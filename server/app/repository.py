"""SQLite repositories and policy queries.

All SQL is confined here. API handlers receive DTO-like dictionaries and do
not need to know table shape or authorization joins.

Access control vocabulary used throughout this module:

* Effective ACL — a folder with ``inherit_acl = 1`` takes its visibility and
  viewer grants from the nearest ancestor with ``inherit_acl = 0``; root
  folders are always their own source.  ``_ACL_CTE`` resolves that mapping.
* Managed folder — the folder owner can always manage; folders flagged
  ``is_official`` can additionally be managed by any administrator.  Official
  content is the built-in gallery shown to everyone.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .database import Database


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid4())


class QuotaExceededError(ValueError):
    """The owner's storage quota does not allow this upload."""


@dataclass(frozen=True)
class MediaAsset:
    object_key: str
    original_name: str
    mime_type: str
    byte_count: int
    width: int
    height: int
    sha256: str
    kind: str


# Maps every folder to the folder whose visibility/grants apply to it.
_ACL_CTE = """
acl_walk(folder_id, node_id, inherit, parent_id) AS (
  SELECT id, id, inherit_acl, parent_id FROM folders
  UNION ALL
  SELECT acl_walk.folder_id, folders.id, folders.inherit_acl, folders.parent_id
  FROM acl_walk JOIN folders ON folders.id = acl_walk.parent_id
  WHERE acl_walk.inherit = 1
),
acl_source(folder_id, source_id) AS (
  SELECT folder_id, node_id FROM acl_walk WHERE inherit = 0 OR parent_id IS NULL
)
"""

# Visibility predicate evaluated against the resolved ACL source folder
# (aliased ``acl``) and a grants join (aliased ``folder_grants``).
_VISIBLE_PREDICATE = """(
  folders.owner_id = :user_id
  OR acl.visibility = 'public'
  OR (acl.visibility = 'authenticated' AND :user_id IS NOT NULL)
  OR folder_grants.user_id IS NOT NULL
)"""

# The folder owner manages their own tree; administrators manage any official
# folder.  Role is read from the database so the check cannot drift from a
# stale session dictionary.
_MANAGED_PREDICATE = """(
  folders.owner_id = :user_id
  OR (folders.is_official = 1
      AND EXISTS(SELECT 1 FROM users WHERE users.id = :user_id AND users.role = 'admin'))
)"""

