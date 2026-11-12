import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import vm from 'node:vm';
import { JSDOM } from 'jsdom';

function load(dom, file) {
  const source = readFileSync(new URL(`../src/${file}.ts`, import.meta.url), 'utf8')
    .replace(/^import .+;\r?$/gm, '').replace(/^export /gm, '');
  vm.runInContext(stripTypeScriptTypes(source, { mode: 'strip' }), dom.getInternalVMContext());
}
const wait = (ms = 340) => new Promise(resolve => setTimeout(resolve, ms));
const appearance = { preset: 'regular', dimOpacity: .2, blurPx: 4, saturation: .9,
  cardBlurPx: 6, cardOpacity: .12, cardSaturation: 1.4, cardRefraction: 70 };

async function editor(put) {
  const dom = new JSDOM('<body></body>', { url: 'https://wallpaper.example.test', runScripts: 'outside-only' });
  const calls = [], toasts = [];
  Object.assign(dom.window, {
    getSession: async () => ({ authenticated: true, user: { role: 'admin' }, csrfToken: 'test-csrf' }),
    api: async (url, options, csrf) => {
      const payload = JSON.parse(options.body);
      calls.push({ url, payload, csrf });
      if (put) await put(payload);
      return { ok: true, state: { revision: calls.length, appearance: { ...appearance, cardBlurPx: payload.card_blur_px } } };
    },
    showWallToast: (...args) => toasts.push(args), setWallpaperViaHelper: () => {},
  });
  load(dom, 'modal'); load(dom, 'homepage-wallpaper');
  await dom.window.openHomepageAppearance({ revision: 1, appearance, imageUrl: 'https://wallpaper.example.test/public/homepage/one.webp' });
  const document = dom.window.document;
  const control = field => document.querySelector(`[data-field="${field}"]`);
  const change = (field, value) => {
    control(field).value = String(value);
    control(field).dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  };
  return { dom, document, calls, toasts, control, change };
}

test('opening is read-only; default live sync signs all card controls; closing flushes the last draft', async t => {
  const e = await editor(); t.after(() => e.dom.window.close());
  assert.equal(e.control('live').checked, true);
  assert.equal(e.calls.length, 0);
  e.change('cardBlurPx', 10); e.change('cardOpacity', 24); e.change('cardSaturation', 160); e.change('cardRefraction', 90);
  await wait();
  assert.equal(e.calls.length, 1);
  assert.deepEqual(e.calls[0].payload, { preset: 'regular', dim_opacity: .2, blur_px: 4, saturation: .9,
    card_blur_px: 10, card_opacity: .24, card_saturation: 1.6, card_refraction: 90 });
  assert.equal(e.calls[0].csrf, 'test-csrf');
  e.change('cardBlurPx', 12);
  e.document.dispatchEvent(new e.dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await wait(20);
  assert.equal(e.calls.length, 2);
  assert.equal(e.calls[1].payload.card_blur_px, 12);
  await wait();
  assert.equal(e.document.querySelector('.homepage-appearance-dialog'), null);
  assert.equal(e.calls.length, 2, 'dismissal must not leave a duplicate timer');
});

test('manual mode cancels pending live work; background presets preserve card tuning; reset is independent', async t => {
  const e = await editor(); t.after(() => e.dom.window.close());
  e.change('cardBlurPx', 14);
  e.control('live').checked = false;
  e.control('live').dispatchEvent(new e.dom.window.Event('change'));
  e.document.querySelector('[data-preset="clear"]').click();
  await wait();
  assert.equal(e.calls.length, 0);
  assert.equal(e.control('cardBlurPx').value, '14');
  e.document.querySelector('[data-action="apply"]').click(); await wait(10);
  assert.equal(e.calls[0].payload.card_blur_px, 14);
  assert.equal(e.calls[0].payload.dim_opacity, 0);
  e.document.querySelector('[data-action="reset-cards"]').click();
  assert.equal(e.control('cardBlurPx').value, '6');
  assert.equal(e.control('cardOpacity').value, '0');
  assert.equal(e.control('cardRefraction').value, '70');
});

test('slow saves coalesce to the latest draft and never overlap', async t => {
  let finish;
  const e = await editor(() => new Promise(resolve => { finish = resolve; }));
  t.after(() => e.dom.window.close());
  e.change('cardBlurPx', 7); await wait();
  e.change('cardBlurPx', 9); await wait();
  e.change('cardBlurPx', 11); await wait();
  assert.equal(e.calls.length, 1);
  finish(); await wait(20);
  assert.equal(e.calls.length, 2);
  assert.equal(e.calls[1].payload.card_blur_px, 11);
  finish(); await wait(10);
  assert.equal(e.document.querySelector('[data-action="apply"]').disabled, false);
});

test('search dismisses stale focus, Escape and active filters without clearing them', async t => {
  const dom = new JSDOM('<body><div id="outside"></div></body>', { url: 'https://wallpaper.example.test', runScripts: 'outside-only' });
  t.after(() => dom.window.close());
  dom.window.hashId = () => 0;
  load(dom, 'refine-bar');
  const bar = dom.window.createRefineBar(() => {}), document = dom.window.document;
  document.body.append(bar.element);
  const input = bar.element.querySelector('input');
  input.focus(); input.value = 'dragon'; input.dispatchEvent(new dom.window.Event('input'));
  await wait(180);
  assert.ok(bar.element.classList.contains('is-open'));
  assert.ok(bar.element.classList.contains('is-active'));
  // A non-focusable outside target reproduces the lingering-focus path.
  document.getElementById('outside').dispatchEvent(new dom.window.Event('pointerdown', { bubbles: true }));
  assert.equal(bar.element.classList.contains('is-open'), false);
  assert.notEqual(document.activeElement, input);
  assert.equal(bar.state.query, 'dragon');
  input.focus();
  input.dispatchEvent(new dom.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(bar.element.classList.contains('is-open'), false);
  assert.equal(input.value, 'dragon');
  input.focus(); bar.element.querySelector('.refine-collapse').click();
  assert.equal(bar.element.classList.contains('is-open'), false);
  bar.element.dispatchEvent(new dom.window.Event('pointerenter'));
  assert.equal(bar.element.classList.contains('is-open'), true);
  bar.element.dispatchEvent(new dom.window.Event('pointerleave'));
  assert.equal(bar.element.classList.contains('is-open'), false);
});

test('saving a named image/material preset does not apply a manual draft or issue a second update', async t => {
  const e = await editor(); t.after(() => e.dom.window.close());
  e.control('live').checked = false; e.control('live').dispatchEvent(new e.dom.window.Event('change'));
  e.change('cardBlurPx', 1); e.change('cardOpacity', 2); e.change('cardRefraction', 19);
  e.document.querySelector('#homepage-preset-name').value = '夜航';
  e.document.querySelector('[data-action="save-preset"]').click(); await wait();
  assert.equal(e.calls.length, 1); assert.equal(e.calls[0].url, 'api/v1/homepage-wallpaper/main/presets');
  assert.equal(e.calls[0].payload.name, '夜航'); assert.equal(e.calls[0].payload.expected_image_url, 'https://wallpaper.example.test/public/homepage/one.webp');
  assert.equal(e.calls[0].payload.card_refraction, 19); assert.equal(e.calls[0].payload.card_blur_px, 1);
  assert.equal(e.calls[0].csrf, 'test-csrf'); assert.match(e.document.querySelector('[data-status]').textContent, /已保存/);
});
