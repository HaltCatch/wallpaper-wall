import './styles.css';
import { accountIcon, createAuthModal } from './auth-modal';
import { watchIndexBuild } from './catalog';
import { createFolderPanel } from './folder-panel';
import { FavoritesStore } from './favorites';
import { createHub } from './hub';
import { gridIcon } from './icons';
import { columnCount, computeLayout, DENSITY_OPTIONS } from './masonry';
import { createScrollRail } from './scroll-rail';
import { createRefineBar } from './refine-bar';
import { Showcase } from './showcase';
import type { Wallpaper } from './types';
import { Viewer } from './viewer';
import { Wall } from './wall';
import { showWallToast } from './toast';
import { WallpaperRepository } from './wallpaper-repository';

const wallElement = document.querySelector<HTMLElement>('#wall')!;
const tileTemplate = document.querySelector<HTMLTemplateElement>('#tile-template')!;

let densityIndex = Number(localStorage.getItem('wall-masonry-density') ?? 0);
if (!Number.isInteger(densityIndex) || densityIndex < 0 || densityIndex >= DENSITY_OPTIONS.length) densityIndex = 0;
let activeFolder = new URL(location.href).searchParams.get('folder') ?? '';
let favoritesOnly = new URL(location.href).searchParams.get('favorites') === '1';
let renderQueued = false;

function toolButton(className: string, title: string, content: string, onClick: () => void): HTMLButtonElement {
  const button = document.createElement('button');
  button.className = className;
  button.type = 'button';
  button.title = title;
  button.setAttribute('aria-label', title);
  if (content.startsWith('<svg')) button.innerHTML = content;
  else button.textContent = content;
  button.addEventListener('click', onClick);
  return button;
}

