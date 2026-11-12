"""Read-only registry and visibility policy for the mounted system catalogue.

The mounted images directory is scanned into catalog.json by the container.
``SystemCatalogRegistry`` caches one immutable snapshot of that file and
reloads it after an atomic rebuild.  ``SystemCatalogService`` layers the
administrator-managed folder visibility policy on top: it decides which
wallpapers a session may list and whether nginx may serve a static asset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any
from urllib.parse import unquote

from .repository import Repository

PUBLIC = "public"
AUTHENTICATED = "authenticated"
ADMIN = "admin"
SYSTEM_VISIBILITIES = (PUBLIC, AUTHENTICATED, ADMIN)


def top_folder(folder_path: str) -> str:
    return folder_path.split("/", 1)[0]


@dataclass(frozen=True)
class CatalogSnapshot:
    version: int
    wallpapers: tuple[dict[str, Any], ...]
    ids: frozenset[str]
    # Static asset path (as referenced by the catalogue, no leading slash)
    # mapped to its wallpaper's top-level folder.
    asset_folders: dict[str, str] = field(default_factory=dict)
    top_folder_counts: dict[str, int] = field(default_factory=dict)


_EMPTY = CatalogSnapshot(version=2, wallpapers=(), ids=frozenset())


def _parse_snapshot(payload: Any) -> CatalogSnapshot:
    if not isinstance(payload, dict):
        return _EMPTY
    wallpapers = [item for item in payload.get("wallpapers", []) if isinstance(item, dict) and item.get("id")]
    ids = frozenset(str(item["id"]) for item in wallpapers)
    asset_folders: dict[str, str] = {}
    counts: dict[str, int] = {}
    for item in wallpapers:
        folder = top_folder(str(item.get("folder", "")))
        if not folder:
            continue
        counts[folder] = counts.get(folder, 0) + 1
        assets = [item.get("thumbnail"), item.get("thumbnailSmall"), item.get("preview"), item.get("homepage"), item.get("placeholder")]
        assets.extend(variant.get("source") for variant in item.get("variants", []) if isinstance(variant, dict))
        for asset in assets:
            if isinstance(asset, str) and asset:
                asset_folders[asset.lstrip("/")] = folder
    return CatalogSnapshot(
        version=int(payload.get("version", 2)),
        wallpapers=tuple(wallpapers),
        ids=ids,
        asset_folders=asset_folders,
        top_folder_counts=counts,
    )


class SystemCatalogRegistry:
    """Caches the catalogue snapshot and reloads after an atomic rebuild."""

    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path
        self._lock = RLock()
        self._mtime_ns = -1
        self._snapshot = _EMPTY

    def snapshot(self) -> CatalogSnapshot:
        try:
            mtime_ns = self.catalog_path.stat().st_mtime_ns
        except FileNotFoundError:
            return _EMPTY
        with self._lock:
            if mtime_ns == self._mtime_ns:
                return self._snapshot
            try:
                payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                # Keep the last complete snapshot while the atomic builder is
                # publishing or storage is transiently unavailable.
                return self._snapshot
            self._mtime_ns = mtime_ns
            self._snapshot = _parse_snapshot(payload)
            return self._snapshot

    def ids(self) -> frozenset[str]:
        return self.snapshot().ids


class SystemCatalogService:
    """Applies the admin-managed folder policy to catalogue reads.

    Policies are cached briefly in memory: the visibility check runs for
    every nginx auth_request subrequest, so it must not open a database
    connection per thumbnail.  Writes invalidate the cache immediately.
    """

    def __init__(self, registry: SystemCatalogRegistry, repository: Repository, cache_seconds: float = 5.0) -> None:
        self.registry = registry
        self.repository = repository
        self._cache_seconds = cache_seconds
        self._lock = RLock()
        self._policies: dict[str, str] = {}
        self._loaded_at = float("-inf")
        self._json_cache: dict[str, tuple[CatalogSnapshot, dict[str, str], str]] = {}

    def _current_policies(self) -> dict[str, str]:
        with self._lock:
            if monotonic() - self._loaded_at > self._cache_seconds:
                fresh = self.repository.list_system_policies()
                # Keep the same object when nothing changed so identity-keyed
                # caches (the serialized catalogue) stay warm across refreshes.
                if fresh != self._policies:
                    self._policies = fresh
                self._loaded_at = monotonic()
            return self._policies

    def invalidate(self) -> None:
        with self._lock:
            self._loaded_at = float("-inf")

    @staticmethod
    def _allowed(visibility: str, user: dict[str, Any] | None) -> bool:
        if visibility == PUBLIC:
            return True
        if visibility == AUTHENTICATED:
            return user is not None
        return bool(user) and user.get("role") == "admin"

    def folder_visibility(self, folder: str) -> str:
        return self._current_policies().get(folder, PUBLIC)

    def visible_wallpapers(self, user: dict[str, Any] | None) -> dict[str, Any]:
        snapshot = self.registry.snapshot()
        policies = self._current_policies()
        if not policies:
            wallpapers = list(snapshot.wallpapers)
        else:
            wallpapers = [
                item for item in snapshot.wallpapers
                if self._allowed(policies.get(top_folder(str(item.get("folder", ""))), PUBLIC), user)
            ]
        return {"version": snapshot.version, "count": len(wallpapers), "wallpapers": wallpapers}

    @staticmethod
    def _access_class(user: dict[str, Any] | None) -> str:
        if user is None:
            return "anonymous"
        return "admin" if user.get("role") == "admin" else "authenticated"

    def visible_wallpapers_json(self, user: dict[str, Any] | None) -> str:
        """Serialized catalogue for the current session's access class.

        Filtering depends only on anonymous/authenticated/admin, so at most
        three serializations exist per (snapshot, policies) generation; large
        catalogues are not re-serialized on every request.
        """
        snapshot = self.registry.snapshot()
        policies = self._current_policies()
        klass = self._access_class(user)
        with self._lock:
            cached = self._json_cache.get(klass)
            if cached and cached[0] is snapshot and cached[1] is policies:
                return cached[2]
        payload = json.dumps(self.visible_wallpapers(user), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._json_cache[klass] = (snapshot, policies, payload)
        return payload

    def accessible_ids(self, user: dict[str, Any] | None) -> set[str]:
        snapshot = self.registry.snapshot()
        policies = self._current_policies()
        if not policies:
            return set(snapshot.ids)
        return {
            str(item["id"]) for item in snapshot.wallpapers
            if self._allowed(policies.get(top_folder(str(item.get("folder", ""))), PUBLIC), user)
        }

    def public_wallpaper_variant(self, wallpaper_id: str, variant_source: str) -> dict[str, Any] | None:
        """Return one variant only when anonymous visitors may load it.

        Homepage backgrounds are intentionally global, so a private or merely
        authenticated gallery asset must never be promoted into this channel.
        """
        for wallpaper in self.visible_wallpapers(None)["wallpapers"]:
            if str(wallpaper.get("id")) != wallpaper_id:
                continue
            for variant in wallpaper.get("variants", []):
                if isinstance(variant, dict) and variant.get("source") == variant_source:
                    homepage = wallpaper.get("homepage")
                    if isinstance(homepage, str) and homepage.startswith("public/homepage/"):
                        return {"wallpaper": wallpaper, "variant": variant, "homepage": homepage}
                    return None
            return None
        return None

    def list_top_folders(self) -> list[dict[str, Any]]:
        snapshot = self.registry.snapshot()
        policies = self._current_policies()
        return [
            {"path": folder, "wallpapers": count, "visibility": policies.get(folder, PUBLIC)}
            for folder, count in sorted(snapshot.top_folder_counts.items())
        ]

    def set_folder_visibility(self, folder: str, visibility: str) -> None:
        if visibility not in SYSTEM_VISIBILITIES:
            raise ValueError("未知可见性")
        if folder not in self.registry.snapshot().top_folder_counts:
            raise LookupError("挂载目录中不存在该文件夹")
        self.repository.set_system_policy(folder, None if visibility == PUBLIC else visibility)
        self.invalidate()

    def authorize_asset(self, uri: str, user: dict[str, Any] | None) -> bool:
        """Authorize one static media URI for nginx's auth_request.

        /images/... paths carry their folder in the path itself.  Thumbnail
        names are content hashes, so an entry missing from the snapshot map
        (e.g. mid-rebuild) is unguessable and allowed by default.
        """
        path = unquote(uri.split("?", 1)[0]).lstrip("/")
        if ".." in path.split("/"):
            return False
        if path.startswith("images/"):
            remainder = path.removeprefix("images/")
            if "/" not in remainder:
                # A bare file in the images root belongs to no folder policy.
                return True
            return self._allowed(self.folder_visibility(top_folder(remainder)), user)
        folder = self.registry.snapshot().asset_folders.get(path)
        if folder is None:
            return True
        return self._allowed(self.folder_visibility(folder), user)
