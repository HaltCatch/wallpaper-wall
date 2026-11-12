"""Runtime configuration.  No framework-specific settings magic is used here.

Keeping parsing in one module makes Docker environment configuration explicit
and lets the domain/application layers remain independent from FastAPI.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


def _csv(name: str) -> tuple[str, ...]:
    return tuple(value.strip() for value in os.getenv(name, "").split(",") if value.strip())


def _session_secret(data_dir: Path) -> str:
    """Return an explicit secret or persist a generated lightweight default."""
    configured = os.getenv("WALLPAPER_SESSION_SECRET", "").strip()
    if configured:
        return configured
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_path = data_dir / "session-secret"
    try:
        existing = secret_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    generated = secrets.token_urlsafe(48)
    try:
        descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return secret_path.read_text(encoding="utf-8").strip()
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(generated)
    return generated


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    uploads_dir: Path
    system_images_dir: Path
    system_catalog_path: Path
    public_origin: str
    auth_mode: str
    session_secret: str
    local_registration_enabled: bool
    invite_codes: tuple[str, ...]
    auth_rate_limit_attempts: int
    auth_rate_limit_window_seconds: int
    upload_rate_limit_per_minute: int
    admin_local_users: tuple[str, ...]
    oidc_issuer: str
    oidc_client_id: str
    oidc_client_secret: str
    oidc_redirect_uri: str
    admin_subjects: tuple[str, ...]
    storage_driver: str
    s3_endpoint: str
    s3_bucket: str
    s3_region: str
    s3_access_key: str
    s3_secret_key: str
    s3_force_path_style: bool
    upload_max_bytes: int
    user_storage_quota_bytes: int
    media_url_ttl_seconds: int
    cookie_secure: bool
    public_image_base_url: str
    homepage_sync_url: str
    homepage_sync_secret: str

    @property
    def database_path(self) -> Path:
        return self.data_dir / "wallpaper-wall.sqlite3"

    @property
    def local_auth_enabled(self) -> bool:
        return self.auth_mode in {"local", "hybrid"}

    @property
    def invite_required(self) -> bool:
        """Self-service registration additionally requires a valid invite code."""
        return bool(self.invite_codes)

    @property
    def oidc_enabled(self) -> bool:
        return self.auth_mode in {"oidc", "hybrid"}

    @property
    def oidc_redirect_target(self) -> str:
        """The registered callback: explicit value first, else derived from the
        public origin so one variable configures both CSRF and OIDC."""
        return self.oidc_redirect_uri or f"{self.public_origin}/api/v1/auth/callback"

    @classmethod
    def from_environment(cls) -> "Settings":
        data_dir = Path(os.getenv("WALLPAPER_DATA_DIR", "/app/data"))
        uploads_dir = Path(os.getenv("WALLPAPER_UPLOADS_DIR", str(data_dir / "uploads")))
        auth_mode = os.getenv("WALLPAPER_AUTH_MODE", "local").strip().lower()
        if auth_mode not in {"disabled", "local", "oidc", "hybrid"}:
            raise RuntimeError("WALLPAPER_AUTH_MODE must be disabled, local, oidc, or hybrid")
        storage_driver = os.getenv("WALLPAPER_STORAGE_DRIVER", "local").strip().lower()
        if storage_driver not in {"local", "s3"}:
            raise RuntimeError("WALLPAPER_STORAGE_DRIVER must be local or s3")
        return cls(
            data_dir=data_dir,
            uploads_dir=uploads_dir,
            system_images_dir=Path(os.getenv("WALLPAPER_SYSTEM_IMAGES_DIR", "/app/images")),
            system_catalog_path=Path(os.getenv("WALLPAPER_SYSTEM_CATALOG_PATH", "/app/runtime/catalog.json")),
            public_origin=os.getenv("WALLPAPER_PUBLIC_ORIGIN", "").strip().rstrip("/"),
            auth_mode=auth_mode,
            # A configured secret takes precedence.  Otherwise a generated
            # value is persisted on the existing data volume so sessions and
            # OIDC state survive ordinary container restarts.
            session_secret=_session_secret(data_dir),
            local_registration_enabled=os.getenv("WALLPAPER_LOCAL_REGISTRATION", "true").lower() in {"1", "true", "yes"},
            invite_codes=_csv("WALLPAPER_INVITE_CODES"),
            auth_rate_limit_attempts=int(os.getenv("WALLPAPER_AUTH_RATE_LIMIT_ATTEMPTS", "10")),
            auth_rate_limit_window_seconds=int(os.getenv("WALLPAPER_AUTH_RATE_LIMIT_WINDOW_SECONDS", "60")),
            upload_rate_limit_per_minute=int(os.getenv("WALLPAPER_UPLOAD_RATE_LIMIT_PER_MINUTE", "60")),
            admin_local_users=tuple(value.casefold() for value in _csv("WALLPAPER_ADMIN_LOCAL_USERS")),
            oidc_issuer=os.getenv("WALLPAPER_OIDC_ISSUER", "").rstrip("/"),
            oidc_client_id=os.getenv("WALLPAPER_OIDC_CLIENT_ID", ""),
            oidc_client_secret=os.getenv("WALLPAPER_OIDC_CLIENT_SECRET", ""),
            oidc_redirect_uri=os.getenv("WALLPAPER_OIDC_REDIRECT_URI", ""),
            admin_subjects=_csv("WALLPAPER_ADMIN_SUBJECTS"),
            storage_driver=storage_driver,
            s3_endpoint=os.getenv("WALLPAPER_S3_ENDPOINT", ""),
            s3_bucket=os.getenv("WALLPAPER_S3_BUCKET", ""),
            s3_region=os.getenv("WALLPAPER_S3_REGION", "us-east-1"),
            s3_access_key=os.getenv("WALLPAPER_S3_ACCESS_KEY", ""),
            s3_secret_key=os.getenv("WALLPAPER_S3_SECRET_KEY", ""),
            s3_force_path_style=os.getenv("WALLPAPER_S3_FORCE_PATH_STYLE", "true").lower() in {"1", "true", "yes"},
            upload_max_bytes=int(os.getenv("WALLPAPER_UPLOAD_MAX_BYTES", str(100 * 1024 * 1024))),
            user_storage_quota_bytes=int(os.getenv("WALLPAPER_USER_STORAGE_QUOTA_BYTES", str(2 * 1024 * 1024 * 1024))),
            media_url_ttl_seconds=int(os.getenv("WALLPAPER_MEDIA_URL_TTL_SECONDS", "300")),
            cookie_secure=os.getenv("WALLPAPER_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"},
            public_image_base_url=os.getenv("WALLPAPER_PUBLIC_IMAGE_BASE_URL", "").strip().rstrip("/"),
            homepage_sync_url=os.getenv("WALLPAPER_HOMEPAGE_SYNC_URL", "").strip().rstrip("/"),
            homepage_sync_secret=os.getenv("WALLPAPER_HOMEPAGE_SYNC_SECRET", "").strip(),
        )

    def validate(self) -> None:
        if self.auth_rate_limit_attempts < 1 or self.auth_rate_limit_window_seconds < 1:
            raise RuntimeError("authentication rate-limit values must be positive")
        if self.upload_rate_limit_per_minute < 0:
            raise RuntimeError("upload rate limit must be zero (disabled) or positive")
        if self.upload_max_bytes < 1 or self.user_storage_quota_bytes < 0:
            raise RuntimeError("upload limit must be positive and user quota must be zero or positive")
        if self.public_origin:
            parsed_origin = urlsplit(self.public_origin)
            if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.netloc or parsed_origin.path or parsed_origin.query or parsed_origin.fragment:
                raise RuntimeError("WALLPAPER_PUBLIC_ORIGIN must be an http(s) origin without a path, query, or fragment")
        for name, value in {
            "WALLPAPER_PUBLIC_IMAGE_BASE_URL": self.public_image_base_url,
            "WALLPAPER_HOMEPAGE_SYNC_URL": self.homepage_sync_url,
        }.items():
            if value:
                parsed = urlsplit(value)
                if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
                    raise RuntimeError(f"{name} must be an http(s) URL without a query or fragment")
        if bool(self.homepage_sync_url) != bool(self.homepage_sync_secret):
            raise RuntimeError("WALLPAPER_HOMEPAGE_SYNC_URL and WALLPAPER_HOMEPAGE_SYNC_SECRET must be configured together")
        if self.homepage_sync_secret and len(self.homepage_sync_secret) < 32:
            raise RuntimeError("WALLPAPER_HOMEPAGE_SYNC_SECRET must contain at least 32 characters")
        if self.oidc_enabled:
            missing = [
                name for name, value in {
                    "WALLPAPER_SESSION_SECRET": self.session_secret,
                    "WALLPAPER_OIDC_ISSUER": self.oidc_issuer,
                    "WALLPAPER_OIDC_CLIENT_ID": self.oidc_client_id,
                    "WALLPAPER_OIDC_REDIRECT_URI or WALLPAPER_PUBLIC_ORIGIN": self.oidc_redirect_target if (self.oidc_redirect_uri or self.public_origin) else "",
                }.items() if not value
            ]
            if missing:
                raise RuntimeError(f"OIDC is enabled but missing: {', '.join(missing)}")
        if self.storage_driver == "s3":
            missing = [name for name, value in {
                "WALLPAPER_S3_BUCKET": self.s3_bucket,
                "WALLPAPER_S3_ACCESS_KEY": self.s3_access_key,
                "WALLPAPER_S3_SECRET_KEY": self.s3_secret_key,
            }.items() if not value]
            if missing:
                raise RuntimeError(f"S3 storage is enabled but missing: {', '.join(missing)}")
