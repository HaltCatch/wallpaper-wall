"""System catalogue delivery, mounted-folder policy management and the
authorization hook nginx uses before serving static media."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from ..catalog import SYSTEM_VISIBILITIES
from ..deps import AdminUser, CsrfUser, OptionalUser, ServicesDep

router = APIRouter(prefix="/api/v1", tags=["catalog"])


class SystemPolicyUpdate(BaseModel):
    visibility: str


@router.get("/catalog")
def catalog(services: ServicesDep, user: OptionalUser) -> Response:
    """The mounted catalogue, filtered by the per-folder visibility policy.

    Served by the API instead of as a static file so hidden folders never
    reach a session that may not list them.  The serialized payload is cached
    per access class (anonymous/authenticated/admin) until the snapshot or a
    policy changes.
    """
    payload = services.system_catalog.visible_wallpapers_json(user)
    return Response(payload, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/system-folders")
def system_folders(services: ServicesDep, _: AdminUser) -> dict[str, Any]:
    return {"folders": services.system_catalog.list_top_folders(), "visibilities": list(SYSTEM_VISIBILITIES)}


@router.put("/system-folders/{folder_path:path}")
def set_system_folder(folder_path: str, payload: SystemPolicyUpdate, services: ServicesDep, user: CsrfUser) -> dict[str, bool]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    try:
        services.system_catalog.set_folder_visibility(folder_path, payload.visibility)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"ok": True}


@router.get("/authz/media")
def authorize_media(request: Request, services: ServicesDep, user: OptionalUser) -> Response:
    """nginx auth_request hook for /images/** and /public/thumbs/**.

    Returns 204 to allow the static file, 401/403 to deny; nginx maps both
    denials to 404 so hidden folders do not reveal their existence.
    """
    uri = request.headers.get("X-Original-URI", "")
    if not uri:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if services.system_catalog.authorize_asset(uri, user):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED if user is None else status.HTTP_403_FORBIDDEN)
