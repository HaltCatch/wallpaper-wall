import { api, getSession } from './api';
import { setWallpaperViaHelper } from './agent-panel';
import { createModal } from './modal';
import { showWallToast } from './toast';
import type { Wallpaper } from './types';

interface SyncResponse {
  ok: boolean;
  state: HomepageWallpaperState;
}

type AppearancePreset = 'clear' | 'regular' | 'prominent';

interface HomepageAppearance {
  preset: AppearancePreset;
  dimOpacity: number;
  blurPx: number;
  saturation: number;
  cardBlurPx: number;
  cardOpacity: number;
  cardSaturation: number;
  cardRefraction: number;
}

interface HomepageWallpaperState {
  revision: number;
  imageUrl?: string;
  appearance?: HomepageAppearance;
}

const CARD_DEFAULTS = { cardBlurPx: 6, cardOpacity: 0, cardSaturation: 1.4, cardRefraction: 70 };
const APPEARANCE_PRESETS: Record<AppearancePreset, Pick<HomepageAppearance, 'preset' | 'dimOpacity' | 'blurPx' | 'saturation'>> = {
  clear: { preset: 'clear', dimOpacity: 0, blurPx: 0, saturation: 1 },
  regular: { preset: 'regular', dimOpacity: 0.18, blurPx: 4, saturation: 0.92 },
  prominent: { preset: 'prominent', dimOpacity: 0.35, blurPx: 8, saturation: 0.84 },
};

const PRESET_LABELS: Record<AppearancePreset, string> = {
  clear: '清透',
  regular: '常规',
  prominent: '强调',
};

function boundedNumber(value: unknown, minimum: number, maximum: number, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) && value >= minimum && value <= maximum ? value : fallback;
}

function normalizeAppearance(value: unknown): HomepageAppearance {
  const candidate = value && typeof value === 'object' ? value as Partial<HomepageAppearance> : {};
  const preset: AppearancePreset = candidate.preset && Object.hasOwn(APPEARANCE_PRESETS, candidate.preset) ? candidate.preset : 'clear';
  const defaults = APPEARANCE_PRESETS[preset];
  return {
    preset,
    dimOpacity: boundedNumber(candidate.dimOpacity, 0, 0.6, defaults.dimOpacity),
    blurPx: boundedNumber(candidate.blurPx, 0, 20, defaults.blurPx),
    saturation: boundedNumber(candidate.saturation, 0.6, 1, defaults.saturation),
    cardBlurPx: boundedNumber(candidate.cardBlurPx, 0, 20, CARD_DEFAULTS.cardBlurPx),
    cardOpacity: boundedNumber(candidate.cardOpacity, 0, 0.6, CARD_DEFAULTS.cardOpacity),
    cardSaturation: boundedNumber(candidate.cardSaturation, 0.6, 2, CARD_DEFAULTS.cardSaturation),
    cardRefraction: boundedNumber(candidate.cardRefraction, 0, 100, CARD_DEFAULTS.cardRefraction),
  };
}

/** Admin-only appearance editor; live changes use the existing HMAC/SSE chain.
 * Opening the dialog only reads state. Changes debounce and save by default. */
