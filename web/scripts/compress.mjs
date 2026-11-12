// Precompress the hashed build output so nginx can serve .br/.gz files as-is
// (brotli_static / gzip_static): better ratios than runtime compression, and
// zero compression CPU per request. Zero dependencies — node:zlib does both.
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { brotliCompressSync, constants, gzipSync } from 'node:zlib';

const assetsDir = fileURLToPath(new URL('../dist/assets/', import.meta.url));
const compressible = /\.(js|css|svg|json)$/;
let files = 0;
let before = 0;
let brotliAfter = 0;

for (const name of readdirSync(assetsDir)) {
  const path = join(assetsDir, name);
  if (!compressible.test(name) || !statSync(path).isFile()) continue;
  const data = readFileSync(path);
  if (data.length < 1024) continue;
  writeFileSync(`${path}.gz`, gzipSync(data, { level: 9 }));
  const brotli = brotliCompressSync(data, {
    params: {
      [constants.BROTLI_PARAM_QUALITY]: 11,
      [constants.BROTLI_PARAM_SIZE_HINT]: data.length,
    },
  });
  writeFileSync(`${path}.br`, brotli);
  files += 1;
  before += data.length;
  brotliAfter += brotli.length;
}

console.log(`precompressed ${files} assets: ${(before / 1024).toFixed(1)} KB → ${(brotliAfter / 1024).toFixed(1)} KB (brotli)`);
