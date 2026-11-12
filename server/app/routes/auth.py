"""Session, local-account and OIDC endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from ..config import Settings
from ..deps import CsrfUser, OptionalUser, ServicesDep, limit_auth_attempt, require_same_origin
from ..passwords import hash_password, verify_password
from ..schemas import LocalCredentials, PasswordChange

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

SESSION_COOKIE = "wallpaperwall_session"
CSRF_COOKIE = "wallpaperwall_csrf"
SESSION_MAX_AGE = 14 * 24 * 3600


# The `data:` media types accepted for an avatar. Rendered through an <img>,
# these are inert (no script execution, no external fetches), including
# `image/svg+xml` — which is exactly how authentik delivers its default
# initials avatar for a user without a Gravatar. Any other scheme
# (`javascript:`, `data:text/html`, …) is rejected.
_DATA_AVATAR_PREFIXES = (
    "data:image/png",
    "data:image/jpeg",
    "data:image/jpg",
    "data:image/gif",
    "data:image/webp",
    "data:image/svg+xml",
)


def _safe_avatar_url(value: Any) -> str | None:
    """Persist only an avatar URL the frontend can safely drop into an <img>:
    an http(s) link, or an inline `data:image/*` URI (authentik's initials
    avatar). A hostile provider cannot inject a `javascript:` or `data:text/html`
    value this way, and the length cap keeps a bloated data URI out of the
    session/DB row."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    lowered = candidate.lower()
    if lowered.startswith(("https://", "http://")):
        return candidate if len(candidate) <= 2048 else None
    if lowered.startswith(_DATA_AVATAR_PREFIXES):
        return candidate if len(candidate) <= 65536 else None
    return None


def _set_session_cookies(response: Response, settings: Settings, session_id: str, csrf_token: str) -> None:
    response.set_cookie(SESSION_COOKIE, session_id, httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=SESSION_MAX_AGE, path="/")
    # The CSRF cookie is deliberately readable by the frontend: the double
    # submit value is also validated against the server-side session row.
    response.set_cookie(CSRF_COOKIE, csrf_token, httponly=False, secure=settings.cookie_secure, samesite="lax", max_age=SESSION_MAX_AGE, path="/")


def _session_response(services: ServicesDep, user: dict[str, Any], status_code: int = status.HTTP_200_OK) -> JSONResponse:
    session_id, csrf_token = services.repository.create_session(user["id"])
    response = JSONResponse({"ok": True}, status_code=status_code)
    _set_session_cookies(response, services.settings, session_id, csrf_token)
    return response


@router.get("/me")
def me(request: Request, services: ServicesDep, user: OptionalUser) -> dict[str, Any]:
    settings = services.settings
    payload: dict[str, Any] = {
        "authenticated": bool(user),
        "localEnabled": settings.local_auth_enabled,
        "registrationEnabled": settings.local_auth_enabled and settings.local_registration_enabled,
        "inviteRequired": settings.local_auth_enabled and settings.local_registration_enabled and settings.invite_required,
        "oidcEnabled": settings.oidc_enabled,
    }
    if user:
        payload["user"] = {key: user[key] for key in ("id", "display_name", "email", "role")}
        payload["user"]["avatar_url"] = user.get("avatar_url")
        # Lets the frontend offer password change only to password-backed accounts.
        payload["user"]["local"] = user.get("issuer") == "local"
        payload["csrfToken"] = request.cookies.get(CSRF_COOKIE)
    return payload


@router.post("/local/register", status_code=status.HTTP_201_CREATED)
def local_register(payload: LocalCredentials, request: Request, services: ServicesDep) -> Response:
    settings = services.settings
    if not settings.local_auth_enabled or not settings.local_registration_enabled:
        raise HTTPException(status_code=404, detail="当前未启用账号注册")
    require_same_origin(request)
    limit_auth_attempt(request, services, "register", payload.username)
    if settings.invite_required and (payload.invite_code or "").strip() not in settings.invite_codes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="邀请码无效或缺失")
    try:
        user = services.repository.create_local_user(payload.username, hash_password(payload.password), settings.admin_local_users)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return _session_response(services, user, status.HTTP_201_CREATED)


@router.post("/local/login")
def local_login(payload: LocalCredentials, request: Request, services: ServicesDep) -> Response:
    settings = services.settings
    if not settings.local_auth_enabled:
        raise HTTPException(status_code=404, detail="当前未启用账号登录")
    require_same_origin(request)
    limit_auth_attempt(request, services, "login", payload.username)
    user = services.repository.get_local_user(payload.username)
    if not user or not verify_password(payload.password, user.get("password_hash")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    user = services.repository.reconcile_local_role(user, settings.admin_local_users)
    return _session_response(services, user)


@router.post("/local/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: PasswordChange, request: Request, services: ServicesDep, user: CsrfUser, wallpaperwall_session: Annotated[str | None, Cookie()] = None) -> Response:
    if user.get("issuer") != "local":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前账号不使用密码登录")
    require_same_origin(request)
    if not verify_password(payload.current_password, user.get("password_hash")):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="当前密码不正确")
    services.repository.update_local_password(user["id"], hash_password(payload.new_password))
    # Invalidate every other session so a leaked one cannot outlive the change;
    # the tab making the request keeps its cookies and CSRF token.
    services.repository.delete_user_sessions(user["id"], keep_session_id=wallpaperwall_session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(request: Request, services: ServicesDep, user: CsrfUser, wallpaperwall_session: Annotated[str | None, Cookie()] = None) -> Response:
    """Sign out every other device, keeping the current session active."""
    require_same_origin(request)
    services.repository.delete_user_sessions(user["id"], keep_session_id=wallpaperwall_session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/login")
async def oidc_login(request: Request, services: ServicesDep) -> Response:
    if not services.oauth:
        raise HTTPException(status_code=404, detail="当前未启用 OIDC")
    client = services.oauth.create_client("oidc")
    return await client.authorize_redirect(request, services.settings.oidc_redirect_target)


@router.get("/callback")
async def oidc_callback(request: Request, services: ServicesDep) -> Response:
    if not services.oauth:
        raise HTTPException(status_code=404, detail="当前未启用 OIDC")
    client = services.oauth.create_client("oidc")
    try:
        token = await client.authorize_access_token(request)
    except OAuthError:
        # The user cancelled at the provider or the state/PKCE exchange failed.
        # Return to the wall instead of surfacing a bare 500.
        return RedirectResponse(url="/?auth=denied", status_code=status.HTTP_303_SEE_OTHER)
    claims = token.get("userinfo") or await client.userinfo(token=token)
    subject = str(claims.get("sub") or "")
    if not subject:
        raise HTTPException(status_code=401, detail="OIDC 返回缺少 sub")
    display_name = str(claims.get("name") or claims.get("preferred_username") or subject)
    user = services.repository.upsert_oidc_user(
        services.settings.oidc_issuer,
        subject,
        display_name,
        str(claims["email"]) if claims.get("email") else None,
        services.settings.admin_subjects,
        _safe_avatar_url(claims.get("picture")),
    )
    session_id, csrf_token = services.repository.create_session(user["id"])
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookies(response, services.settings, session_id, csrf_token)
    return response


@router.post("/logout")
def logout(services: ServicesDep, _: CsrfUser, wallpaperwall_session: Annotated[str | None, Cookie()] = None) -> Response:
    services.repository.delete_session(wallpaperwall_session)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response
