import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

// Catalog, thumbnails and source images are produced by scripts/build_catalog.py
// and served by nginx in the container. During `npm run dev` those requests are
// proxied to a running instance (default: the local Docker container).
const dataOrigin = process.env.WALLPAPER_DEV_PROXY ?? 'http://localhost:4000';

export default defineConfig({
  // Site-root static files (favicons); wallpaper data stays outside the build.
  publicDir: 'static',
  appType: 'mpa',
  server: {
    proxy: {
      '/public': { target: dataOrigin, changeOrigin: true },
      '/images': { target: dataOrigin, changeOrigin: true },
      '/api': { target: dataOrigin, changeOrigin: true },
      '/healthz': { target: dataOrigin, changeOrigin: true },
    },
  },
  build: {
    target: 'es2022',
    rollupOptions: {
      input: {
        index: fileURLToPath(new URL('index.html', import.meta.url)),
        detail: fileURLToPath(new URL('detail.html', import.meta.url)),
      },
    },
  },
});
