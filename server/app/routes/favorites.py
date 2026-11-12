"""Account favourites, including the one-time guest merge."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import CsrfUser, RequiredUser, ServicesDep
from ..schemas import FavoriteMerge

router = APIRouter(prefix="/api/v1/favorites", tags=["favorites"])


@router.get("")
def favorites(services: ServicesDep, user: RequiredUser) -> dict[str, list[str]]:
    return {"wallpaperIds": services.favorite_service.list_ids(user)}


@router.put("/{wallpaper_id}")
def favorite(wallpaper_id: str, services: ServicesDep, user: CsrfUser) -> dict[str, bool]:
    try:
        services.favorite_service.add(user, wallpaper_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"ok": True}


@router.delete("/{wallpaper_id}")
def unfavorite(wallpaper_id: str, services: ServicesDep, user: CsrfUser) -> dict[str, bool]:
    services.repository.remove_favorite(user["id"], wallpaper_id)
    return {"ok": True}


@router.post("/merge")
def merge_favorites(payload: FavoriteMerge, services: ServicesDep, user: CsrfUser) -> dict[str, list[str]]:
    return {"wallpaperIds": services.favorite_service.merge(user, payload.wallpaper_ids)}
