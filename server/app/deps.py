"""Request-scoped dependencies shared by all routers.

Routers never build services themselves: the composition root wires a single
``Services`` container onto ``app.state`` and everything else resolves from
the current request.  This keeps route modules import-cycle free and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from authlib.integrations.starlette_client import OAuth
from fastapi import Cookie, Depends, HTTPException, Request, status

from .catalog import SystemCatalogService
from .config import Settings
from .favorite_service import FavoriteService
from .library_service import UserLibraryService
from .rate_limit import SlidingWindowRateLimiter
from .repository import Repository
from .storage import StorageRouter
from .uploads import UploadService


@dataclass(frozen=True)
class Services:
    settings: Settings
    repository: Repository
    storage: StorageRouter
    system_catalog: SystemCatalogService
    favorite_service: FavoriteService
    library_service: UserLibraryService
    upload_service: UploadService
    auth_limiter: SlidingWindowRateLimiter
    upload_limiter: SlidingWindowRateLimiter
    oauth: OAuth | None


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


def optional_user(services: ServicesDep, wallpaperwall_session: Annotated[str | None, Cookie()] = None) -> dict[str, Any] | None:
    return services.repository.get_session_user(wallpaperwall_session)


OptionalUser = Annotated[dict[str, Any] | None, Depends(optional_user)]


def require_user(user: OptionalUser) -> dict[str, Any]:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要登录")
    return user


RequiredUser = Annotated[dict[str, Any], Depends(require_user)]


def require_admin(user: RequiredUser) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def public_base_url(request: Request) -> str:
    settings: Settings = request.app.state.services.settings
    return settings.public_origin or str(request.base_url).rstrip("/")


def require_same_origin(request: Request) -> None:
    """Reject browser mutations from any origin except the public site.

    An explicit public origin keeps this check stable behind one or more
    reverse proxies.  Direct/local deployments can leave it empty and use the
    origin reconstructed by Uvicorn from the forwarded request.
    """
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") != public_base_url(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不允许跨站请求")


def require_csrf_user(
    request: Request,
    services: ServicesDep,
    user: RequiredUser,
    wallpaperwall_session: Annotated[str | None, Cookie()] = None,
    wallpaperwall_csrf: Annotated[str | None, Cookie()] = None,
) -> dict[str, Any]:
    supplied = request.headers.get("X-CSRF-Token")
    if supplied != wallpaperwall_csrf or not services.repository.is_valid_csrf(wallpaperwall_session, supplied):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败")
    require_same_origin(request)
    return user


CsrfUser = Annotated[dict[str, Any], Depends(require_csrf_user)]
AdminUser = Annotated[dict[str, Any], Depends(require_admin)]


def external_url(request: Request, route_name: str, **path_params: str) -> str:
    path = request.app.url_path_for(route_name, **path_params)
    return f"{public_base_url(request)}{path}"


def limit_auth_attempt(request: Request, services: Services, action: str, username: str) -> None:
    client = request.client.host if request.client else "unknown"
    settings = services.settings
    for key in (f"{action}:client:{client}", f"{action}:account:{username.casefold()}"):
        retry_after = services.auth_limiter.retry_after(key, settings.auth_rate_limit_attempts, settings.auth_rate_limit_window_seconds)
        if retry_after is not None:
            raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试", headers={"Retry-After": str(retry_after)})


def limit_upload_attempt(services: Services, user_id: str) -> None:
    """Cap uploads per authenticated account per minute (0 disables). Guards the
    ingest pipeline against a single account flooding it within its quota."""
    per_minute = services.settings.upload_rate_limit_per_minute
    if per_minute <= 0:
        return
    retry_after = services.upload_limiter.retry_after(f"upload:user:{user_id}", per_minute, 60)
    if retry_after is not None:
        raise HTTPException(status_code=429, detail="上传过于频繁，请稍后再试", headers={"Retry-After": str(retry_after)})
