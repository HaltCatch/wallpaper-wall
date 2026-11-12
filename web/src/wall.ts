import type { LayoutEntry } from './masonry';
import { encodePath } from './paths';
import type { Wallpaper } from './types';

/** A mounted tile carries its wallpaper and the showcase-mode timers. */
export interface TileElement extends HTMLElement {
  _wallpaper?: Wallpaper;
  _showcaseStart?: number;
  _showcaseSwap?: number;
  _showcaseCleanup?: number;
}

/**
 * The virtualised masonry wall: only tiles near the viewport exist in the DOM,
 * and only thumbnails are ever loaded here.
 */
export class Wall {
  readonly element: HTMLElement;
  readonly mounted = new Map<string, TileElement>();
  private layout: LayoutEntry[] = [];
  private readonly template: HTMLTemplateElement;
  private readonly onOpen: (item: Wallpaper) => void;
  private readonly onToggleFavorite: (item: Wallpaper) => void;
  private readonly isFavorite: (item: Wallpaper) => boolean;

  constructor(element: HTMLElement, template: HTMLTemplateElement, onOpen: (item: Wallpaper) => void, onToggleFavorite: (item: Wallpaper) => void, isFavorite: (item: Wallpaper) => boolean) {
    this.element = element;
    this.template = template;
    this.onOpen = onOpen;
    this.onToggleFavorite = onToggleFavorite;
    this.isFavorite = isFavorite;
  }

  setLayout(entries: LayoutEntry[], totalHeight: number): void {
    this.layout = entries;
    this.element.style.height = `${Math.max(totalHeight, innerHeight)}px`;
  }

  clear(): void {
    this.mounted.forEach((tile) => tile.remove());
    this.mounted.clear();
  }

  showMessage(text: string): void {
    this.clear();
    this.layout = [];
    this.element.replaceChildren(Object.assign(document.createElement('p'), { className: 'wall-error', textContent: text }));
    this.element.style.height = '100vh';
  }

  updateFavorites(): void {
    this.mounted.forEach((tile) => {
      const button = tile.querySelector<HTMLButtonElement>('.tile-favorite');
      const item = tile._wallpaper;
      if (!button || !item) return;
      const active = this.isFavorite(item);
      button.classList.toggle('is-favorite', active);
      button.setAttribute('aria-label', active ? '取消喜欢此壁纸' : '喜欢此壁纸');
      button.title = button.getAttribute('aria-label') ?? '';
    });
  }

  updateMessage(text: string): void {
    const notice = this.element.querySelector('.wall-error');
    if (notice) notice.textContent = text;
  }

  renderWindow(): void {
    if (!this.layout.length) return;
    const wallTop = this.element.getBoundingClientRect().top + scrollY;
    const localScroll = Math.max(0, scrollY - wallTop);
    const start = Math.max(0, localScroll - innerHeight * 0.75);
    const end = localScroll + innerHeight * 1.25;
    const wanted = new Set(
      this.layout.filter((entry) => entry.y + entry.height > start && entry.y < end).map((entry) => entry.item.id),
    );
    this.mounted.forEach((tile, id) => {
      if (!wanted.has(id)) {
        tile.remove();
        this.mounted.delete(id);
      }
    });
    const fragment = document.createDocumentFragment();
    this.layout.forEach((entry) => {
      if (!wanted.has(entry.item.id) || this.mounted.has(entry.item.id)) return;
      const tile = this.createTile(entry);
      this.mounted.set(entry.item.id, tile);
      fragment.append(tile);
    });
    this.element.append(fragment);
  }

  setTileWallpaper(tile: TileElement, item: Wallpaper): void {
    const open = tile.querySelector<HTMLAnchorElement>('.tile-open');
    const download = tile.querySelector<HTMLAnchorElement>('.tile-download');
    const image = tile.querySelector('img');
    const favorite = tile.querySelector<HTMLButtonElement>('.tile-favorite');
    if (!open || !download || !image || !favorite) return;
    tile._wallpaper = item;
    open.href = `detail.html?id=${encodeURIComponent(item.id)}`;
    download.href = encodePath(item.primary.source);
    download.download = item.primary.name;
    image.alt = item.title;
    const active = this.isFavorite(item);
    favorite.classList.toggle('is-favorite', active);
    favorite.setAttribute('aria-label', active ? '取消喜欢此壁纸' : '喜欢此壁纸');
    favorite.title = favorite.getAttribute('aria-label') ?? '';
    image.fetchPriority = 'auto';
    image.addEventListener('load', () => tile.classList.add('is-loaded'), { once: true });
    // Let the browser decode the smallest sufficient thumbnail for the actual
    // card width: at 5–7 columns that is the 640px file, which shrinks the
    // wall's decoded-bitmap memory roughly fourfold with no visual loss.
    if (item.thumbnailSmall) {
      const cardWidth = Math.ceil(parseFloat(tile.style.width)) || 400;
      image.sizes = `${cardWidth}px`;
      image.srcset = `${encodePath(item.thumbnailSmall)} 640w, ${encodePath(item.thumbnail)} 1280w`;
    }
    image.src = encodePath(item.thumbnail);
    if (image.complete) tile.classList.add('is-loaded');
  }

  private createTile(entry: LayoutEntry): TileElement {
    const tile = this.template.content.firstElementChild!.cloneNode(true) as TileElement;
    const open = tile.querySelector<HTMLAnchorElement>('.tile-open')!;
    const favorite = tile.querySelector<HTMLButtonElement>('.tile-favorite')!;
    tile.style.left = `${entry.x}px`;
    tile.style.top = `${entry.y}px`;
    tile.style.width = `${entry.width}px`;
    tile.style.height = `${entry.height}px`;
    tile.style.setProperty('--placeholder', entry.item.placeholder ?? '#171b25');
    open.addEventListener('click', (event) => {
      event.preventDefault();
      this.onOpen(tile._wallpaper ?? entry.item);
    });
    favorite.addEventListener('click', () => this.onToggleFavorite(tile._wallpaper ?? entry.item));
    this.setTileWallpaper(tile, entry.item);
    const image = tile.querySelector('img')!;
    image.fetchPriority = entry.y < innerHeight * 1.25 ? 'high' : 'auto';
    return tile;
  }
}
