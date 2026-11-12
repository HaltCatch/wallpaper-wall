import type { Wallpaper } from './types';
import { hashId } from './masonry';

export type Orientation = 'all' | 'landscape' | 'portrait';
export type SortOrder = 'default' | 'newest' | 'random';

export interface RefineState {
  query: string;
  orientation: Orientation;
  sort: SortOrder;
  /** Reshuffle key for random order; stable across re-renders until changed. */
  seed: number;
}

export interface RefineBar {
  element: HTMLElement;
  state: RefineState;
  /** Whether any refinement (search/orientation/non-default sort) is active. */
  isActive: () => boolean;
  /** Apply search, orientation filter and sort order to a folder-scoped list. */
  apply: (items: Wallpaper[]) => Wallpaper[];
}

const ORIENTATION_KEY = 'wall-refine-orientation';
const SORT_KEY = 'wall-refine-sort';

function restore<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  const value = localStorage.getItem(key) as T | null;
  return value && allowed.includes(value) ? value : fallback;
}

const ORIENTATIONS: { value: Orientation; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'landscape', label: '横屏' },
  { value: 'portrait', label: '竖屏' },
];

const SORTS: { value: SortOrder; label: string }[] = [
  { value: 'default', label: '默认' },
  { value: 'newest', label: '最新' },
  { value: 'random', label: '随机' },
];

const SEARCH_ICON =
  '<svg class="refine-search-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.2-3.2"/></svg>';

/** Top-centre control for refining the wall: keyword search, orientation filter
 * and sort order. All three run client-side over the already-loaded catalogue,
 * so refinement is instant and needs no extra requests. */
export function createRefineBar(onChange: () => void): RefineBar {
  const state: RefineState = {
    query: '',
    orientation: restore<Orientation>(ORIENTATION_KEY, ['all', 'landscape', 'portrait'], 'all'),
    sort: restore<SortOrder>(SORT_KEY, ['default', 'newest', 'random'], 'default'),
    seed: (Math.random() * 0xffffffff) >>> 0,
  };

  const isActive = () => state.query.trim() !== '' || state.orientation !== 'all' || state.sort !== 'default';

  const element = document.createElement('div');
  element.className = 'refine-bar';
  element.setAttribute('role', 'search');
  const segment = (name: string, options: { value: string; label: string }[], active: string) =>
    `<div class="refine-segment" data-group="${name}" role="group">${options
      .map((option) => `<button type="button" data-value="${option.value}" class="${option.value === active ? 'is-active' : ''}">${option.label}</button>`)
      .join('')}</div>`;
  element.innerHTML = `
    <label class="refine-search">
      ${SEARCH_ICON}
      <input type="search" placeholder="搜索壁纸名称或文件夹" autocomplete="off" spellcheck="false" aria-label="搜索壁纸" />
    </label>
    ${segment('orientation', ORIENTATIONS, state.orientation)}
    ${segment('sort', SORTS, state.sort)}
    <button type="button" class="refine-collapse" aria-label="收起搜索">×</button>`;

  // Active filters remain indicated, but do not permanently pin the bar open.
  // Safari/macOS can retain input/button focus after clicking a non-focusable
  // image or the page background; explicitly dismiss that stale focus.
  const syncActive = () => element.classList.toggle('is-active', isActive());
  syncActive();

  const input = element.querySelector<HTMLInputElement>('input')!;
  const expand = () => {
    element.classList.remove('is-dismissed');
    element.classList.add('is-open');
  };
  const collapse = () => {
    element.classList.remove('is-open');
    element.classList.add('is-dismissed');
    if (document.activeElement instanceof HTMLElement && element.contains(document.activeElement)) document.activeElement.blur();
  };
  element.addEventListener('pointerenter', (event) => { if (event.pointerType !== 'touch') expand(); });
  element.addEventListener('pointerleave', () => {
    if (!element.contains(document.activeElement)) collapse();
  });
  element.addEventListener('focusin', expand);
  element.addEventListener('focusout', () => {
    queueMicrotask(() => { if (!element.contains(document.activeElement) && !element.matches(':hover')) collapse(); });
  });
  document.addEventListener('pointerdown', (event) => {
    if (event.target instanceof Node && !element.contains(event.target)) collapse();
  }, { capture: true });
  element.querySelector<HTMLButtonElement>('.refine-collapse')!.addEventListener('click', collapse);
  let debounce: number | undefined;
  input.addEventListener('input', () => {
    window.clearTimeout(debounce);
    debounce = window.setTimeout(() => {
      state.query = input.value;
      syncActive();
      onChange();
    }, 140);
  });
  // Escape dismisses the toolbar without silently clearing the user's filter.
  element.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      event.preventDefault();
      collapse();
    }
  });

  element.querySelectorAll<HTMLElement>('.refine-segment').forEach((group) => {
    const name = group.dataset['group'];
    group.querySelectorAll<HTMLButtonElement>('button').forEach((button) => {
      button.addEventListener('click', () => {
        const value = button.dataset['value']!;
        if (name === 'orientation') {
          state.orientation = value as Orientation;
          localStorage.setItem(ORIENTATION_KEY, value);
        } else {
          // Clicking 随机 again reshuffles; picking another sort just switches.
          if (value === 'random' && state.sort === 'random') state.seed = (Math.random() * 0xffffffff) >>> 0;
          state.sort = value as SortOrder;
          localStorage.setItem(SORT_KEY, value);
        }
        group.querySelectorAll('button').forEach((sibling) => sibling.classList.toggle('is-active', sibling === button));
        syncActive();
        onChange();
      });
    });
  });

  const apply = (items: Wallpaper[]): Wallpaper[] => {
    let result = items;
    const query = state.query.trim().toLowerCase();
    if (query) result = result.filter((item) => item.title.toLowerCase().includes(query) || item.folder.toLowerCase().includes(query));
    if (state.orientation !== 'all')
      result = result.filter((item) => (state.orientation === 'landscape' ? item.width >= item.height : item.height > item.width));
    if (state.sort === 'newest') result = [...result].sort((left, right) => (right.mtime ?? 0) - (left.mtime ?? 0));
    else if (state.sort === 'random') result = [...result].sort((left, right) => hashId(`${left.id}:${state.seed}`) - hashId(`${right.id}:${state.seed}`));
    return result;
  };

  return { element, state, isActive, apply };
}
