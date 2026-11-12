import type { TileElement, Wall } from './wall';
import type { Wallpaper } from './types';

/**
 * Fullscreen "exhibition" mode: visible tiles periodically flip over to other
 * wallpapers from the current filter.
 */
export class Showcase {
  active = false;
  private timer: number | undefined;
  private cursor = 0;
  private readonly wall: Wall;
  private readonly pool: () => Wallpaper[];

  constructor(wall: Wall, pool: () => Wallpaper[]) {
    this.wall = wall;
    this.pool = pool;
  }

  async enter(): Promise<void> {
    if (!document.documentElement.requestFullscreen) return;
    try {
      await document.documentElement.requestFullscreen({ navigationUI: 'hide' });
    } catch {
      return;
    }
    this.active = true;
    document.body.classList.add('is-showcase');
    document.querySelector('.folder-panel')?.classList.remove('is-open');
    document.querySelector('.agent-panel')?.classList.remove('is-open');
    this.cycle();
    this.timer = window.setInterval(() => this.cycle(), 10_000);
  }

  leave({ exitFullscreen = false } = {}): void {
    if (!this.active) return;
    this.active = false;
    window.clearInterval(this.timer);
    document.body.classList.remove('is-showcase');
    this.wall.mounted.forEach((tile) => {
      window.clearTimeout(tile._showcaseStart);
      window.clearTimeout(tile._showcaseSwap);
      window.clearTimeout(tile._showcaseCleanup);
      tile.classList.remove('is-showcase-switching');
    });
    if (exitFullscreen && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }

  private visibleTiles(): TileElement[] {
    return [...this.wall.mounted.values()]
      .filter((tile) => {
        const rect = tile.getBoundingClientRect();
        return rect.bottom > 0 && rect.top < innerHeight && rect.right > 0 && rect.left < innerWidth;
      })
      .sort((a, b) => a.offsetTop - b.offsetTop || a.offsetLeft - b.offsetLeft);
  }

  private replacements(tiles: TileElement[]): Wallpaper[] {
    const pool = this.pool();
    const occupied = new Set(tiles.map((tile) => tile._wallpaper?.id));
    const used = new Set<string>();
    const picked: Wallpaper[] = [];
    for (let index = 0; index < tiles.length; index += 1) {
      let candidate: Wallpaper | undefined;
      for (let attempt = 0; attempt < pool.length; attempt += 1) {
        candidate = pool[this.cursor % pool.length];
        this.cursor += 1;
        if (candidate && !occupied.has(candidate.id) && !used.has(candidate.id)) break;
        candidate = undefined;
      }
      candidate ??= pool[(this.cursor + index) % pool.length];
      if (!candidate) continue;
      used.add(candidate.id);
      picked.push(candidate);
    }
    return picked;
  }

  private cycle(): void {
    if (!this.active || document.hidden) return;
    const tiles = this.visibleTiles();
    if (!tiles.length) return;
    const replacements = this.replacements(tiles);
    tiles.forEach((tile, index) => {
      const replacement = replacements[index];
      if (!replacement) return;
      window.clearTimeout(tile._showcaseSwap);
      window.clearTimeout(tile._showcaseCleanup);
      tile._showcaseStart = window.setTimeout(() => {
        tile.classList.remove('is-showcase-switching');
        void tile.offsetWidth;
        tile.classList.add('is-showcase-switching');
        tile._showcaseSwap = window.setTimeout(() => this.wall.setTileWallpaper(tile, replacement), 390);
        tile._showcaseCleanup = window.setTimeout(() => tile.classList.remove('is-showcase-switching'), 860);
      }, index * 68);
    });
  }
}
