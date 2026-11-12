from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
try:
    from PIL import Image
except ModuleNotFoundError:  # The production image always installs Pillow.
    Image = None  # type: ignore[assignment]


@unittest.skipIf(Image is None, "Pillow is not installed in this host interpreter")
class HttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        catalog = root / "catalog.json"
        catalog.write_text(json.dumps({"version": 2, "count": 2, "wallpapers": [
            {"id": "sys-open", "folder": "公开期/一", "thumbnail": "public/thumbs/open.webp", "variants": [{"source": "images/公开期/一/a.png"}]},
            {"id": "sys-staff", "folder": "内部期/一", "thumbnail": "public/thumbs/staff.webp", "variants": [{"source": "images/内部期/一/b.png"}]},
        ]}), encoding="utf-8")
        self.environment = patch.dict(os.environ, {
            "WALLPAPER_DATA_DIR": str(root / "data"),
            "WALLPAPER_UPLOADS_DIR": str(root / "uploads"),
            "WALLPAPER_SYSTEM_CATALOG_PATH": str(catalog),
            "WALLPAPER_PUBLIC_ORIGIN": "https://wallpaper.example.test",
            "WALLPAPER_AUTH_MODE": "local",
            "WALLPAPER_LOCAL_REGISTRATION": "true",
            "WALLPAPER_SESSION_SECRET": "test-secret-that-is-long-and-stable",
            "WALLPAPER_COOKIE_SECURE": "true",
            "WALLPAPER_ADMIN_LOCAL_USERS": "root",
        })
        self.environment.start()
        from app.main import create_app
        self.client_context = TestClient(create_app(), base_url="https://wallpaper.example.test")
        self.client = self.client_context.__enter__()
        self.origin = {"Origin": "https://wallpaper.example.test"}

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.environment.stop()
        self.temp.cleanup()

    def register(self, client: TestClient, username: str) -> dict[str, object]:
        response = client.post("/api/v1/auth/local/register", json={"username": username, "password": "123456"}, headers=self.origin)
        self.assertEqual(201, response.status_code, response.text)
        session = client.get("/api/v1/auth/me").json()
        self.assertTrue(session["authenticated"])
        return session

    def test_origin_auth_upload_variants_and_explicit_share(self) -> None:
        rejected = self.client.post(
            "/api/v1/auth/local/register",
            json={"username": "owner", "password": "123456"},
            headers={"Origin": "https://attacker.example"},
        )
        self.assertEqual(403, rejected.status_code)
        owner_session = self.register(self.client, "owner")
        csrf = str(owner_session["csrfToken"])
        mutation_headers = {**self.origin, "X-CSRF-Token": csrf}

        folder_response = self.client.post("/api/v1/folders", json={"name": "Portfolio"}, headers=mutation_headers)
        self.assertEqual(201, folder_response.status_code, folder_response.text)
        folder_id = folder_response.json()["id"]

        image_bytes = io.BytesIO()
        Image.new("RGB", (1200, 800), "#6688aa").save(image_bytes, "JPEG")
        image_bytes.seek(0)
        uploaded = self.client.post(
            f"/api/v1/folders/{folder_id}/uploads",
            files={"file": ("wall.jpg", image_bytes, "image/jpeg")},
            headers=mutation_headers,
        )
        self.assertEqual(201, uploaded.status_code, uploaded.text)

        items = self.client.get("/api/v1/wallpapers/user").json()["wallpapers"]
        self.assertEqual(1, len(items))
        self.assertEqual(1, len(items[0]["variants"]))
        self.assertTrue(items[0]["thumbnail"]["mediaUrl"].startswith("https://wallpaper.example.test/"))
        self.assertEqual(items[0]["primary"]["media_id"], items[0]["thumbnail"]["source_media_id"])

        viewer_context = TestClient(self.client.app, base_url="https://wallpaper.example.test")
        viewer = viewer_context.__enter__()
        try:
            self.register(viewer, "viewer")
            self.assertEqual([], viewer.get("/api/v1/wallpapers/user").json()["wallpapers"])
            shared = self.client.put(
                f"/api/v1/folders/{folder_id}/grants",
                json={"identifiers": ["viewer"]},
                headers=mutation_headers,
            )
            self.assertEqual(200, shared.status_code, shared.text)
            self.assertEqual(1, len(viewer.get("/api/v1/wallpapers/user").json()["wallpapers"]))
        finally:
            viewer_context.__exit__(None, None, None)

        self.assertEqual(403, self.client.post("/api/v1/auth/logout", headers=self.origin).status_code)
        self.assertEqual(204, self.client.post("/api/v1/auth/logout", headers=mutation_headers).status_code)

    def test_system_folder_policy_over_http(self) -> None:
        # Anonymous sessions see the whole catalogue while no policy exists.
        self.assertEqual({"sys-open", "sys-staff"}, {item["id"] for item in self.client.get("/api/v1/catalog").json()["wallpapers"]})
        self.assertEqual(401, self.client.get("/api/v1/system-folders").status_code)

        admin_session = self.register(self.client, "root")
        headers = {**self.origin, "X-CSRF-Token": str(admin_session["csrfToken"])}
        folders = self.client.get("/api/v1/system-folders").json()["folders"]
        self.assertEqual(
            sorted([{"path": "内部期", "wallpapers": 1, "visibility": "public"}, {"path": "公开期", "wallpapers": 1, "visibility": "public"}], key=lambda item: str(item["path"])),
            sorted(folders, key=lambda item: str(item["path"])),
        )

        updated = self.client.put("/api/v1/system-folders/内部期", json={"visibility": "admin"}, headers=headers)
        self.assertEqual(200, updated.status_code, updated.text)

        anonymous_context = TestClient(self.client.app, base_url="https://wallpaper.example.test")
        with anonymous_context as anonymous:
            listed = anonymous.get("/api/v1/catalog").json()
            self.assertEqual(["sys-open"], [item["id"] for item in listed["wallpapers"]])
            self.assertEqual(1, listed["count"])
            # nginx auth_request contract: hidden folders deny, unknown thumbs allow.
            self.assertEqual(401, anonymous.get("/api/v1/authz/media", headers={"X-Original-URI": "/images/%E5%86%85%E9%83%A8%E6%9C%9F/%E4%B8%80/b.png"}).status_code)
            self.assertEqual(401, anonymous.get("/api/v1/authz/media", headers={"X-Original-URI": "/public/thumbs/staff.webp"}).status_code)
            self.assertEqual(204, anonymous.get("/api/v1/authz/media", headers={"X-Original-URI": "/public/thumbs/open.webp"}).status_code)
            self.assertEqual(204, anonymous.get("/api/v1/authz/media", headers={"X-Original-URI": "/public/thumbs/rebuilt-unknown.webp"}).status_code)
        # The admin session still sees and fetches the hidden folder.
        self.assertEqual({"sys-open", "sys-staff"}, {item["id"] for item in self.client.get("/api/v1/catalog").json()["wallpapers"]})
        self.assertEqual(204, self.client.get("/api/v1/authz/media", headers={"X-Original-URI": "/images/%E5%86%85%E9%83%A8%E6%9C%9F/%E4%B8%80/b.png"}).status_code)

    def test_local_session_exposes_avatar_field(self) -> None:
        # A local account has no provider portrait; the field is present and null
        # so the frontend can rely on it without probing.
        session = self.register(self.client, "root")
        self.assertIn("avatar_url", session["user"])
        self.assertIsNone(session["user"]["avatar_url"])
        self.assertTrue(session["user"]["local"])
        self.assertFalse(session["inviteRequired"])

    def test_change_password_revokes_other_sessions(self) -> None:
        session = self.register(self.client, "alice")
        csrf = str(session["csrfToken"])
        headers = {**self.origin, "X-CSRF-Token": csrf}
        # A second device signs in as the same account.
        other_context = TestClient(self.client.app, base_url="https://wallpaper.example.test")
        with other_context as other:
            self.assertEqual(200, other.post("/api/v1/auth/local/login", json={"username": "alice", "password": "123456"}, headers=self.origin).status_code)
            self.assertTrue(other.get("/api/v1/auth/me").json()["authenticated"])
            # Wrong current password is rejected.
            self.assertEqual(401, self.client.post("/api/v1/auth/local/password", json={"current_password": "nope!!", "new_password": "brandnew1"}, headers=headers).status_code)
            # Correct change succeeds and keeps the current session working.
            self.assertEqual(204, self.client.post("/api/v1/auth/local/password", json={"current_password": "123456", "new_password": "brandnew1"}, headers=headers).status_code)
            self.assertTrue(self.client.get("/api/v1/auth/me").json()["authenticated"])
            # The other device's session is revoked.
            self.assertFalse(other.get("/api/v1/auth/me").json()["authenticated"])
        # The old password no longer works; the new one does.
        self.assertEqual(401, self.client.post("/api/v1/auth/local/login", json={"username": "alice", "password": "123456"}, headers=self.origin).status_code)
        fresh_context = TestClient(self.client.app, base_url="https://wallpaper.example.test")
        with fresh_context as fresh:
            self.assertEqual(200, fresh.post("/api/v1/auth/local/login", json={"username": "alice", "password": "brandnew1"}, headers=self.origin).status_code)

    def test_logout_all_keeps_current_session(self) -> None:
        session = self.register(self.client, "carol")
        headers = {**self.origin, "X-CSRF-Token": str(session["csrfToken"])}
        other_context = TestClient(self.client.app, base_url="https://wallpaper.example.test")
        with other_context as other:
            other.post("/api/v1/auth/local/login", json={"username": "carol", "password": "123456"}, headers=self.origin)
            self.assertEqual(204, self.client.post("/api/v1/auth/logout-all", headers=headers).status_code)
            self.assertTrue(self.client.get("/api/v1/auth/me").json()["authenticated"])
            self.assertFalse(other.get("/api/v1/auth/me").json()["authenticated"])