export async function openHomepageAppearance(initialState?: HomepageWallpaperState): Promise<void> {
  const session = await getSession();
  if (!session.authenticated || session.user?.role !== 'admin') {
    showWallToast('只有壁纸墙管理员可以调整全局 Homepage 外观。', 'error', 3600);
    return;
  }
  let state = initialState;
  if (!state) {
    try {
      state = (await api<SyncResponse>('api/v1/homepage-wallpaper/main')).state;
    } catch (error) {
      showWallToast(error instanceof Error ? error.message : '无法读取 Homepage 当前外观', 'error', 4200);
      return;
    }
  }
  if (!state) return;
  const modal = createModal('homepage-appearance-dialog', 'Homepage 外观');
  let draft = normalizeAppearance(state.appearance);
  let pendingTimer: number | undefined;
  let saveQueue: Promise<void> | undefined;
  let queued: { snapshot: HomepageAppearance; announce: boolean } | undefined;
  let disposed = false;
  modal.panel.innerHTML = `
    <h3 class="wp-target-title">Homepage 外观</h3>
    <p class="wp-target-note">背景与 Liquid Glass 卡片独立调整；卡片设置不改变文字、图标和布局。</p>
    <div class="hp-appearance-preview" aria-hidden="true"><div class="hp-appearance-preview-image"></div><div class="hp-appearance-preview-card">Liquid Glass<small>卡片材质预览</small></div></div>
    <h4 class="hp-appearance-heading">背景</h4>
    <div class="hp-appearance-presets" role="group" aria-label="材质预设">
      ${Object.entries(PRESET_LABELS).map(([id, label]) => `<button type="button" class="hp-appearance-preset" data-preset="${id}">${label}</button>`).join('')}
    </div>
    <label class="hp-appearance-control">背景压暗 <output data-output="dim"></output><input data-field="dim" type="range" min="0" max="60" step="1" /></label>
    <label class="hp-appearance-control">背景虚化 <output data-output="blur"></output><input data-field="blur" type="range" min="0" max="20" step="1" /></label>
    <label class="hp-appearance-control">背景饱和度 <output data-output="saturation"></output><input data-field="saturation" type="range" min="60" max="100" step="1" /></label>
    <h4 class="hp-appearance-heading">Liquid Glass 卡片 <button type="button" class="auth-text-action" data-action="reset-cards">恢复默认</button></h4>
    <label class="hp-appearance-control">卡片模糊度 <output data-output="cardBlurPx"></output><input data-field="cardBlurPx" type="range" min="0" max="20" step="1" /></label>
    <label class="hp-appearance-control">卡片底色不透明度 <output data-output="cardOpacity"></output><input data-field="cardOpacity" type="range" min="0" max="60" step="1" /></label>
    <label class="hp-appearance-control">卡片饱和度 <output data-output="cardSaturation"></output><input data-field="cardSaturation" type="range" min="60" max="200" step="1" /></label>
    <label class="hp-appearance-control">卡片折射强度 <output data-output="cardRefraction"></output><input data-field="cardRefraction" type="range" min="0" max="100" step="1" /></label>
    <p class="hp-appearance-help">不透明度调整白色玻璃底色。折射效果请在 Homepage 的实际卡片上观察。</p>
    <label class="hp-appearance-live"><input data-field="live" type="checkbox" checked /> 实时同步到全部 Homepage</label>
    <p class="hp-appearance-help" data-status>默认实时同步：停止拖动约 0.3 秒后自动保存并同步；关闭窗口不会撤销已同步的设置。</p>
    <div class="hp-appearance-save-preset">
      <label for="homepage-preset-name">保存当前图片与参数为预设</label>
      <div><input id="homepage-preset-name" type="text" maxlength="64" placeholder="例如：夜航 · 清透" autocomplete="off" /><button type="button" data-action="save-preset">保存预设</button></div>
      <p>保留此刻的图片和全部参数。之后可在 Homepage 时间右侧的齿轮中选择或删除。</p>
    </div>
    <button type="button" class="auth-primary hp-appearance-apply" data-action="apply">应用到全部设备</button>
    <button type="button" class="auth-text-action" data-action="cancel">关闭</button>`;
  const close = () => modal.close();
  const preview = modal.panel.querySelector<HTMLElement>('.hp-appearance-preview-image')!;
  const previewShell = modal.panel.querySelector<HTMLElement>('.hp-appearance-preview')!;
  const previewCard = modal.panel.querySelector<HTMLElement>('.hp-appearance-preview-card')!;
  const dim = modal.panel.querySelector<HTMLInputElement>('[data-field="dim"]')!;
  const blur = modal.panel.querySelector<HTMLInputElement>('[data-field="blur"]')!;
  const saturation = modal.panel.querySelector<HTMLInputElement>('[data-field="saturation"]')!;
  const live = modal.panel.querySelector<HTMLInputElement>('[data-field="live"]')!;
  const apply = modal.panel.querySelector<HTMLButtonElement>('[data-action="apply"]')!;
  const status = modal.panel.querySelector<HTMLElement>('[data-status]')!;
  const presetName = modal.panel.querySelector<HTMLInputElement>('#homepage-preset-name')!;
  const savePreset = modal.panel.querySelector<HTMLButtonElement>('[data-action="save-preset"]')!;
  if (typeof state.imageUrl === 'string' && state.imageUrl.startsWith('https://')) preview.style.backgroundImage = `url(${JSON.stringify(state.imageUrl)})`;

  const render = () => {
    dim.value = String(Math.round(draft.dimOpacity * 100));
    blur.value = String(Math.round(draft.blurPx));
    saturation.value = String(Math.round(draft.saturation * 100));
    modal.panel.querySelectorAll<HTMLButtonElement>('[data-preset]').forEach((button) => button.classList.toggle('is-preferred', button.dataset.preset === draft.preset));
    modal.panel.querySelector<HTMLOutputElement>('[data-output="dim"]')!.value = `${Math.round(draft.dimOpacity * 100)}%`;
    modal.panel.querySelector<HTMLOutputElement>('[data-output="blur"]')!.value = `${Math.round(draft.blurPx)}px`;
    modal.panel.querySelector<HTMLOutputElement>('[data-output="saturation"]')!.value = `${Math.round(draft.saturation * 100)}%`;
    preview.style.filter = draft.blurPx || draft.saturation !== 1 ? `blur(${draft.blurPx}px) saturate(${draft.saturation * 100}%)` : 'none';
    preview.style.transform = draft.blurPx ? 'scale(1.03)' : 'none';
    previewShell.style.setProperty('--hp-preview-dim', String(draft.dimOpacity));
    previewCard.style.backdropFilter = `blur(${draft.cardBlurPx}px) saturate(${draft.cardSaturation * 100}%)`;
    previewCard.style.setProperty('-webkit-backdrop-filter', previewCard.style.backdropFilter);
    previewCard.style.backgroundColor = `rgba(255,255,255,${draft.cardOpacity})`;
    for (const [field, value, suffix] of [
      ['cardBlurPx', draft.cardBlurPx, 'px'], ['cardOpacity', draft.cardOpacity * 100, '%'],
      ['cardSaturation', draft.cardSaturation * 100, '%'], ['cardRefraction', draft.cardRefraction, ''],
    ] as const) {
      modal.panel.querySelector<HTMLInputElement>(`[data-field="${field}"]`)!.value = String(Math.round(value));
      modal.panel.querySelector<HTMLOutputElement>(`[data-output="${field}"]`)!.value = `${Math.round(value)}${suffix}`;
    }
  };
  const enqueueSave = (announce: boolean) => {
    // At most one in-flight and one latest draft; slow connections cannot
    // build a queue of obsolete slider positions.
    queued = { snapshot: { ...draft }, announce: announce || !!queued?.announce };
    if (saveQueue) return saveQueue;
    saveQueue = (async () => {
      apply.disabled = true;
      while (queued) {
        const { snapshot, announce: notify } = queued;
        queued = undefined;
        status.textContent = '正在同步到全部 Homepage…';
        try {
          const response = await api<SyncResponse>(
            'api/v1/homepage-wallpaper/main/appearance',
            { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({
              preset: snapshot.preset, dim_opacity: snapshot.dimOpacity, blur_px: snapshot.blurPx, saturation: snapshot.saturation,
              card_blur_px: snapshot.cardBlurPx, card_opacity: snapshot.cardOpacity,
              card_saturation: snapshot.cardSaturation, card_refraction: snapshot.cardRefraction,
            }) },
            session.csrfToken,
          );
          if (response.state.appearance?.cardBlurPx === undefined) throw new Error('Homepage 同步服务尚未支持卡片设置，请更新同步服务后重试。');
          if (notify) showWallToast(`Homepage 外观已同步（版本 ${response.state.revision}）。`, 'success', 2400);
          status.textContent = '已同步；所有已打开的 Homepage 会立即淡变，新页面也会使用此设置。';
        } catch (error) {
          status.textContent = error instanceof Error ? error.message : '同步失败';
          if (notify || disposed) showWallToast(status.textContent, 'error', 4200);
        }
      }
      apply.disabled = false;
    })().finally(() => { saveQueue = undefined; });
    return saveQueue;
  };
  const maybeLiveSave = () => {
    if (!live.checked) return;
    if (pendingTimer) window.clearTimeout(pendingTimer);
    pendingTimer = window.setTimeout(() => { pendingTimer = undefined; void enqueueSave(false); }, 300);
  };
  modal.panel.querySelectorAll<HTMLButtonElement>('[data-preset]').forEach((button) => button.addEventListener('click', () => {
    const preset = button.dataset.preset as AppearancePreset;
    draft = { ...draft, ...APPEARANCE_PRESETS[preset] };
    render();
    maybeLiveSave();
  }));
  dim.addEventListener('input', () => { draft.dimOpacity = Number(dim.value) / 100; render(); maybeLiveSave(); });
  blur.addEventListener('input', () => { draft.blurPx = Number(blur.value); render(); maybeLiveSave(); });
  saturation.addEventListener('input', () => { draft.saturation = Number(saturation.value) / 100; render(); maybeLiveSave(); });
  for (const [field, divisor] of [['cardBlurPx', 1], ['cardOpacity', 100], ['cardSaturation', 100], ['cardRefraction', 1]] as const) {
    const control = modal.panel.querySelector<HTMLInputElement>(`[data-field="${field}"]`)!;
    control.addEventListener('input', () => { draft[field] = Number(control.value) / divisor; render(); maybeLiveSave(); });
  }
  modal.panel.querySelector<HTMLButtonElement>('[data-action="reset-cards"]')!.addEventListener('click', () => {
    draft = { ...draft, ...CARD_DEFAULTS }; render(); maybeLiveSave();
  });
  live.addEventListener('change', () => {
    if (pendingTimer) { window.clearTimeout(pendingTimer); pendingTimer = undefined; }
    if (live.checked) maybeLiveSave();
    status.textContent = live.checked ? '实时同步已开启：停止拖动约 0.3 秒后会广播到全部设备。' : '实时同步已关闭：拖动只预览当前草稿。';
  });
  apply.addEventListener('click', async () => {
    if (pendingTimer) { window.clearTimeout(pendingTimer); pendingTimer = undefined; }
    await enqueueSave(true);
  });
  savePreset.addEventListener('click', async () => {
    const name = presetName.value.trim();
    if (!name) { presetName.focus(); status.textContent = '请给预设起个名字。'; return; }
    if (!state?.imageUrl) { status.textContent = '当前图片不可用，请重新打开外观编辑器。'; return; }
    const snapshot = { ...draft };
    savePreset.disabled = true;
    try {
      if (saveQueue) await saveQueue;
      await api('api/v1/homepage-wallpaper/main/presets', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({
        name, expected_image_url: state.imageUrl, preset: snapshot.preset,
        dim_opacity: snapshot.dimOpacity, blur_px: snapshot.blurPx, saturation: snapshot.saturation,
        card_blur_px: snapshot.cardBlurPx, card_opacity: snapshot.cardOpacity,
        card_saturation: snapshot.cardSaturation, card_refraction: snapshot.cardRefraction,
      }) }, session.csrfToken);
      status.textContent = `预设“${name}”已保存，可在 Homepage 右上角齿轮中选择。`;
      showWallToast(`预设“${name}”已保存。`, 'success', 2400);
      presetName.value = '';
    } catch (error) { status.textContent = error instanceof Error ? error.message : '预设保存失败'; }
    finally { savePreset.disabled = false; }
  });
  modal.panel.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.addEventListener('click', close);
  modal.overlay.querySelector('.modal-backdrop')!.addEventListener('click', close);
  modal.overlay.addEventListener('keydown', (event) => { if ((event as KeyboardEvent).key === 'Escape') close(); });
  // The shared modal also closes on document Escape. Handle every dismissal,
  // flush the last live draft, and release the observer/DOM exactly once.
  const closed = new MutationObserver(() => {
    if (modal.isOpen() || disposed) return;
    disposed = true;
    closed.disconnect();
    if (pendingTimer) {
      window.clearTimeout(pendingTimer); pendingTimer = undefined;
      if (live.checked) void enqueueSave(false);
    }
    window.setTimeout(() => modal.overlay.remove(), 220);
  });
  closed.observe(modal.overlay, { attributes: true, attributeFilter: ['class'] });
  render();
  modal.open();
}

