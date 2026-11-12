"""ACL-checked media listing and delivery."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from ..deps import CsrfUser, OptionalUser, ServicesDep, external_url
from ..filenames import content_disposition, safe_filename
from ..tickets import issue_ticket, verify_ticket

router = APIRouter(prefix="/api/v1", tags=["media"])


@router.get("/wallpapers/user")
def user_wallpapers(request: Request, services: ServicesDep, user: OptionalUser) -> dict[str, list[dict[str, Any]]]:
    items = services.repository.list_accessible_user_wallpapers(user)
    for item in items:
        for asset in [*item["variants"], item.get("thumbnail"), item.get("thumbnail_small")]:
            if asset:
                asset["mediaUrl"] = external_url(request, "media", media_id=asset["media_id"], filename=safe_filename(asset["original_name"]))
    return {"wallpapers": items}


@router.get("/media/{media_id}/{filename}", name="media")
def media(media_id: str, filename: str, services: ServicesDep, user: OptionalUser, token: str | None = None) -> Response:
    object_info = services.repository.media_for_download(media_id, user)
    if not object_info and verify_ticket(services.settings.session_secret, media_id, token):
        object_info = services.repository.media_by_id(media_id)
    if not object_info:
        raise HTTPException(status_code=404, detail="媒体不存在或无权访问")
    try:
        # Every object is served by the backend it was uploaded to, so a
        # storage-driver switch never breaks previously published media.
        backend = services.storage.for_driver(str(object_info.get("storage_driver") or "local"))
    except LookupError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    actual_name = safe_filename(object_info["original_name"])
    if backend.supports_signed_urls:
        return RedirectResponse(backend.signed_download_url(object_info["object_key"], actual_name, services.settings.media_url_ttl_seconds))
    headers = {"Content-Disposition": content_disposition(actual_name)}

    def stream_local_object() -> Iterator[bytes]:
        with backend.open(object_info["object_key"]) as stream:
            while chunk := stream.read(1024 * 1024):
                yield chunk

    return StreamingResponse(stream_local_object(), media_type=object_info["mime_type"], headers=headers)


@router.post("/media/{media_id}/{filename}/link")
def media_link(request: Request, media_id: str, filename: str, services: ServicesDep, user: CsrfUser) -> dict[str, str | int]:
    object_info = services.repository.media_for_download(media_id, user)
    if not object_info:
        raise HTTPException(status_code=404, detail="媒体不存在或无权访问")
    url = external_url(request, "media", media_id=media_id, filename=safe_filename(object_info["original_name"]))
    ticket = issue_ticket(services.settings.session_secret, media_id, services.settings.media_url_ttl_seconds)
    return {"url": f"{url}?token={ticket}", "expiresIn": services.settings.media_url_ttl_seconds}
