# Wallpaper Wall

[中文](README.md) · [English](README.en.md)

Turn a collection of images into a wallpaper library you can browse, favorite and sync. Wallpaper Wall connects a self-hosted shared catalog, personal uploads and desktop/mobile helpers, serving both as a gallery wall and a daily wallpaper picker.

## Try it online

[GitHub Pages](https://haltcatch.github.io/wallpaper-wall/) · Synthetic gallery with browsing, previews and favorites.

## Features

- Smooth browsing: virtualized masonry, orientation filters, folders, search and multi-size previews.
- Favorites and personal libraries: favorites management, upload quotas and separate personal storage.
- Flexible authentication: local accounts, OIDC or hybrid mode, with registration, invitations and administrator identities.
- Storage options: local files or S3-compatible object storage, with expiring media URLs.
- Desktop and mobile integration: wallpaper helper source and protocol entry points, with configurable download URLs.
- Background integration: sync selected wallpapers to Homepage and adjust background/card appearance presets.

## Quick start

Docker Compose is recommended. Frontend development uses Node.js 26 and the pnpm version pinned in `web/package.json`; the backend uses Python/FastAPI.

```sh
cp .env.example .env
# Configure image directory, origin and authentication in .env.
docker compose -p wallpaper-wall up -d --build
```

## Configuration

| Setting | Purpose |
| --- | --- |
| `WALLPAPER_IMAGES_DIR` | Read-only source directory for the shared library. |
| `WALLPAPER_PUBLIC_ORIGIN` | Actual browser origin; adjust secure-cookie settings for local HTTP development. |
| `WALLPAPER_AUTH_MODE` | `local`, `oidc`, `hybrid` or `disabled`. |
| `WALLPAPER_SESSION_SECRET` | Session secret; generated in the data volume if left empty. |
| `WALLPAPER_STORAGE_DRIVER` | `local` or `s3`; configure S3 connection settings in the same example file. |
| `WALLPAPER_USER_STORAGE_QUOTA_BYTES` | Per-user storage quota. |
| `WALLPAPER_HOMEPAGE_SYNC_URL / WALLPAPER_HOMEPAGE_SYNC_SECRET` | Optional Homepage wallpaper sync and its separate signing credential. |

## Usage

The default service port is `4000`. Set the image directory and browser origin in `.env` before first use. Configure administrators, OIDC and helper download URLs as needed. Media files remain subject to their owners’ rights.

## Project structure

- `web/` — Browser gallery
- `server/` — Authentication, catalog and media API
- `wallpaper-agent/` — Desktop helper
- `mobile/` — Mobile helper

## License

[PolyForm Noncommercial 1.0.0](LICENSE). See [LICENSE_SCOPE.md](LICENSE_SCOPE.md) for the scope of original material and third-party components, and the accompanying notices for third-party copyrights and licenses.