/** Present the two deliberately separate wallpaper destinations. The native
 * helper remains local-device only; Homepage is a global administrator action.
 */
export function openWallpaperDestination(item: Wallpaper, source: string): void {
  const modal = createModal('wallpaper-destination', '设置壁纸');
  modal.panel.innerHTML = `
    <h3 class="wp-target-title">设置壁纸</h3>
    <p class="wp-target-note">选择应用位置。本机桌面壁纸仅影响当前设备；Homepage 背景会同步给所有 Homepage 客户端。</p>
    <div class="wp-target-actions">
      <button type="button" class="wp-target-option" data-action="desktop">设为本机桌面壁纸</button>
      <button type="button" class="wp-target-option" data-action="homepage">设为 Homepage 背景</button>
    </div>
    <button type="button" class="auth-text-action" data-action="cancel">取消</button>`;
  const close = () => {
    modal.close();
    window.setTimeout(() => modal.overlay.remove(), 220);
  };
  modal.panel.querySelector<HTMLButtonElement>('[data-action="desktop"]')!.addEventListener('click', () => {
    close();
    void setWallpaperViaHelper(item, source);
  });
  modal.panel.querySelector<HTMLButtonElement>('[data-action="homepage"]')!.addEventListener('click', () => {
    void setHomepageBackground(item, source, close);
  });
  modal.panel.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.addEventListener('click', close);
  modal.overlay.querySelector('.modal-backdrop')!.addEventListener('click', close);
  modal.open();
}

async function setHomepageBackground(item: Wallpaper, source: string, close: () => void): Promise<void> {
  const session = await getSession();
  if (!session.authenticated || session.user?.role !== 'admin') {
    showWallToast('只有壁纸墙管理员可以修改全局 Homepage 背景。', 'error', 3600);
    return;
  }
  try {
    const response = await api<SyncResponse>(
      'api/v1/homepage-wallpaper/main',
      {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ wallpaper_id: item.id, variant_source: source }),
      },
      session.csrfToken,
    );
    close();
    showWallToast(`Homepage 背景已同步（版本 ${response.state.revision}）。现在可按实际观感调整外观。`, 'success', 2400);
    void openHomepageAppearance(response.state);
  } catch (error) {
    const message = error instanceof Error ? error.message : '同步失败';
    showWallToast(`Homepage 背景未更新：${message}`, 'error', 4200);
  }
}