@unittest.skipIf(Image is None, "Pillow is not installed in this host interpreter")
class InviteRegistrationTests(unittest.TestCase):
    def test_registration_requires_valid_invite_code(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        catalog = root / "catalog.json"
        catalog.write_text(json.dumps({"version": 2, "count": 0, "wallpapers": []}), encoding="utf-8")
        environment = patch.dict(os.environ, {
            "WALLPAPER_DATA_DIR": str(root / "data"),
            "WALLPAPER_UPLOADS_DIR": str(root / "uploads"),
            "WALLPAPER_SYSTEM_CATALOG_PATH": str(catalog),
            "WALLPAPER_PUBLIC_ORIGIN": "https://invite.example.test",
            "WALLPAPER_AUTH_MODE": "local",
            "WALLPAPER_LOCAL_REGISTRATION": "true",
            "WALLPAPER_INVITE_CODES": "letmein, friends",
            "WALLPAPER_SESSION_SECRET": "another-long-stable-test-secret",
            "WALLPAPER_COOKIE_SECURE": "true",
        })
        environment.start()
        self.addCleanup(environment.stop)
        from app.main import create_app
        origin = {"Origin": "https://invite.example.test"}
        with TestClient(create_app(), base_url="https://invite.example.test") as client:
            self.assertTrue(client.get("/api/v1/auth/me").json()["inviteRequired"])
            self.assertEqual(403, client.post("/api/v1/auth/local/register", json={"username": "bob", "password": "123456"}, headers=origin).status_code)
            self.assertEqual(403, client.post("/api/v1/auth/local/register", json={"username": "bob", "password": "123456", "invite_code": "nope"}, headers=origin).status_code)
            self.assertEqual(201, client.post("/api/v1/auth/local/register", json={"username": "bob", "password": "123456", "invite_code": "friends"}, headers=origin).status_code)


@unittest.skipIf(Image is None, "Pillow is not installed in this host interpreter")
class UploadRateLimitTests(unittest.TestCase):
    def test_uploads_are_rate_limited_per_account(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        catalog = root / "catalog.json"
        catalog.write_text(json.dumps({"version": 2, "count": 0, "wallpapers": []}), encoding="utf-8")
        environment = patch.dict(os.environ, {
            "WALLPAPER_DATA_DIR": str(root / "data"),
            "WALLPAPER_UPLOADS_DIR": str(root / "uploads"),
            "WALLPAPER_SYSTEM_CATALOG_PATH": str(catalog),
            "WALLPAPER_PUBLIC_ORIGIN": "https://rl.example.test",
            "WALLPAPER_AUTH_MODE": "local",
            "WALLPAPER_LOCAL_REGISTRATION": "true",
            "WALLPAPER_UPLOAD_RATE_LIMIT_PER_MINUTE": "1",
            "WALLPAPER_SESSION_SECRET": "rate-limit-test-secret-value-long",
            "WALLPAPER_COOKIE_SECURE": "true",
        })
        environment.start()
        self.addCleanup(environment.stop)
        from app.main import create_app
        origin = {"Origin": "https://rl.example.test"}
        with TestClient(create_app(), base_url="https://rl.example.test") as client:
            client.post("/api/v1/auth/local/register", json={"username": "dana", "password": "123456"}, headers=origin)
            csrf = str(client.get("/api/v1/auth/me").json()["csrfToken"])
            headers = {**origin, "X-CSRF-Token": csrf}
            folder_id = client.post("/api/v1/folders", json={"name": "Album"}, headers=headers).json()["id"]

            def upload_once() -> int:
                buffer = io.BytesIO()
                Image.new("RGB", (600, 400), "#446688").save(buffer, "PNG")
                buffer.seek(0)
                return client.post(f"/api/v1/folders/{folder_id}/uploads", files={"file": ("w.png", buffer, "image/png")}, headers=headers).status_code

            self.assertEqual(201, upload_once())
            self.assertEqual(429, upload_once())


class AvatarSanitizerTests(unittest.TestCase):
    def test_http_and_data_image_urls_survive(self) -> None:
        from app.routes.auth import _safe_avatar_url

        self.assertEqual("https://idp.example/p.png", _safe_avatar_url("https://idp.example/p.png"))
        self.assertEqual("http://idp.example/p.png", _safe_avatar_url("http://idp.example/p.png"))
        # authentik's default initials avatar arrives as an inline image data URI.
        self.assertEqual("data:image/png;base64,AAAA", _safe_avatar_url("data:image/png;base64,AAAA"))
        self.assertEqual("data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=", _safe_avatar_url("data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="))
        self.assertIsNone(_safe_avatar_url("javascript:alert(1)"))
        self.assertIsNone(_safe_avatar_url("data:text/html,<script>alert(1)</script>"))
        self.assertIsNone(_safe_avatar_url(None))
        self.assertIsNone(_safe_avatar_url("https://" + "a" * 3000))
        # An oversized data URI is dropped rather than bloating the session row.
        self.assertIsNone(_safe_avatar_url("data:image/png;base64," + "A" * 70000))


class HomepageWallpaperApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        catalog = root / "catalog.json"
        catalog.write_text(json.dumps({"version": 2, "count": 1, "wallpapers": [
            {
                "id": "sys-open",
                "folder": "公开期/一",
                "homepage": "public/homepage/sys-open-night.webp",
                "variants": [{"source": "images/公开期/一/a.png"}],
            },
        ]}), encoding="utf-8")
        self.environment = patch.dict(os.environ, {
            "WALLPAPER_DATA_DIR": str(root / "data"),
            "WALLPAPER_SYSTEM_CATALOG_PATH": str(catalog),
            "WALLPAPER_PUBLIC_ORIGIN": "https://wallpaper.example.test",
            "WALLPAPER_AUTH_MODE": "local",
            "WALLPAPER_SESSION_SECRET": "homepage-test-secret-that-is-long-and-stable",
            "WALLPAPER_ADMIN_LOCAL_USERS": "root",
            "WALLPAPER_HOMEPAGE_SYNC_URL": "https://sync.internal.example",
            "WALLPAPER_HOMEPAGE_SYNC_SECRET": "".join(f"{value:02x}" for value in range(32)),
        })
        self.environment.start()
        from app.main import create_app
        self.context = TestClient(create_app(), base_url="https://wallpaper.example.test")
        self.client = self.context.__enter__()
        self.origin = {"Origin": "https://wallpaper.example.test"}

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)
        self.environment.stop()
        self.temp.cleanup()

    def test_only_admin_can_sync_a_public_catalog_variant(self) -> None:
        self.assertEqual(201, self.client.post("/api/v1/auth/local/register", json={"username": "root", "password": "123456"}, headers=self.origin).status_code)
        session = self.client.get("/api/v1/auth/me").json()
        headers = {**self.origin, "X-CSRF-Token": session["csrfToken"]}
        fake_response = type("Response", (), {"status_code": 200, "json": lambda self: {"revision": 7}})()
        with patch("app.routes.homepage.httpx.put", return_value=fake_response) as request:
            response = self.client.put(
                "/api/v1/homepage-wallpaper/main",
                json={"wallpaper_id": "sys-open", "variant_source": "images/公开期/一/a.png"},
                headers=headers,
            )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(7, response.json()["state"]["revision"])
        sent = json.loads(request.call_args.kwargs["content"])
        self.assertEqual("https://wallpaper.example.test/public/homepage/sys-open-night.webp", sent["imageUrl"])
        self.assertNotIn("material", sent)
        self.assertIn("x-homepage-wallpaper-signature", request.call_args.kwargs["headers"])

        self.assertEqual(
            422,
            self.client.put(
                "/api/v1/homepage-wallpaper/main",
                json={"wallpaper_id": "sys-open", "variant_source": "images/other.png"},
                headers=headers,
            ).status_code,
        )

    def test_card_appearance_is_validated_and_signed_with_csrf(self) -> None:
        self.client.post('/api/v1/auth/local/register', json={'username': 'root', 'password': '123456'}, headers=self.origin)
        session = self.client.get('/api/v1/auth/me').json()
        headers = {**self.origin, 'X-CSRF-Token': session['csrfToken']}
        payload = {'preset': 'clear', 'dim_opacity': 0, 'blur_px': 0, 'saturation': 1,
                   'card_blur_px': 10, 'card_opacity': .2, 'card_saturation': 1.6, 'card_refraction': 85}
        fake = type('Response', (), {'status_code': 200, 'json': lambda self: {'revision': 8}})()
        with patch('app.routes.homepage.httpx.put', return_value=fake) as request:
            response = self.client.put('/api/v1/homepage-wallpaper/main/appearance', json=payload, headers=headers)
            self.assertEqual(200, response.status_code, response.text)
            body = request.call_args.kwargs['content']
            sent = json.loads(body)['appearance']
            self.assertEqual((10, .2, 1.6, 85), (sent['cardBlurPx'], sent['cardOpacity'], sent['cardSaturation'], sent['cardRefraction']))
            from app.routes.homepage import _signature
            signed_headers = request.call_args.kwargs['headers']
            self.assertEqual(_signature(os.environ['WALLPAPER_HOMEPAGE_SYNC_SECRET'], 'PUT', '/internal/wallpaper/appearance', body,
                                        signed_headers['x-homepage-wallpaper-timestamp']), signed_headers['x-homepage-wallpaper-signature'])
            self.assertEqual(403, self.client.put('/api/v1/homepage-wallpaper/main/appearance', json=payload, headers=self.origin).status_code)
            for field, invalid in [('card_blur_px', 21), ('card_opacity', -.1), ('card_saturation', 2.1), ('card_refraction', 101)]:
                self.assertEqual(422, self.client.put('/api/v1/homepage-wallpaper/main/appearance', json={**payload, field: invalid}, headers=headers).status_code)
            legacy = {key: value for key, value in payload.items() if not key.startswith('card_')}
            self.assertEqual(200, self.client.put('/api/v1/homepage-wallpaper/main/appearance', json=legacy, headers=headers).status_code)
            self.assertNotIn('cardBlurPx', json.loads(request.call_args.kwargs['content'])['appearance'])

    def test_named_preset_requires_admin_csrf_and_signs_the_image_and_complete_draft(self) -> None:
        self.client.post('/api/v1/auth/local/register', json={'username': 'root', 'password': '123456'}, headers=self.origin)
        session = self.client.get('/api/v1/auth/me').json()
        headers = {**self.origin, 'X-CSRF-Token': session['csrfToken']}
        payload = {'name': '夜航', 'expected_image_url': 'https://wallpaper.example.test/public/homepage/one.webp',
                   'preset': 'clear', 'dim_opacity': .21, 'blur_px': 0, 'saturation': .86,
                   'card_blur_px': 1, 'card_opacity': .02, 'card_saturation': 1.59, 'card_refraction': 19}
        route = '/api/v1/homepage-wallpaper/main/presets'
        fake = type('Response', (), {'status_code': 200, 'json': lambda self: {'preset': {'id': 'test', 'name': '夜航'}}})()
        with patch('app.routes.homepage.httpx.put', return_value=fake) as peer:
            response = self.client.post(route, json=payload, headers=headers)
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual('夜航', response.json()['preset']['name'])
            body = peer.call_args.kwargs['content']; sent = json.loads(body)
            self.assertEqual(payload['expected_image_url'], sent['expectedImageUrl'])
            self.assertEqual(19, sent['appearance']['cardRefraction'])
            self.assertEqual(1, peer.call_count, 'saving must not separately apply appearance or image')
            from app.routes.homepage import _signature
            h = peer.call_args.kwargs['headers']
            self.assertEqual(_signature(os.environ['WALLPAPER_HOMEPAGE_SYNC_SECRET'], 'PUT', '/internal/wallpaper/presets', body, h['x-homepage-wallpaper-timestamp']), h['x-homepage-wallpaper-signature'])
            self.assertEqual(403, self.client.post(route, json=payload, headers=self.origin).status_code)
            self.assertEqual(403, self.client.post(route, json=payload, headers={**headers, 'Origin': 'https://attacker.test'}).status_code)
            self.assertEqual(422, self.client.post(route, json={**payload, 'card_blur_px': 21}, headers=headers).status_code)
        conflict = type('Response', (), {'status_code': 409, 'json': lambda self: {'error': 'preset-name-exists'}})()
        with patch('app.routes.homepage.httpx.put', return_value=conflict):
            response = self.client.post(route, json=payload, headers=headers)
            self.assertEqual(409, response.status_code)
            self.assertIn('名称已存在', response.json()['detail'])
        self.client.post('/api/v1/auth/logout', headers=headers)
        self.client.post('/api/v1/auth/local/register', json={'username': 'ordinary', 'password': '123456'}, headers=self.origin)
        other = self.client.get('/api/v1/auth/me').json()
        self.assertEqual(403, self.client.post(route, json=payload, headers={**self.origin, 'X-CSRF-Token': other['csrfToken']}).status_code)


if __name__ == "__main__":
    unittest.main()
