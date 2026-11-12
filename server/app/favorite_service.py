"""Favourite policy shared by single-item and guest-merge operations."""

from __future__ import annotations

from typing import Any

from .catalog import SystemCatalogService
from .repository import Repository


class FavoriteService:
    def __init__(self, repository: Repository, system_catalog: SystemCatalogService) -> None:
        self.repository = repository
        self.system_catalog = system_catalog

    def _accessible_ids(self, user: dict[str, Any]) -> set[str]:
        return self.system_catalog.accessible_ids(user) | self.repository.accessible_user_wallpaper_ids(user)

    def list_ids(self, user: dict[str, Any]) -> list[str]:
        accessible = self._accessible_ids(user)
        return [wallpaper_id for wallpaper_id in self.repository.list_favorite_ids(user["id"]) if wallpaper_id in accessible]

    def add(self, user: dict[str, Any], wallpaper_id: str) -> None:
        if wallpaper_id not in self._accessible_ids(user):
            raise LookupError("壁纸不存在或无权访问")
        self.repository.add_favorite(user["id"], wallpaper_id)

    def merge(self, user: dict[str, Any], wallpaper_ids: list[str]) -> list[str]:
        accessible = self._accessible_ids(user)
        valid = [wallpaper_id for wallpaper_id in wallpaper_ids if wallpaper_id in accessible]
        self.repository.merge_favorites(user["id"], valid)
        return self.list_ids(user)
