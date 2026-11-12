import { openWallpaperDestination } from './homepage-wallpaper';
import { checkIcon, downloadIcon, linkIcon, wallpaperIcon } from './icons';
import { formatBytes } from './format';
import { encodePath } from './paths';
import { copyText, publicImageUrl } from './settings';
import type { Variant, Wallpaper } from './types';

/** The in-page preview overlay used by the wall. Created lazily, reused. */
export class Viewer {
  private overlay: HTMLElement | undefined;
  private releaseTimer: number | undefined;
  /** Invalidates in-flight decode feedback when another switch starts. */
  private switchSeq = 0;
  /** The ordered list currently browsable with prev/next, and the open item. */
  private sequence: (() => Wallpaper[]) | undefined;
  private current: Wallpaper | undefined;
  get isOpen(): boolean {
    return this.overlay?.classList.contains('is-open') ?? false;
  }

  private neighbour(direction: -1 | 1): Wallpaper | undefined {
    if (!this.sequence || !this.current) return undefined;
    const items = this.sequence();
    const index = items.findIndex((item) => item.id === this.current!.id);
    return index < 0 ? undefined : items[index + direction];
  }

  /** Step to the previous/next wallpaper in the wall's current order. */
  prev(): void {
    const item = this.neighbour(-1);
    if (item) this.show(item);
  }

  next(): void {
    const item = this.neighbour(1);
    if (item) this.show(item);
  }

  close(): void {
    if (!this.overlay) return;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    this.overlay.classList.remove('is-open');
    this.overlay.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('is-viewer-open');
    // The stage keeps the full-resolution source referenced after closing,
    // which pins its decoded bitmap (potentially hundreds of MB for large
    // sources) in memory. Release it once the fade-out has finished.
    this.switchSeq += 1;
    this.overlay.querySelector('.viewer-stage')?.classList.remove('is-loading');
    const image = this.overlay.querySelector<HTMLImageElement>('.viewer-stage-image')!;
    window.clearTimeout(this.releaseTimer);
    this.releaseTimer = window.setTimeout(() => {
      if (!this.isOpen) {
        image.onload = null;
        image.removeAttribute('src');
        image.dataset.full = '';
      }
    }, 300);
  }

  /** Open the overlay on `item`. Passing the wall's ordered list enables
   * prev/next stepping (arrows and on-screen chevrons). */
  open(item: Wallpaper, sequence?: () => Wallpaper[]): void {
    this.sequence = sequence;
    this.show(item);
  }

  private show(item: Wallpaper): void {
    this.current = item;
    const overlay = this.ensureOverlay();
    const stage = overlay.querySelector<HTMLElement>('.viewer-stage')!;
    const image = overlay.querySelector<HTMLImageElement>('.viewer-stage-image')!;
    const variants = overlay.querySelector<HTMLElement>('.viewer-variants')!;
    const download = overlay.querySelector<HTMLAnchorElement>('.viewer-download')!;
    const copy = overlay.querySelector<HTMLButtonElement>('.viewer-copy')!;
    const wallpaper = overlay.querySelector<HTMLButtonElement>('.viewer-wallpaper')!;
    const initial = item.primary;
    let selected = initial;
    const finishSwitch = (token: number, button?: HTMLButtonElement) => {
      image.decode().catch(() => {}).finally(() => {
        if (token !== this.switchSeq) return;
        image.classList.remove('is-switching');
        stage.classList.remove('is-loading');
        button?.classList.remove('is-loading');
      });
    };
    const selectVariant = (variant: Variant, button?: HTMLButtonElement) => {
      selected = variant;
      const token = ++this.switchSeq;
      variants.querySelectorAll('.viewer-variant').forEach((element) => element.classList.remove('is-active', 'is-loading'));
      button?.classList.add('is-active', 'is-loading');
      stage.classList.add('is-loading');
      image.classList.add('is-switching');
      image.dataset.full = 'true';
      image.src = encodePath(variant.source);
      image.alt = `${item.title} · ${variant.label}`;
      download.href = encodePath(variant.source);
      download.download = variant.name;
      finishSwitch(token, button);
    };
    this.switchSeq += 1;
    stage.classList.remove('is-loading');
    image.classList.remove('is-switching');
    image.dataset.full = '';
    image.alt = item.title;
    download.href = encodePath(initial.source);
    download.download = initial.name;
    image.onload = () => {
      if (image.dataset.full) return;
      image.dataset.full = 'true';
      // Upgrading the thumbnail to the full-resolution source can take a
      // while for large files; surface the same waiting feedback.
      const token = ++this.switchSeq;
      stage.classList.add('is-loading');
      image.src = encodePath(initial.source);
      finishSwitch(token);
    };
    image.src = encodePath(item.preview);
    variants.replaceChildren();
    item.variants.forEach((variant) => {
      const button = document.createElement('button');
      button.className = `viewer-variant ${variant.source === initial.source ? 'is-active' : ''}`;
      button.type = 'button';
      const label = document.createElement('span');
      label.textContent = variant.label;
      const size = document.createElement('small');
      size.textContent = formatBytes(variant.bytes);
      button.append(label, size);
      button.addEventListener('click', () => selectVariant(variant, button));
      variants.append(button);
    });
    copy.onclick = async () => {
      await copyText(await publicImageUrl(selected.source));
      copy.innerHTML = checkIcon;
      window.setTimeout(() => {
        copy.innerHTML = linkIcon;
      }, 1200);
    };
    wallpaper.onclick = () => {
      openWallpaperDestination(item, selected.source);
    };
    // Only show a chevron when a neighbour exists in the current order.
    const prevButton = overlay.querySelector<HTMLButtonElement>('.viewer-prev')!;
    const nextButton = overlay.querySelector<HTMLButtonElement>('.viewer-next')!;
    prevButton.hidden = !this.neighbour(-1);
    nextButton.hidden = !this.neighbour(1);
    overlay.classList.add('is-open');
    overlay.setAttribute('aria-hidden', 'false');
    document.body.classList.add('is-viewer-open');
    overlay.querySelector<HTMLButtonElement>('.viewer-close')!.focus();
  }

