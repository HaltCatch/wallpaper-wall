#!/bin/sh
set -eu

APP_DIR=/app
RUNTIME_DIR="${WALLPAPER_PUBLIC_DIR:-/app/runtime}"

mkdir -p "$RUNTIME_DIR/thumbs" "$RUNTIME_DIR/homepage"

# The cache is persisted in a named volume while public/downloads remains baked
# into the image.  Symlinks let the static server keep using normal public URLs.
rm -f "$APP_DIR/public/catalog.json" "$APP_DIR/public/.catalog-cache.json" "$APP_DIR/public/index-status.json"
rm -rf "$APP_DIR/public/thumbs" "$APP_DIR/public/homepage"
ln -s "$RUNTIME_DIR/catalog.json" "$APP_DIR/public/catalog.json"
ln -s "$RUNTIME_DIR/.catalog-cache.json" "$APP_DIR/public/.catalog-cache.json"
ln -s "$RUNTIME_DIR/index-status.json" "$APP_DIR/public/index-status.json"
ln -s "$RUNTIME_DIR/thumbs" "$APP_DIR/public/thumbs"
ln -s "$RUNTIME_DIR/homepage" "$APP_DIR/public/homepage"

# Keep the last complete catalog online while a new index is built. A brand-new
# library starts with an empty, valid catalog; the browser polls the status file
# and refreshes itself as soon as the first build is published.
if [ ! -f "$RUNTIME_DIR/catalog.json" ]; then
  printf '%s' '{"version":2,"count":0,"wallpapers":[]}' > "$RUNTIME_DIR/catalog.json"
fi
printf '%s' '{"state":"building"}' > "$RUNTIME_DIR/index-status.json"

python - <<'PY'
import json
import os
from pathlib import Path

Path('/app/public/settings.json').write_text(json.dumps({
    'publicImageBaseUrl': os.environ.get('WALLPAPER_PUBLIC_IMAGE_BASE_URL', '').strip(),
    'agentScheme': os.environ.get('WALLPAPER_AGENT_SCHEME', 'wallpaperwall').strip() or 'wallpaperwall',
    'assistantDownloadsBaseUrl': os.environ.get('WALLPAPER_DOWNLOADS_BASE_URL', '').strip().rstrip('/'),
}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

# Keep nginx's early request cap aligned with the application setting while
# allowing one MiB for multipart headers and framing.
upload_bytes = int(os.environ.get('WALLPAPER_UPLOAD_MAX_BYTES', str(100 * 1024 * 1024)))
upload_mib = max(1, (upload_bytes + 2 * 1024 * 1024 - 1) // (1024 * 1024))
nginx_config = Path('/etc/nginx/nginx.conf')
nginx_text = nginx_config.read_text(encoding='utf-8')
nginx_text = nginx_text.replace('client_max_body_size 101m; # WALLPAPER_UPLOAD_LIMIT', f'client_max_body_size {upload_mib}m; # WALLPAPER_UPLOAD_LIMIT')
nginx_config.write_text(nginx_text, encoding='utf-8')
PY

(
  if python "$APP_DIR/scripts/build_catalog.py"; then
    printf '%s' '{"state":"ready"}' > "$RUNTIME_DIR/index-status.json"
  else
    printf '%s' '{"state":"failed"}' > "$RUNTIME_DIR/index-status.json"
  fi
) &

# The API owns the SQLite database in /app/data. It is deliberately a single
# process: WAL permits concurrent reads, while serialising writes avoids the
# operational complexity of a database server for this one-node deployment.
cd "$APP_DIR/server"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers &

exec nginx -g 'daemon off;'