async function start(): Promise<void> {
  const wallpapers = await WallpaperRepository.load();
  const favorites = new FavoritesStore();
  await favorites.initialize();
  const toggleFavorite = (item: Wallpaper) => {
    void favorites.toggle(item.id).catch((error: unknown) => showWallToast(error instanceof Error ? error.message : '收藏更新失败', 'error'));
  };
  const viewer = new Viewer();
  const wall = new Wall(wallElement, tileTemplate, (item) => viewer.open(item, filteredItems), toggleFavorite, (item) => favorites.has(item.id));
  const showcase = new Showcase(wall, filteredItems);

  const allItems = (): Wallpaper[] => wallpapers.all();

  function favoriteCount(): number {
    // Browser storage can outlive a re-indexed/deleted catalogue item. The
    // directory shows only favourites that can actually be rendered now.
    return allItems().filter((item) => favorites.has(item.id)).length;
  }

  function filteredItems(): Wallpaper[] {
    const availableItems = allItems();
    const folderItems = activeFolder
      ? availableItems.filter((item) => item.folder === activeFolder || item.folder.startsWith(`${activeFolder}/`))
      : availableItems;
    const scoped = favoritesOnly ? folderItems.filter((item) => favorites.has(item.id)) : folderItems;
    // Search, orientation and sort refine whatever the folder/favourites view
    // currently shows.
    return refine.apply(scoped);
  }

  const render = () => {
    const columns = columnCount(densityIndex, innerWidth, innerHeight);
    const nextColumns = columnCount((densityIndex + 1) % DENSITY_OPTIONS.length, innerWidth, innerHeight);
    densityButton.title = `当前每行 ${columns} 张，点击切换为 ${nextColumns} 张`;
    densityButton.setAttribute('aria-label', densityButton.title);
    wall.clear();
    if (!allItems().length) {
      wall.showMessage('正在生成壁纸目录…');
      return;
    }
    const items = filteredItems();
    if (!items.length) {
      wall.showMessage(refine.isActive() ? '没有匹配的壁纸，换个关键词或筛选试试。' : favoritesOnly ? '这里还没有喜欢的壁纸。' : '此文件夹暂无壁纸。');
      return;
    }
    const width = Math.max(1, wallElement.clientWidth || innerWidth);
    const layout = computeLayout(items, columns, width);
    wall.setLayout(layout.entries, layout.height);
    wall.renderWindow();
    requestAnimationFrame(() => rail.update());
  };

  const selectView = (folder: string, onlyFavorites: boolean) => {
    activeFolder = folder;
    favoritesOnly = onlyFavorites;
    const next = new URL(location.href);
    if (folder) next.searchParams.set('folder', folder);
    else next.searchParams.delete('folder');
    if (onlyFavorites) next.searchParams.set('favorites', '1');
    else next.searchParams.delete('favorites');
    history.pushState({}, '', next);
    window.scrollTo({ top: 0, behavior: 'auto' });
    render();
    panel.updateActive();
  };

  const panel = createFolderPanel(allItems(), {
    activeFolder: () => activeFolder,
    onSelect: (path) => {
      selectView(path, false);
    },
    favoritesActive: () => favoritesOnly,
    favoritesCount: favoriteCount,
    onSelectFavorites: () => selectView('', true),
  });
  const refreshLibraryView = async () => {
    // Visibility-policy edits affect the system catalogue too, so both
    // sources reload together.
    await wallpapers.refresh();
    panel.setItems(allItems());
    render();
  };

  const densityButton = toolButton('density-toggle', '调整壁纸密度', gridIcon, () => {
    densityIndex = (densityIndex + 1) % DENSITY_OPTIONS.length;
    localStorage.setItem('wall-masonry-density', String(densityIndex));
    render();
  });
  document.body.append(
    densityButton,
    toolButton(
      'folder-toggle',
      '选择期数或文件夹',
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/></svg>',
      () => panel.element.classList.toggle('is-open'),
    ),
    toolButton(
      'showcase-toggle',
      '进入展示墙模式',
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm4 5 7 3-7 3V9Z" /></svg>',
      () => {
        if (showcase.active) showcase.leave({ exitFullscreen: true });
        else void showcase.enter();
      },
    ),
  );
  const rail = createScrollRail();
  const refine = createRefineBar(() => render());
  document.body.append(refine.element);

  // A single account entry: logged-out visitors get the centered sign-in
  // dialog; signed-in users get the 管理中心 with account, libraries (incl.
  // the admin-only official library) and the assistant downloads.
  if (favorites.authenticated) {
    const hub = createHub(favorites, refreshLibraryView);
    const accountButton = toolButton(
      'account-toggle',
      `${favorites.accountName ?? '账户'}（已登录）`,
      `${accountIcon}<span class="account-toggle-label">账户</span>`,
      () => hub.open('account'),
    );
    // Show the identity provider's portrait (authentik `picture` claim) in place
    // of the generic glyph when one is available.
    const avatarUrl = favorites.avatarUrl;
    if (avatarUrl) {
      const avatar = document.createElement('img');
      avatar.className = 'account-avatar';
      avatar.alt = '';
      avatar.referrerPolicy = 'no-referrer';
      // Assign through the DOM property so the URL is never parsed as markup;
      // a broken portrait quietly reverts to the glyph.
      avatar.src = avatarUrl;
      avatar.addEventListener('error', () => avatar.remove());
      accountButton.prepend(avatar);
      accountButton.querySelector('svg')?.remove();
    }
    document.body.append(accountButton);
  } else {
    const authModal = createAuthModal(favorites);
    document.body.append(
      toolButton('account-toggle', '登录或创建账户', `${accountIcon}<span class="account-toggle-label">登录</span>`, authModal.open),
    );
    if (new URL(location.href).searchParams.get('auth') === 'denied') {
      showWallToast('统一身份登录已取消', 'info');
      const cleaned = new URL(location.href);
      cleaned.searchParams.delete('auth');
      history.replaceState({}, '', cleaned);
    }
  }
  favorites.subscribe(() => {
    wall.updateFavorites();
    panel.updateActive();
    if (favoritesOnly) render();
  });

  render();
  // Reveal the hover-only controls once on a visitor's first load so the
  // toolbar and login entry are discoverable, then fade back to the clean look.
  if (!localStorage.getItem('wall-intro-seen')) {
    localStorage.setItem('wall-intro-seen', '1');
    document.body.classList.add('is-intro');
    window.setTimeout(() => document.body.classList.remove('is-intro'), 3200);
  }
  watchIndexBuild({
    hasContent: () => wallpapers.catalogCount > 0,
    onFailed: () => wall.updateMessage('壁纸目录生成失败，请查看容器日志后重启服务。'),
  });

  addEventListener('fullscreenchange', () => {
    if (showcase.active && !document.fullscreenElement) showcase.leave();
  });
  addEventListener('popstate', () => {
    activeFolder = new URL(location.href).searchParams.get('folder') ?? '';
    favoritesOnly = new URL(location.href).searchParams.get('favorites') === '1';
    panel.updateActive();
    render();
  });
  addEventListener(
    'scroll',
    () => {
      rail.update();
      if (renderQueued) return;
      renderQueued = true;
      requestAnimationFrame(() => {
        renderQueued = false;
        wall.renderWindow();
      });
    },
    { passive: true },
  );
  let resizeTimer: number | undefined;
  addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => render(), 120);
  });
  addEventListener(
    'pointermove',
    (event) => {
      wallElement.style.setProperty('--parallax-x', `${(event.clientX / innerWidth - 0.5) * -4}px`);
      wallElement.style.setProperty('--parallax-y', `${(event.clientY / innerHeight - 0.5) * -3}px`);
    },
    { passive: true },
  );
  addEventListener('keydown', (event) => {
    if (viewer.isOpen) {
      if (['q', 'x', 'Escape'].includes(event.key)) viewer.close();
      else if (event.key === 'ArrowLeft') viewer.prev();
      else if (event.key === 'ArrowRight') viewer.next();
    } else if (showcase.active && event.key === 'Escape') showcase.leave({ exitFullscreen: true });
  });
}

start().catch((error: unknown) => {
  console.error(error);
  wallElement.innerHTML = '<p class="wall-error">壁纸目录尚未生成。</p>';
});