  private ensureOverlay(): HTMLElement {
    if (this.overlay) return this.overlay;
    const overlay = document.createElement('section');
    overlay.className = 'wallpaper-viewer-overlay';
    overlay.setAttribute('aria-hidden', 'true');
    overlay.innerHTML =
      `<div class="wallpaper-viewer-backdrop"></div><button class="viewer-nav viewer-prev" type="button" aria-label="上一张壁纸" title="上一张"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7" /></svg></button><button class="viewer-nav viewer-next" type="button" aria-label="下一张壁纸" title="下一张"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7" /></svg></button><article class="wallpaper-viewer" role="dialog" aria-modal="true" aria-label="壁纸预览"><div class="viewer-window-actions"><button class="viewer-fullscreen" type="button" aria-label="全屏预览" title="全屏预览"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M21 16v3a2 2 0 0 1-2 2h-3M3 16v3a2 2 0 0 0 2 2h3" /></svg></button><button class="viewer-close" type="button" aria-label="关闭预览" title="关闭"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 5 14 14M19 5 5 19" /></svg></button></div><div class="viewer-stage"><img class="viewer-stage-image" alt="" decoding="async" fetchpriority="high" /><div class="viewer-spinner" aria-hidden="true"></div><div class="viewer-stage-actions"><button class="viewer-copy" type="button" title="复制图片链接" aria-label="复制图片链接">${linkIcon}</button><button class="viewer-wallpaper" type="button" title="设为壁纸" aria-label="设为壁纸">${wallpaperIcon}</button><a class="viewer-download" title="下载当前规格" aria-label="下载当前规格">${downloadIcon}</a></div></div><aside class="viewer-variants" aria-label="壁纸规格"></aside></article>`;
    overlay.querySelector<HTMLButtonElement>('.viewer-close')!.addEventListener('click', () => this.close());
    overlay.querySelector<HTMLButtonElement>('.viewer-fullscreen')!.addEventListener('click', async () => {
      const card = overlay.querySelector<HTMLElement>('.wallpaper-viewer')!;
      if (document.fullscreenElement) await document.exitFullscreen();
      else await card.requestFullscreen?.();
    });
    overlay.querySelector<HTMLElement>('.wallpaper-viewer-backdrop')!.addEventListener('click', () => this.close());
    overlay.querySelector<HTMLButtonElement>('.viewer-prev')!.addEventListener('click', () => this.prev());
    overlay.querySelector<HTMLButtonElement>('.viewer-next')!.addEventListener('click', () => this.next());
    document.body.append(overlay);
    this.overlay = overlay;
    return overlay;
  }
}
