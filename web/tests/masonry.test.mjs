import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';

const source = readFileSync(new URL('../src/masonry.ts', import.meta.url), 'utf8');
const { columnCount, computeLayout } = await import(`data:text/javascript;base64,${Buffer.from(stripTypeScriptTypes(source)).toString('base64')}`);
const counts = (width, height) => [0, 1, 2].map(density => columnCount(density, width, height));

test('rotated 4K layouts use larger previews across Windows display scaling levels', () => {
  for (const [width, height] of [[2160, 3840], [1728, 3072], [1440, 2560], [1080, 1920], [720, 1280]]) {
    assert.deepEqual(counts(width, height), [2, 3, 4]);
  }
});

test('moving back to landscape restores each saved density level', () => {
  for (let density = 0; density < 3; density += 1) {
    const before = columnCount(density, 2560, 1440);
    assert.equal(columnCount(density, 1440, 2560), [2, 3, 4][density]);
    assert.equal(columnCount(density, 2560, 1440), before);
  }
  assert.deepEqual(counts(3840, 2160), [4, 5, 7]);
  assert.deepEqual(counts(980, 800), [4, 5, 7]);
  assert.deepEqual(counts(900, 700), [3, 4, 6]);
  assert.deepEqual(counts(600, 900), [2, 3, 5]);
  assert.deepEqual(counts(390, 844), [2, 3, 5]);
  assert.deepEqual(counts(1080, 1080), [4, 5, 7]);
  assert.equal(columnCount(99, 1440, 2560), 2);
});

test('portrait masonry fills the viewport without overlapping previews', () => {
  const items = Array.from({ length: 30 }, (_, index) => ({
    id: String(index), width: index % 2 ? 3840 : 2160, height: index % 2 ? 2160 : 3840,
  }));
  for (const density of [0, 1, 2]) {
    const width = 1440;
    const columns = columnCount(density, width, 2560);
    const { entries, height } = computeLayout(items, columns, width);
    assert.equal(new Set(entries.map(entry => entry.x)).size, columns);
    for (const entry of entries) {
      assert.ok(entry.x >= 0 && entry.x + entry.width <= width + .001);
      assert.ok(entry.height > 0 && entry.y + entry.height <= height);
      for (const previous of entries.slice(0, entries.indexOf(entry))) {
        if (entry.x === previous.x) assert.ok(entry.y >= previous.y + previous.height);
      }
    }
  }
});
