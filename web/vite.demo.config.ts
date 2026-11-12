import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  publicDir: 'static',
  appType: 'mpa',
  plugins: [{
    name: 'private-demo-entry',
    transformIndexHtml: {
      order: 'pre',
      handler(html) { return html.replace(/src="\/src\/(?:main|detail)\.ts"/, 'src="/src/demo-entry.ts"').replace('<title>Wallpaper Wall</title>', '<title>Wallpaper Wall · Demo</title>'); },
    },
  }],
  build: {
    outDir: 'demo-dist', target: 'es2022',
    rollupOptions: { input: { index: fileURLToPath(new URL('index.html', import.meta.url)), detail: fileURLToPath(new URL('detail.html', import.meta.url)) } },
  },
});
