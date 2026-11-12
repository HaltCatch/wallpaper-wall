from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.catalog import SystemCatalogRegistry, SystemCatalogService
from app.database import Database
from app.favorite_service import FavoriteService
from app.filenames import content_disposition, safe_filename
from app.repository import MediaAsset, Repository
from app.storage import LocalStorageBackend, StorageRouter


class LibraryPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        self.repository = Repository(Database(root / "test.sqlite3", migrations))
        self.repository.database.initialize()
        self.owner = self.repository.create_local_user("owner", "hash", ())
        self.viewer = self.repository.create_local_user("viewer", "hash", ())
        self.admin = self.repository.create_local_user("admin", "hash", ("admin",))
        self.catalog_path = root / "catalog.json"
        self.catalog_path.write_text(json.dumps({"wallpapers": [{"id": "system-one", "folder": "第一期"}]}), encoding="utf-8")
        self.system_catalog = SystemCatalogService(SystemCatalogRegistry(self.catalog_path), self.repository)
        self.favorites = FavoriteService(self.repository, self.system_catalog)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def publish(self, folder_id: str, name: str = "wall.jpg") -> str:
        upload = self.repository.create_upload(folder_id, self.owner["id"], name, 100)
        original = MediaAsset(upload["object_key"], name, "image/jpeg", 100, 1920, 1080, "a" * 64, "original")
        thumbnail = MediaAsset(f"{upload['object_key']}.thumb", "thumbnail.webp", "image/webp", 50, 1280, 720, "b" * 64, "thumbnail")
        small = MediaAsset(f"{upload['object_key']}.small", "thumbnail_small.webp", "image/webp", 25, 640, 360, "c" * 64, "thumbnail_small")
        return self.repository.publish_user_upload(upload, original, [thumbnail, small])["id"]

    def test_private_library_is_not_visible_to_admin_and_grants_are_explicit(self) -> None:
        folder = self.repository.create_folder(self.owner["id"], "Private", None)
        wallpaper_id = self.publish(folder["id"])

        self.assertNotIn(wallpaper_id, self.repository.accessible_user_wallpaper_ids(None))
        self.assertNotIn(wallpaper_id, self.repository.accessible_user_wallpaper_ids(self.admin))
        self.assertNotIn(wallpaper_id, self.repository.accessible_user_wallpaper_ids(self.viewer))

        self.repository.replace_grants_by_identifiers(folder["id"], self.owner["id"], ["viewer"])
        self.assertIn(wallpaper_id, self.repository.accessible_user_wallpaper_ids(self.viewer))
        self.assertNotIn(wallpaper_id, self.repository.accessible_user_wallpaper_ids(self.admin))

    def test_public_and_authenticated_visibility_are_distinct(self) -> None:
        public = self.repository.create_folder(self.owner["id"], "Public", None)
        authenticated = self.repository.create_folder(self.owner["id"], "Members", None)
        public_id = self.publish(public["id"], "public.jpg")
        authenticated_id = self.publish(authenticated["id"], "members.jpg")
        self.repository.update_folder(public["id"], self.owner["id"], None, "public")
        self.repository.update_folder(authenticated["id"], self.owner["id"], None, "authenticated")

        self.assertIn(public_id, self.repository.accessible_user_wallpaper_ids(None))
        self.assertNotIn(authenticated_id, self.repository.accessible_user_wallpaper_ids(None))
        self.assertIn(authenticated_id, self.repository.accessible_user_wallpaper_ids(self.viewer))

    def test_media_lineage_variants_and_safe_folder_deletion(self) -> None:
        folder = self.repository.create_folder(self.owner["id"], "Variants", None)
        self.publish(folder["id"], "large.jpg")
        self.publish(folder["id"], "second.jpg")
        items = self.repository.list_accessible_user_wallpapers(self.owner)
        item = next(value for value in items if value["folder_id"] == folder["id"])

        self.assertEqual(2, len(item["variants"]))
        self.assertEqual(item["primary"]["media_id"], item["thumbnail"]["source_media_id"])
        with self.assertRaisesRegex(ValueError, "请先清空"):
            self.repository.delete_folder(folder["id"], self.owner["id"])
        self.assertEqual(6, len(self.repository.delete_folder_media(folder["id"], self.owner["id"])))
        self.assertTrue(self.repository.delete_folder(folder["id"], self.owner["id"]))

    def test_favorites_filter_unknown_and_inaccessible_ids(self) -> None:
        folder = self.repository.create_folder(self.owner["id"], "Favourite", None)
        private_id = self.publish(folder["id"])
        merged = self.favorites.merge(self.viewer, ["system-one", private_id, "unknown"])
        self.assertEqual(["system-one"], merged)
        with self.assertRaises(LookupError):
            self.favorites.add(self.viewer, private_id)

    def test_system_folder_policy_filters_catalog_and_static_assets(self) -> None:
        self.catalog_path.write_text(json.dumps({"version": 2, "wallpapers": [
            {"id": "open-1", "folder": "公开期/第一辑", "thumbnail": "public/thumbs/open.webp", "homepage": "public/homepage/open.webp", "variants": [{"source": "images/公开期/第一辑/a.png"}]},
            {"id": "staff-1", "folder": "内部素材", "thumbnail": "public/thumbs/staff.webp", "homepage": "public/homepage/staff.webp", "variants": [{"source": "images/内部素材/b.png"}]},
        ]}), encoding="utf-8")

        # Default: everything public, matching historical behaviour.
        self.assertEqual({"open-1", "staff-1"}, self.system_catalog.accessible_ids(None))
        self.assertTrue(self.system_catalog.authorize_asset("/images/%E5%86%85%E9%83%A8%E7%B4%A0%E6%9D%90/b.png", None))

        self.system_catalog.set_folder_visibility("内部素材", "admin")
        self.assertEqual({"open-1"}, self.system_catalog.accessible_ids(None))
        self.assertEqual({"open-1"}, self.system_catalog.accessible_ids(self.viewer))
        self.assertEqual({"open-1", "staff-1"}, self.system_catalog.accessible_ids(self.admin))
        listed = self.system_catalog.visible_wallpapers(self.viewer)
        self.assertEqual(1, listed["count"])

        # Static enforcement mirrors the listing: original path, thumbnail
        # lineage and traversal attempts.
        self.assertFalse(self.system_catalog.authorize_asset("/images/%E5%86%85%E9%83%A8%E7%B4%A0%E6%9D%90/b.png", self.viewer))
        self.assertTrue(self.system_catalog.authorize_asset("/images/内部素材/b.png", self.admin))
        self.assertFalse(self.system_catalog.authorize_asset("/public/thumbs/staff.webp", None))
        self.assertTrue(self.system_catalog.authorize_asset("/public/thumbs/open.webp", None))
        self.assertFalse(self.system_catalog.authorize_asset("/public/homepage/staff.webp", None))
        self.assertTrue(self.system_catalog.authorize_asset("/public/homepage/open.webp", None))
        self.assertTrue(self.system_catalog.authorize_asset("/public/thumbs/unknown-hash.webp", None))
        self.assertFalse(self.system_catalog.authorize_asset("/images/公开期/../内部素材/b.png", None))

        # Favourites respect the same policy.
        self.assertEqual([], self.favorites.merge(self.viewer, ["staff-1"]))
        self.assertEqual(["staff-1"], self.favorites.merge(self.admin, ["staff-1"]))

        # Restoring public removes the stored row entirely.
        self.system_catalog.set_folder_visibility("内部素材", "public")
        self.assertEqual({}, self.repository.list_system_policies())
        with self.assertRaises(LookupError):
            self.system_catalog.set_folder_visibility("不存在", "admin")

    def test_download_filenames_are_header_safe_and_keep_unicode(self) -> None:
        cleaned = safe_filename('../目录/壁纸\r\n".png')
        self.assertNotIn("\r", cleaned)
        self.assertNotIn("\n", cleaned)
        header = content_disposition(cleaned)
        self.assertTrue(header.isascii())
        self.assertIn("filename*=UTF-8''", header)

    def test_subfolders_inherit_parent_acl_until_detached(self) -> None:
        parent = self.repository.create_folder(self.owner["id"], "Parent", None)
        child = self.repository.create_folder(self.owner["id"], "Child", parent["id"])
        self.assertEqual(1, child["inherit_acl"])
        child_id = self.publish(child["id"])

        # Child follows the parent's visibility while inheriting.
        self.assertNotIn(child_id, self.repository.accessible_user_wallpaper_ids(None))
        self.repository.update_folder(parent["id"], self.owner["id"], None, "public")
        self.assertIn(child_id, self.repository.accessible_user_wallpaper_ids(None))

        # Inherited grants come from the parent too.
        self.repository.update_folder(parent["id"], self.owner["id"], None, "private")
        self.repository.replace_grants_by_identifiers(parent["id"], self.owner["id"], ["viewer"])
        self.assertIn(child_id, self.repository.accessible_user_wallpaper_ids(self.viewer))

        # Detaching restores explicit, folder-local ACLs.
        self.repository.update_folder(child["id"], self.owner["id"], None, "private", inherit_acl=False)
        self.assertNotIn(child_id, self.repository.accessible_user_wallpaper_ids(self.viewer))
        with self.assertRaisesRegex(ValueError, "显式权限"):
            self.repository.update_folder(parent["id"], self.owner["id"], None, None, inherit_acl=True)

    def test_official_library_is_public_and_admin_managed(self) -> None:
        with self.assertRaises(PermissionError):
            self.repository.create_folder(self.owner["id"], "Official", None, official=True, is_admin=False)
        official = self.repository.create_folder(self.admin["id"], "Official", None, official=True, is_admin=True)
        self.assertEqual("public", official["visibility"])
        self.assertEqual(1, official["is_official"])

        upload = self.repository.create_upload(official["id"], self.admin["id"], "wall.jpg", 100)
        original = MediaAsset(upload["object_key"], "wall.jpg", "image/jpeg", 100, 1920, 1080, "d" * 64, "original")
        wallpaper_id = self.repository.publish_user_upload(upload, original, [])["id"]
        self.assertIn(wallpaper_id, self.repository.accessible_user_wallpaper_ids(None))
        item = next(value for value in self.repository.list_accessible_user_wallpapers(None) if value["id"] == wallpaper_id)
        self.assertTrue(item["official"])

        # Another administrator manages the folder; regular users cannot.
        second_admin = self.repository.create_local_user("root", "hash", ("root",))
        renamed = self.repository.update_folder(official["id"], second_admin["id"], "Curated", None)
        self.assertEqual("Curated", renamed["name"])
        self.assertIsNone(self.repository.update_folder(official["id"], self.viewer["id"], "Hijack", None))
        with self.assertRaises(PermissionError):
            self.repository.create_upload(official["id"], self.viewer["id"], "x.jpg", 10)

        # Official folders never consume the admin's personal quota.
        self.repository.create_upload(official["id"], self.admin["id"], "big.jpg", 10_000, max_owner_bytes=100)

    def test_storage_driver_travels_with_each_object_across_switches(self) -> None:
        folder = self.repository.create_folder(self.owner["id"], "Mixed", None)
        wallpaper_id = self.publish(folder["id"])

        item = next(value for value in self.repository.list_accessible_user_wallpapers(self.owner) if value["id"] == wallpaper_id)
        media = self.repository.media_by_id(item["primary"]["media_id"])
        self.assertEqual("local", media["storage_driver"])

        # Deletion reports the driver of every object so a router can address
        # the correct backend even after the active driver changed.
        objects = self.repository.delete_folder_media(folder["id"], self.owner["id"])
        self.assertTrue(objects)
        self.assertTrue(all(driver == "local" for _, driver in objects))

        # The router keeps serving 'local' objects after switching to S3 and
        # fails loudly for drivers that lost their configuration.
        local_backend = LocalStorageBackend(Path(self.temp.name) / "uploads")
        router = StorageRouter("s3", {"local": local_backend})
        self.assertIs(local_backend, router.for_driver("local"))
        with self.assertRaisesRegex(LookupError, "s3"):
            router.for_driver("s3")

        # Legacy rows (empty driver, pre-0006) are stamped with the driver
        # configured at startup.
        legacy = self.repository.create_upload(
            self.repository.create_folder(self.owner["id"], "Legacy", None)["id"],
            self.owner["id"], "old.jpg", 10, storage_driver="",
        )
        self.repository.backfill_storage_driver("s3")
        with self.repository.database.connection() as db:
            row = db.execute("SELECT storage_driver FROM uploads WHERE id = ?", (legacy["id"],)).fetchone()
        self.assertEqual("s3", row["storage_driver"])

    def test_user_storage_quota_reserves_pending_uploads(self) -> None:
        folder = self.repository.create_folder(self.owner["id"], "Quota", None)
        self.repository.create_upload(folder["id"], self.owner["id"], "first.jpg", 60, max_owner_bytes=100)
        with self.assertRaisesRegex(ValueError, "存储配额"):
            self.repository.create_upload(folder["id"], self.owner["id"], "second.jpg", 50, max_owner_bytes=100)


if __name__ == "__main__":
    unittest.main()
