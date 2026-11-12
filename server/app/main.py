"""Composition root: builds settings, services and the FastAPI application.

All request handling lives in ``routes/``; all policy lives in the repository
and services.  This module only wires them together.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .catalog import SystemCatalogRegistry, SystemCatalogService
from .config import Settings
from .database import Database
from .deps import Services
from .favorite_service import FavoriteService
from .library_service import UserLibraryService
from .rate_limit import SlidingWindowRateLimiter
from .repository import Repository
from .routes import auth, catalog, favorites, folders, homepage, media
from .storage import create_storage
from .uploads import UploadService


def _build_oauth(settings: Settings) -> OAuth | None:
    if not settings.oidc_enabled:
        return None
    oauth = OAuth()
    client_kwargs: dict[str, str] = {
        "scope": "openid profile email",
        # Authorization code + PKCE (S256) even for a confidential client;
        # authlib also validates state and the ID token nonce.
        "code_challenge_method": "S256",
    }
    if not settings.oidc_client_secret:
        # A public client (no secret) must not fall back to client_secret_basic
        # with an empty secret; PKCE is the proof of possession instead.
        client_kwargs["token_endpoint_auth_method"] = "none"
    oauth.register(
        name="oidc",
        server_metadata_url=f"{settings.oidc_issuer}/.well-known/openid-configuration",
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret or None,
        client_kwargs=client_kwargs,
    )
    return oauth


def build_services(settings: Settings) -> Services:
    server_root = Path(__file__).resolve().parents[1]
    repository = Repository(Database(settings.database_path, server_root / "migrations"))
    storage = create_storage(settings)
    system_catalog = SystemCatalogService(SystemCatalogRegistry(settings.system_catalog_path), repository)
    return Services(
        settings=settings,
        repository=repository,
        storage=storage,
        system_catalog=system_catalog,
        favorite_service=FavoriteService(repository, system_catalog),
        library_service=UserLibraryService(repository, storage),
        upload_service=UploadService(settings, repository, storage),
        auth_limiter=SlidingWindowRateLimiter(),
        upload_limiter=SlidingWindowRateLimiter(),
        oauth=_build_oauth(settings),
    )


def create_app() -> FastAPI:
    settings = Settings.from_environment()
    settings.validate()
    services = build_services(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        services.repository.database.initialize()
        services.repository.backfill_storage_driver(settings.storage_driver)
        services.repository.prune_expired_sessions()
        yield

    app = FastAPI(title="Wallpaper Wall API", version="1.0.0", lifespan=lifespan)
    # API and UI are same-origin behind nginx. Keep CORS closed by default.
    app.add_middleware(CORSMiddleware, allow_origins=[], allow_methods=[], allow_headers=[])
    # The Starlette session only carries transient OIDC state/nonce/PKCE data;
    # application sessions are database-backed cookies.
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=settings.cookie_secure, same_site="lax")
    app.state.services = services

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(catalog.router)
    app.include_router(favorites.router)
    app.include_router(folders.router)
    app.include_router(homepage.router)
    app.include_router(media.router)
    return app


app = create_app()
