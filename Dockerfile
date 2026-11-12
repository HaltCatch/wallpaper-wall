# Stage 1: type-check and bundle the web client (TypeScript 7 + Vite 8/Rolldown,
# installed with pnpm via corepack; the store cache survives rebuilds).
FROM node:22-alpine AS web
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
# CI supplies an ephemeral resolver for this external-dependency step. BuildKit
# owns the default read-only resolv.conf; the optional native mount overrides it
# without changing shared DNS or baking cluster addresses into image layers.
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    --mount=type=secret,id=wallpaper-build-resolv,target=/etc/resolv.conf \
    pnpm install --frozen-lockfile --store-dir /pnpm/store
COPY web/tsconfig.json web/vite.config.ts web/index.html web/detail.html ./
COPY web/scripts ./scripts
COPY web/static ./static
COPY web/src ./src
COPY web/tests ./tests
RUN pnpm run check && pnpm run test && pnpm run build

# Stage 2: nginx serves the built pages; Python runs the catalog builder and API.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx libnginx-mod-http-brotli-filter libnginx-mod-http-brotli-static \
    && rm -rf /var/lib/apt/lists/* \
    && true

# Only runtime files enter the image; agent/mobile sources and docs stay out.
COPY scripts/build_catalog.py /app/scripts/build_catalog.py
COPY server/requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir -r /app/server/requirements.txt
COPY server/ /app/server/
COPY public/ /app/public/
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
COPY docker/nginx.conf /etc/nginx/nginx.conf
COPY --from=web /web/dist/ /app/

RUN chmod +x /app/docker/entrypoint.sh \
    && mkdir -p /app/runtime /app/data /var/cache/nginx /var/run

EXPOSE 8080
ENTRYPOINT ["/app/docker/entrypoint.sh"]
