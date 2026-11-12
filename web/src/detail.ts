import './styles.css';
import { openWallpaperDestination } from './homepage-wallpaper';
import { FavoritesStore } from './favorites';
import { checkIcon, downloadIcon, heartIcon, linkIcon, wallpaperIcon } from './icons';
import { formatBytes } from './format';
import { encodePath } from './paths';
import { copyText, publicImageUrl } from './settings';
import type { Wallpaper } from './types';
import { WallpaperRepository } from './wallpaper-repository';

const root = document.querySelector<HTMLElement>('#detail')!;

function render(item: Wallpaper, favorites: FavoritesStore): void {
  const initial = item.primary;
  // Folder and file names come straight from the library owner's filesystem;
  // assign them through DOM properties so quotes or markup never reach innerHTML.
  root.innerHTML = `
    <section class="viewer">
      <img class="viewer-image" decoding="async" fetchpriority="high" />
      <div class="viewer-spinner" aria-hidden="true"></div>
      <div class="viewer-actions">
        <button class="viewer-copy" type="button" aria-label="复制图片链接" title="复制图片链接">${linkIcon}</button>
        <button class="viewer-favorite" type="button" aria-label="喜欢此壁纸" title="喜欢此壁纸">${heartIcon}</button>
        <button class="viewer-wallpaper" type="button" aria-label="设为壁纸" title="设为壁纸">${wallpaperIcon}</button>
        <a class="viewer-download" aria-label="下载当前规格" title="下载当前规格">${downloadIcon}</a>
      </div>
    </section>
    <aside class="variants" aria-label="壁纸规格"></aside>`;
  const stage = root.querySelector<HTMLElement>('.viewer')!;
  const image = root.querySelector<HTMLImageElement>('.viewer-image')!;
  const download = root.querySelector<HTMLAnchorElement>('.viewer-download')!;
  const copy = root.querySelector<HTMLButtonElement>('.viewer-copy')!;
  const favorite = root.querySelector<HTMLButtonElement>('.viewer-favorite')!;
  const wallpaper = root.querySelector<HTMLButtonElement>('.viewer-wallpaper')!;
  const variants = root.querySelector<HTMLElement>('.variants')!;
  let switchSeq = 0;
  const renderFavorite = () => {
    const active = favorites.has(item.id);
    favorite.classList.toggle('is-favorite', active);
    favorite.setAttribute('aria-label', active ? '取消喜欢此壁纸' : '喜欢此壁纸');
    favorite.title = favorite.getAttribute('aria-label') ?? '';
  };
  renderFavorite();
  favorites.subscribe(renderFavorite);
  const finishSwitch = (token: number, button?: HTMLButtonElement) => {
    image.decode().catch(() => {}).finally(() => {
      if (token !== switchSeq) return;
      image.classList.remove('is-switching');
      stage.classList.remove('is-loading');
      button?.classList.remove('is-loading');
    });
  };
  image.alt = item.title;
  download.href = encodePath(initial.source);
  download.download = initial.name;
  // The detail page is the only place where a source PNG is allowed to load.
  // It first paints the tiny thumbnail, then upgrades just this one image.
  image.addEventListener(
    'load',
    () => {
      if (image.dataset.upgraded) return;
      image.dataset.upgraded = 'true';
      const token = ++switchSeq;
      stage.classList.add('is-loading');
      image.src = encodePath(initial.source);
      finishSwitch(token);
    },
    { once: true },
  );
  image.src = encodePath(item.preview);
  const selectedSource = () => image.dataset.source ?? initial.source;
  copy.addEventListener('click', async () => {
    await copyText(await publicImageUrl(selectedSource()));
    copy.innerHTML = checkIcon;
    window.setTimeout(() => {
      copy.innerHTML = linkIcon;
    }, 1200);
  });
  wallpaper.addEventListener('click', () => {
    openWallpaperDestination(item, selectedSource());
  });
  favorite.addEventListener('click', () => {
    void favorites.toggle(item.id).catch(() => {});
  });
  item.variants.forEach((variant) => {
    const button = document.createElement('button');
    button.className = `variant ${variant.source === initial.source ? 'is-active' : ''}`;
    button.type = 'button';
    const label = document.createElement('span');
    label.textContent = variant.label;
    const size = document.createElement('small');
    size.textContent = formatBytes(variant.bytes);
    button.append(label, size);
    button.addEventListener('click', () => {
      // Picking a variant supersedes the pending preview→primary upgrade;
      // otherwise a slow thumbnail load would snap the image back to primary.
      image.dataset.upgraded = 'true';
      const token = ++switchSeq;
      variants.querySelectorAll('.variant').forEach((element) => element.classList.remove('is-active', 'is-loading'));
      button.classList.add('is-active', 'is-loading');
      stage.classList.add('is-loading');
      image.classList.add('is-switching');
      image.src = encodePath(variant.source);
      image.dataset.source = variant.source;
      image.alt = `${item.title} · ${variant.label}`;
      download.href = encodePath(variant.source);
      download.download = variant.name;
      finishSwitch(token, button);
    });
    variants.append(button);
  });
}

async function start(): Promise<void> {
  const id = new URLSearchParams(location.search).get('id');
  const [wallpapers, favorites] = await Promise.all([WallpaperRepository.load(), (async () => {
    const store = new FavoritesStore();
    await store.initialize();
    return store;
  })()]);
  const item = wallpapers.find(id);
  if (!item) throw new Error('找不到壁纸');
  document.title = item.title;
  render(item, favorites);
}

start().catch(() => {
  root.innerHTML = '<a class="back-link" href="index.html">返回壁纸墙</a>';
});