class Repository:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ------------------------------------------------------------------ users

    def upsert_oidc_user(self, issuer: str, subject: str, display_name: str, email: str | None, admins: tuple[str, ...], avatar_url: str | None = None) -> dict[str, Any]:
        now = utcnow()
        identity = f"{issuer}|{subject}"
        with self.database.transaction() as db:
            user = db.execute("SELECT * FROM users WHERE issuer = ? AND subject = ?", (issuer, subject)).fetchone()
            role = "admin" if identity in admins else "user"
            if user:
                db.execute("UPDATE users SET display_name = ?, email = ?, avatar_url = ?, role = ?, updated_at = ? WHERE id = ?", (display_name, email, avatar_url, role, now, user["id"]))
                user = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
            else:
                user_id = new_id()
                db.execute("INSERT INTO users(id, issuer, subject, display_name, email, avatar_url, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (user_id, issuer, subject, display_name, email, avatar_url, role, now, now))
                user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(user)

    def create_local_user(self, username: str, password_hash: str, admin_usernames: tuple[str, ...]) -> dict[str, Any]:
        """Create a password-backed identity without coupling it to HTTP."""
        normalized = username.casefold()
        now = utcnow()
        user_id = new_id()
        role = "admin" if normalized in admin_usernames else "user"
        try:
            with self.database.transaction() as db:
                db.execute(
                    """INSERT INTO users(id, issuer, subject, username, password_hash, display_name, role, created_at, updated_at)
                    VALUES (?, 'local', ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, normalized, normalized, password_hash, username, role, now, now),
                )
                row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        except sqlite3.IntegrityError as error:
            raise ValueError("用户名已被使用") from error
        return dict(row)

    def get_local_user(self, username: str) -> dict[str, Any] | None:
        with self.database.connection() as db:
            row = db.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND password_hash IS NOT NULL",
                (username.casefold(),),
            ).fetchone()
        return dict(row) if row else None

    def reconcile_local_role(self, user: dict[str, Any], admin_usernames: tuple[str, ...]) -> dict[str, Any]:
        expected = "admin" if str(user.get("username") or "").casefold() in admin_usernames else "user"
        if user["role"] == expected:
            return user
        with self.database.transaction() as db:
            db.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ? AND issuer = 'local'", (expected, utcnow(), user["id"]))
            row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        return dict(row)

    def update_local_password(self, user_id: str, new_hash: str) -> None:
        with self.database.transaction() as db:
            db.execute("UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ? AND issuer = 'local'", (new_hash, utcnow(), user_id))

    # --------------------------------------------------------------- sessions

    def delete_user_sessions(self, user_id: str, keep_session_id: str | None = None) -> None:
        """Revoke every session for a user, optionally sparing the current one
        (used after a password change / for 'log out other devices')."""
        with self.database.transaction() as db:
            if keep_session_id:
                db.execute("DELETE FROM sessions WHERE user_id = ? AND id != ?", (user_id, keep_session_id))
            else:
                db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    def create_session(self, user_id: str, lifetime_days: int = 14) -> tuple[str, str]:
        session_id = new_id()
        csrf_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires = now + timedelta(days=lifetime_days)
        with self.database.transaction() as db:
            db.execute("INSERT INTO sessions(id, user_id, csrf_token, expires_at, created_at) VALUES (?, ?, ?, ?, ?)", (session_id, user_id, csrf_token, expires.isoformat(), now.isoformat()))
        return session_id, csrf_token

    def get_session_user(self, session_id: str | None) -> dict[str, Any] | None:
        if not session_id:
            return None
        with self.database.connection() as db:
            row = db.execute("SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.id = ? AND sessions.expires_at > ?", (session_id, utcnow())).fetchone()
        return dict(row) if row else None

    def prune_expired_sessions(self) -> None:
        with self.database.transaction() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (utcnow(),))

    def is_valid_csrf(self, session_id: str | None, csrf_token: str | None) -> bool:
        if not session_id or not csrf_token:
            return False
        with self.database.connection() as db:
            row = db.execute("SELECT 1 FROM sessions WHERE id = ? AND csrf_token = ? AND expires_at > ?", (session_id, csrf_token, utcnow())).fetchone()
        return row is not None

    def delete_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        with self.database.transaction() as db:
            db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # ---------------------------------------------------------------- folders

    def _managed_folder(self, db: sqlite3.Connection, folder_id: str, user_id: str) -> sqlite3.Row | None:
        return db.execute(
            f"SELECT * FROM folders WHERE id = :folder_id AND source_scope = 'user' AND {_MANAGED_PREDICATE}",
            {"folder_id": folder_id, "user_id": user_id},
        ).fetchone()

    def create_folder(self, user_id: str, name: str, parent_id: str | None, official: bool = False, is_admin: bool = False) -> dict[str, Any]:
        now = utcnow()
        folder_id = new_id()
        try:
            with self.database.transaction() as db:
                if parent_id:
                    parent = self._managed_folder(db, parent_id, user_id)
                    if not parent:
                        raise PermissionError("cannot create in this folder")
                    is_official = bool(parent["is_official"])
                    inherit_acl = 1
                    visibility = "private"
                else:
                    is_official = official
                    inherit_acl = 0
                    visibility = "public" if official else "private"
                if is_official and not is_admin:
                    raise PermissionError("only administrators manage the official library")
                # Official siblings are deduplicated across all administrators;
                # personal siblings only within the owner's own tree.
                duplicate = db.execute(
                    """SELECT 1 FROM folders WHERE parent_id IS :parent_id AND name = :name COLLATE NOCASE
                       AND (is_official = 1) = :official AND (:official OR owner_id = :owner_id)""",
                    {"parent_id": parent_id, "name": name, "official": is_official, "owner_id": user_id},
                ).fetchone()
                if duplicate:
                    raise ValueError("同级文件夹名称已存在")
                db.execute(
                    "INSERT INTO folders(id, source_scope, owner_id, parent_id, name, visibility, inherit_acl, is_official, created_at, updated_at) VALUES (?, 'user', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (folder_id, user_id, parent_id, name, visibility, inherit_acl, int(is_official), now, now),
                )
                row = db.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
        except sqlite3.IntegrityError as error:
            raise ValueError("同级文件夹名称已存在") from error
        return dict(row)

    def list_personal_folders(self, owner_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM folders WHERE owner_id = ? AND is_official = 0 ORDER BY name COLLATE NOCASE", (owner_id,))]

    def list_official_folders(self) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM folders WHERE is_official = 1 ORDER BY name COLLATE NOCASE")]

    def get_managed_folder(self, folder_id: str, user_id: str) -> dict[str, Any] | None:
        with self.database.connection() as db:
            row = self._managed_folder(db, folder_id, user_id)
        return dict(row) if row else None

    def update_folder(self, folder_id: str, user_id: str, name: str | None, visibility: str | None, inherit_acl: bool | None = None) -> dict[str, Any] | None:
        try:
            with self.database.transaction() as db:
                current = self._managed_folder(db, folder_id, user_id)
                if not current:
                    return None
                if name is not None and db.execute(
                    """SELECT 1 FROM folders WHERE parent_id IS :parent_id AND name = :name COLLATE NOCASE AND id != :folder_id
                       AND (is_official = 1) = :official AND (:official OR owner_id = :owner_id)""",
                    {"parent_id": current["parent_id"], "name": name, "folder_id": folder_id, "official": bool(current["is_official"]), "owner_id": current["owner_id"]},
                ).fetchone():
                    raise ValueError("同级文件夹名称已存在")
                updates: list[str] = ["updated_at = ?"]
                values: list[Any] = [utcnow()]
                if name is not None:
                    updates.append("name = ?")
                    values.append(name)
                if visibility is not None:
                    updates.append("visibility = ?")
                    values.append(visibility)
                if inherit_acl is not None:
                    if inherit_acl and not current["parent_id"]:
                        raise ValueError("根文件夹必须使用显式权限")
                    updates.append("inherit_acl = ?")
                    values.append(int(inherit_acl))
                db.execute(f"UPDATE folders SET {', '.join(updates)} WHERE id = ?", [*values, folder_id])
                row = db.execute("SELECT * FROM folders WHERE id = ?", (folder_id,)).fetchone()
        except sqlite3.IntegrityError as error:
            raise ValueError("同级文件夹名称已存在") from error
        return dict(row) if row else None

    def delete_folder(self, folder_id: str, user_id: str) -> bool:
        with self.database.transaction() as db:
            folder = self._managed_folder(db, folder_id, user_id)
            if not folder:
                return False
            has_content = db.execute(
                """SELECT EXISTS(SELECT 1 FROM folders WHERE parent_id = ?)
                    OR EXISTS(SELECT 1 FROM wallpapers WHERE folder_id = ? AND status != 'deleted')""",
                (folder_id, folder_id),
            ).fetchone()[0]
            if has_content:
                raise ValueError("文件夹包含子文件夹或壁纸，请先清空")
            result = db.execute("DELETE FROM folders WHERE id = ?", (folder_id,))
        return result.rowcount == 1

    def delete_folder_media(self, folder_id: str, user_id: str) -> list[tuple[str, str]]:
        """Delete folder metadata and return (object_key, storage_driver) pairs."""
        with self.database.transaction() as db:
            folder = self._managed_folder(db, folder_id, user_id)
            if not folder:
                raise PermissionError("not a managed folder")
            keys = {
                (row["object_key"], row["storage_driver"] or "local")
                for row in db.execute(
                    """SELECT media_objects.object_key, media_objects.storage_driver FROM media_objects
                       JOIN wallpapers ON wallpapers.id = media_objects.wallpaper_id
                       WHERE wallpapers.folder_id = ?
                       UNION SELECT object_key, storage_driver FROM uploads WHERE folder_id = ?""",
                    (folder_id, folder_id),
                )
            }
            db.execute("DELETE FROM wallpapers WHERE folder_id = ? AND source_scope = 'user'", (folder_id,))
            db.execute("DELETE FROM uploads WHERE folder_id = ?", (folder_id,))
        return list(keys)

    def backfill_storage_driver(self, configured_driver: str) -> None:
        """Stamp legacy rows (pre-0006) with the driver configured today,
        which is where those objects physically live."""
        with self.database.transaction() as db:
            db.execute("UPDATE media_objects SET storage_driver = ? WHERE storage_driver = ''", (configured_driver,))
            db.execute("UPDATE uploads SET storage_driver = ? WHERE storage_driver = ''", (configured_driver,))

    # ----------------------------------------------------------------- grants

    def replace_grants_by_identifiers(self, folder_id: str, user_id: str, identifiers: list[str]) -> None:
        """Replace viewer grants using local usernames or exact OIDC emails."""
        normalized = list(dict.fromkeys(value.strip() for value in identifiers if value.strip()))
        with self.database.transaction() as db:
            folder = self._managed_folder(db, folder_id, user_id)
            if not folder:
                raise PermissionError("not a managed folder")
            resolved: list[str] = []
            unresolved: list[str] = []
            for identifier in normalized:
                rows = db.execute(
                    """SELECT id FROM users WHERE id = ?
                       OR (username IS NOT NULL AND username = ? COLLATE NOCASE)
                       OR (email IS NOT NULL AND email = ? COLLATE NOCASE)""",
                    (identifier, identifier, identifier),
                ).fetchall()
                unique_ids = {row["id"] for row in rows if row["id"] != folder["owner_id"]}
                if len(unique_ids) != 1:
                    unresolved.append(identifier)
                else:
                    resolved.extend(unique_ids)
            if unresolved:
                raise ValueError(f"找不到或无法唯一确定账号：{', '.join(unresolved)}")
            db.execute("DELETE FROM folder_grants WHERE folder_id = ?", (folder_id,))
            now = utcnow()
            for grantee in set(resolved):
                db.execute("INSERT INTO folder_grants(folder_id, user_id, role, created_at) VALUES (?, ?, 'viewer', ?)", (folder_id, grantee, now))

    def list_grants(self, folder_id: str, user_id: str) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            if not self._managed_folder(db, folder_id, user_id):
                return []
            return [
                dict(row)
                for row in db.execute(
                    "SELECT users.id, users.username, users.display_name, users.email FROM folder_grants JOIN users ON users.id = folder_grants.user_id WHERE folder_grants.folder_id = ?",
                    (folder_id,),
                )
            ]

    # -------------------------------------------------------------- favorites

    def add_favorite(self, user_id: str, wallpaper_id: str) -> None:
        with self.database.transaction() as db:
            db.execute("INSERT OR IGNORE INTO favorites(user_id, wallpaper_id, created_at) VALUES (?, ?, ?)", (user_id, wallpaper_id, utcnow()))

    def remove_favorite(self, user_id: str, wallpaper_id: str) -> None:
        with self.database.transaction() as db:
            db.execute("DELETE FROM favorites WHERE user_id = ? AND wallpaper_id = ?", (user_id, wallpaper_id))

    def list_favorite_ids(self, user_id: str) -> list[str]:
        with self.database.connection() as db:
            return [row["wallpaper_id"] for row in db.execute("SELECT wallpaper_id FROM favorites WHERE user_id = ? ORDER BY created_at DESC", (user_id,))]

    def merge_favorites(self, user_id: str, wallpaper_ids: list[str]) -> list[str]:
        with self.database.transaction() as db:
            now = utcnow()
            for wallpaper_id in set(wallpaper_ids):
                db.execute("INSERT OR IGNORE INTO favorites(user_id, wallpaper_id, created_at) VALUES (?, ?, ?)", (user_id, wallpaper_id, now))
        return self.list_favorite_ids(user_id)

    # ------------------------------------------------------ visibility policy

    def accessible_user_wallpaper_ids(self, user: dict[str, Any] | None) -> set[str]:
        user_id = user["id"] if user else None
        with self.database.connection() as db:
            rows = db.execute(
                f"""WITH RECURSIVE {_ACL_CTE}
                   SELECT DISTINCT wallpapers.id FROM wallpapers
                   JOIN folders ON folders.id = wallpapers.folder_id
                   JOIN acl_source ON acl_source.folder_id = folders.id
                   JOIN folders acl ON acl.id = acl_source.source_id
                   LEFT JOIN folder_grants ON folder_grants.folder_id = acl.id AND folder_grants.user_id = :user_id
                   WHERE wallpapers.source_scope = 'user' AND wallpapers.status = 'ready' AND {_VISIBLE_PREDICATE}""",
                {"user_id": user_id},
            ).fetchall()
        return {row["id"] for row in rows}

    def media_for_download(self, media_id: str, user: dict[str, Any] | None) -> dict[str, Any] | None:
        user_id = user["id"] if user else None
        with self.database.connection() as db:
            row = db.execute(
                f"""WITH RECURSIVE {_ACL_CTE}
                SELECT media_objects.*, wallpapers.title FROM media_objects
                JOIN wallpapers ON wallpapers.id = media_objects.wallpaper_id
                JOIN folders ON folders.id = wallpapers.folder_id
                JOIN acl_source ON acl_source.folder_id = folders.id
                JOIN folders acl ON acl.id = acl_source.source_id
                LEFT JOIN folder_grants ON folder_grants.folder_id = acl.id AND folder_grants.user_id = :user_id
                WHERE media_objects.id = :media_id AND wallpapers.status = 'ready' AND {_VISIBLE_PREDICATE}""",
                {"user_id": user_id, "media_id": media_id},
            ).fetchone()
        return dict(row) if row else None

    def media_by_id(self, media_id: str) -> dict[str, Any] | None:
        with self.database.connection() as db:
            row = db.execute("SELECT media_objects.*, wallpapers.title FROM media_objects JOIN wallpapers ON wallpapers.id = media_objects.wallpaper_id WHERE media_objects.id = ? AND wallpapers.status = 'ready'", (media_id,)).fetchone()
        return dict(row) if row else None

    def list_accessible_user_wallpapers(self, user: dict[str, Any] | None) -> list[dict[str, Any]]:
        user_id = user["id"] if user else None
        with self.database.connection() as db:
            rows = db.execute(
                f"""WITH RECURSIVE {_ACL_CTE},
                folder_paths(id, path) AS (
                  SELECT id, name FROM folders WHERE parent_id IS NULL
                  UNION ALL
                  SELECT child.id, folder_paths.path || '/' || child.name
                  FROM folders child JOIN folder_paths ON child.parent_id = folder_paths.id
                )
                SELECT wallpapers.id AS wallpaper_id, wallpapers.title, wallpapers.created_at, wallpapers.updated_at,
                       folders.id AS folder_id, folders.owner_id, folders.is_official, folder_paths.path AS folder_path,
                       acl.visibility AS effective_visibility,
                       owners.display_name AS owner_name,
                       media_objects.id AS media_id, media_objects.object_key, media_objects.original_name,
                       media_objects.mime_type, media_objects.bytes, media_objects.width, media_objects.height,
                       media_objects.sha256, media_objects.kind, media_objects.source_media_id
                FROM wallpapers JOIN folders ON folders.id = wallpapers.folder_id
                JOIN folder_paths ON folder_paths.id = folders.id
                JOIN acl_source ON acl_source.folder_id = folders.id
                JOIN folders acl ON acl.id = acl_source.source_id
                JOIN users owners ON owners.id = folders.owner_id
                JOIN media_objects ON media_objects.wallpaper_id = wallpapers.id
                LEFT JOIN folder_grants ON folder_grants.folder_id = acl.id AND folder_grants.user_id = :user_id
                WHERE wallpapers.source_scope = 'user' AND wallpapers.status = 'ready' AND {_VISIBLE_PREDICATE}
                ORDER BY wallpapers.created_at DESC, media_objects.created_at ASC""",
                {"user_id": user_id},
            ).fetchall()
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            wallpaper_id = row["wallpaper_id"]
            item = grouped.setdefault(wallpaper_id, {
                "id": wallpaper_id,
                "title": row["title"],
                "folder_id": row["folder_id"],
                "folder_path": row["folder_path"],
                "owner_id": row["owner_id"],
                "owner_name": row["owner_name"],
                "visibility": row["effective_visibility"],
                "official": bool(row["is_official"]),
                "owned": row["owner_id"] == user_id,
                "created_at": row["created_at"],
                "variants": [],
                "derivatives": [],
            })
            media = {key: row[key] for key in ("media_id", "object_key", "original_name", "mime_type", "bytes", "width", "height", "sha256", "kind", "source_media_id")}
            item["variants" if row["kind"] == "original" else "derivatives"].append(media)
        result: list[dict[str, Any]] = []
        for item in grouped.values():
            variants = item["variants"]
            if not variants:
                continue
            variants.sort(key=lambda value: (value["width"] * value["height"], value["media_id"]), reverse=True)
            primary = variants[0]
            matching = [asset for asset in item.pop("derivatives") if asset["source_media_id"] in {None, primary["media_id"]}]
            by_kind = {asset["kind"]: asset for asset in matching}
            item["primary"] = primary
            item["thumbnail"] = by_kind.get("thumbnail")
            item["thumbnail_small"] = by_kind.get("thumbnail_small")
            item["width"] = primary["width"]
            item["height"] = primary["height"]
            result.append(item)
        return result

    # ---------------------------------------------------------------- uploads

    def create_upload(self, folder_id: str, user_id: str, original_name: str, expected_bytes: int | None, max_owner_bytes: int = 0, storage_driver: str = "local") -> dict[str, Any]:
        upload_id = new_id()
        now = utcnow()
        suffix = Path(original_name).suffix.lower()
        suffix = suffix if suffix in {".png", ".jpg", ".jpeg", ".webp"} else ".img"
        object_key = f"users/{user_id}/uploads/{upload_id}/original{suffix}"
        with self.database.transaction() as db:
            folder = self._managed_folder(db, folder_id, user_id)
            if not folder:
                raise PermissionError("not a managed folder")
            # The official library is operated by administrators and exempt
            # from per-user quotas.
            if max_owner_bytes and expected_bytes and not folder["is_official"]:
                self._ensure_quota(db, user_id, expected_bytes, max_owner_bytes, include_reserved=True)
            db.execute(
                "INSERT INTO uploads(id, folder_id, owner_id, object_key, original_name, state, expected_bytes, storage_driver, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'created', ?, ?, ?, ?)",
                (upload_id, folder_id, user_id, object_key, original_name, expected_bytes, storage_driver, now, now),
            )
            row = db.execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
        return dict(row)

    def _ensure_quota(self, db: sqlite3.Connection, owner_id: str, new_bytes: int, max_owner_bytes: int, include_reserved: bool) -> None:
        used_bytes = db.execute(
            """SELECT COALESCE(SUM(media_objects.bytes), 0) FROM media_objects
               JOIN wallpapers ON wallpapers.id = media_objects.wallpaper_id
               JOIN folders ON folders.id = wallpapers.folder_id
               WHERE folders.owner_id = ? AND folders.is_official = 0""",
            (owner_id,),
        ).fetchone()[0]
        reserved_bytes = 0
        if include_reserved:
            reserved_bytes = db.execute(
                """SELECT COALESCE(SUM(uploads.expected_bytes), 0) FROM uploads
                   JOIN folders ON folders.id = uploads.folder_id
                   WHERE uploads.owner_id = ? AND folders.is_official = 0 AND uploads.state IN ('created', 'processing')""",
                (owner_id,),
            ).fetchone()[0]
        if int(used_bytes) + int(reserved_bytes) + new_bytes > max_owner_bytes:
            raise QuotaExceededError("已超过个人图库存储配额")

    def update_upload_state(self, upload_id: str, state: str, error_message: str | None = None) -> None:
        with self.database.transaction() as db:
            db.execute("UPDATE uploads SET state = ?, error_message = ?, updated_at = ? WHERE id = ?", (state, error_message, utcnow(), upload_id))

    def publish_user_upload(self, upload: dict[str, Any], original: MediaAsset, derivatives: list[MediaAsset], max_owner_bytes: int = 0) -> dict[str, Any]:
        """Atomically publish one original and all of its generated variants."""
        now = utcnow()
        with self.database.transaction() as db:
            current_upload = db.execute(
                "SELECT * FROM uploads WHERE id = ? AND owner_id = ? AND state IN ('created', 'processing')",
                (upload["id"], upload["owner_id"]),
            ).fetchone()
            folder = self._managed_folder(db, str(upload["folder_id"]), str(upload["owner_id"]))
            if not current_upload or not folder:
                raise PermissionError("upload or destination folder is no longer available")
            if max_owner_bytes and not folder["is_official"]:
                new_bytes = original.byte_count + sum(asset.byte_count for asset in derivatives)
                self._ensure_quota(db, str(upload["owner_id"]), new_bytes, max_owner_bytes, include_reserved=False)
            existing = db.execute("SELECT * FROM wallpapers WHERE folder_id = ? AND source_scope = 'user' AND status != 'deleted'", (upload["folder_id"],)).fetchone()
            if existing:
                wallpaper_id = existing["id"]
                existing_area = int(existing["width"] or 0) * int(existing["height"] or 0)
                width = original.width if original.width * original.height > existing_area else existing["width"]
                height = original.height if original.width * original.height > existing_area else existing["height"]
                db.execute("UPDATE wallpapers SET title = ?, status = 'ready', width = ?, height = ?, updated_at = ? WHERE id = ?", (folder["name"], width, height, now, wallpaper_id))
            else:
                wallpaper_id = new_id()
                db.execute("INSERT INTO wallpapers(id, folder_id, source_scope, title, status, width, height, created_at, updated_at) VALUES (?, ?, 'user', ?, 'ready', ?, ?, ?, ?)", (wallpaper_id, upload["folder_id"], folder["name"], original.width, original.height, now, now))
            driver = str(upload.get("storage_driver") or "local")
            original_media_id = new_id()
            db.execute(
                """INSERT INTO media_objects(id, wallpaper_id, object_key, original_name, mime_type, bytes, width, height, sha256, kind, source_media_id, storage_driver, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'original', NULL, ?, ?)""",
                (original_media_id, wallpaper_id, original.object_key, original.original_name, original.mime_type, original.byte_count, original.width, original.height, original.sha256, driver, now),
            )
            for asset in derivatives:
                db.execute(
                    """INSERT INTO media_objects(id, wallpaper_id, object_key, original_name, mime_type, bytes, width, height, sha256, kind, source_media_id, storage_driver, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (new_id(), wallpaper_id, asset.object_key, asset.original_name, asset.mime_type, asset.byte_count, asset.width, asset.height, asset.sha256, asset.kind, original_media_id, driver, now),
                )
            db.execute("UPDATE uploads SET state = 'ready', updated_at = ? WHERE id = ?", (now, upload["id"]))
            row = db.execute("SELECT * FROM wallpapers WHERE id = ?", (wallpaper_id,)).fetchone()
        return dict(row)

    # ------------------------------------------------- system folder policies

    def list_system_policies(self) -> dict[str, str]:
        with self.database.connection() as db:
            return {row["path"]: row["visibility"] for row in db.execute("SELECT path, visibility FROM system_folder_policies")}

    def set_system_policy(self, path: str, visibility: str | None) -> None:
        """Persist one mounted-folder policy; ``None`` restores the public default."""
        with self.database.transaction() as db:
            if visibility is None:
                db.execute("DELETE FROM system_folder_policies WHERE path = ?", (path,))
            else:
                db.execute(
                    """INSERT INTO system_folder_policies(path, visibility, updated_at) VALUES (?, ?, ?)
                       ON CONFLICT(path) DO UPDATE SET visibility = excluded.visibility, updated_at = excluded.updated_at""",
                    (path, visibility, utcnow()),
                )

    def enqueue(self, kind: str, payload: dict[str, Any]) -> str:
        job_id = new_id()
        now = utcnow()
        with self.database.transaction() as db:
            db.execute("INSERT INTO jobs(id, kind, payload_json, state, created_at, updated_at) VALUES (?, ?, ?, 'queued', ?, ?)", (job_id, kind, json.dumps(payload), now, now))
        return job_id
