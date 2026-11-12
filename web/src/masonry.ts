import type { Wallpaper } from './types';

export interface LayoutEntry {
  item: Wallpaper;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Layout {
  entries: LayoutEntry[];
  /** Total pixel height of the tallest column. */
  height: number;
}

export const DENSITY_OPTIONS = [4, 5, 7] as const;
const PORTRAIT_DENSITY_OPTIONS = [2, 3, 4] as const;

const GAP = 2;

/** FNV-1a; a stable per-wallpaper value that survives reloads. */
export function hashId(value: string): number {
  let result = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index);
    result = Math.imul(result, 16777619);
  }
  return result >>> 0;
}

export function columnCount(densityIndex: number, viewportWidth: number, viewportHeight: number): number {
  const desktop = DENSITY_OPTIONS[densityIndex] ?? DENSITY_OPTIONS[0];
  if (viewportWidth < 620) return Math.max(2, desktop - 2);
  // Use the viewport ratio rather than physical pixels so a rotated 4K monitor
  // gets larger previews at every OS scaling level, and moving between monitors
  // restores the matching layout without changing the saved density preference.
  if (viewportHeight > viewportWidth) return PORTRAIT_DENSITY_OPTIONS[densityIndex] ?? PORTRAIT_DENSITY_OPTIONS[0];
  if (viewportWidth < 980) return Math.max(3, desktop - 1);
  return desktop;
}

export function computeLayout(items: Wallpaper[], columns: number, width: number): Layout {
  const cardWidth = (width - (columns - 1) * GAP) / columns;
  const heights = new Array<number>(columns).fill(0);
  const entries = items.map((item) => {
    let column = 0;
    for (let index = 1; index < heights.length; index += 1) {
      if (heights[index]! < heights[column]!) column = index;
    }
    const aspect = item.width / item.height;
    // Keeps equal-ratio collections from lining up into a rigid grid. The image
    // remains recognisable; object-fit only absorbs this small 14% variation.
    const variation = 0.87 + (hashId(item.id) % 27) / 100;
    const height = Math.max(96, (cardWidth / aspect) * variation);
    const entry: LayoutEntry = { item, x: column * (cardWidth + GAP), y: heights[column]!, width: cardWidth, height };
    heights[column]! += height + GAP;
    return entry;
  });
  return { entries, height: Math.max(...heights, 0) };
}
