import type { Wallpaper } from './types';

interface FolderNode {
  path: string;
  name: string;
  count: number;
  children: Map<string, FolderNode>;
}

export function folderTree(items: Wallpaper[]): FolderNode {
  const root: FolderNode = { path: '', name: '全部壁纸', count: 0, children: new Map() };
  items.forEach((item) => {
    root.count += 1;
    let path = '';
    let parent = root;
    item.folder.split('/').forEach((part) => {
      path = path ? `${path}/${part}` : part;
      if (!parent.children.has(part)) parent.children.set(part, { path, name: part, count: 0, children: new Map() });
      parent = parent.children.get(part)!;
      parent.count += 1;
    });
  });
  return root;
}

const byName = (a: FolderNode, b: FolderNode) => a.name.localeCompare(b.name, 'zh-CN', { numeric: true });

export interface FolderPanel {
  element: HTMLElement;
  /** Re-sync the highlighted node after activeFolder changes externally. */
  updateActive: () => void;
  /** Rebuild counts and nodes after personal/shared content changes. */
  setItems: (items: Wallpaper[]) => void;
}

export interface FolderPanelOptions {
  activeFolder: () => string;
  onSelect: (path: string) => void;
  favoritesActive: () => boolean;
  favoritesCount: () => number;
  onSelectFavorites: () => void;
}

export function createFolderPanel(items: Wallpaper[], { activeFolder, onSelect, favoritesActive, favoritesCount, onSelectFavorites }: FolderPanelOptions): FolderPanel {
  const panel = document.createElement('aside');
  panel.className = 'folder-panel';
  panel.innerHTML =
    '<div class="folder-panel-head"><span>壁纸目录</span><button type="button" aria-label="关闭目录">×</button></div><nav class="folder-tree"></nav>';
  const tree = panel.querySelector<HTMLElement>('.folder-tree')!;
  const nodeButtons: { path: string; button: HTMLButtonElement }[] = [];
  let favoritesButton: HTMLButtonElement | undefined;
  const updateActive = () => {
    nodeButtons.forEach(({ path, button }) => button.classList.toggle('is-active', !favoritesActive() && path === activeFolder()));
    if (favoritesButton) {
      favoritesButton.classList.toggle('is-active', favoritesActive());
      favoritesButton.textContent = `我的收藏 · ${favoritesCount()}`;
    }
  };
  const selectFolder = (path: string) => {
    onSelect(path);
    updateActive();
    panel.classList.remove('is-open');
  };
  const renderNode = (node: FolderNode, depth = 0): HTMLElement => {
    const wrapper = document.createElement('div');
    wrapper.className = 'folder-branch';
    const row = document.createElement('div');
    row.className = 'folder-row';
    row.style.setProperty('--depth', String(depth));
    const hasChildren = node.children.size > 0;
    if (hasChildren) {
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'folder-expand';
      toggle.textContent = '›';
      toggle.addEventListener('click', () => {
        const expanded = wrapper.classList.toggle('is-expanded');
        toggle.textContent = expanded ? '⌄' : '›';
      });
      row.append(toggle);
    } else {
      row.append(Object.assign(document.createElement('span'), { className: 'folder-expand-spacer' }));
    }
    const select = document.createElement('button');
    select.type = 'button';
    select.className = 'folder-node';
    select.classList.toggle('is-active', node.path === activeFolder());
    select.textContent = `${node.name} · ${node.count}`;
    select.addEventListener('click', () => selectFolder(node.path));
    nodeButtons.push({ path: node.path, button: select });
    row.append(select);
    wrapper.append(row);
    if (hasChildren) {
      const children = document.createElement('div');
      children.className = 'folder-children';
      [...node.children.values()].sort(byName).forEach((child) => children.append(renderNode(child, depth + 1)));
      wrapper.append(children);
    }
    return wrapper;
  };
  const setItems = (nextItems: Wallpaper[]) => {
    tree.replaceChildren();
    nodeButtons.length = 0;
    const all = folderTree(nextItems);
    favoritesButton = document.createElement('button');
    favoritesButton.type = 'button';
    favoritesButton.className = 'folder-node folder-favorites';
    favoritesButton.addEventListener('click', () => {
      onSelectFavorites();
      updateActive();
      panel.classList.remove('is-open');
    });
    const allButton = document.createElement('button');
    allButton.type = 'button';
    allButton.className = 'folder-node folder-all';
    allButton.classList.toggle('is-active', !favoritesActive() && !activeFolder());
    allButton.textContent = `全部壁纸 · ${all.count}`;
    allButton.addEventListener('click', () => selectFolder(''));
    nodeButtons.push({ path: '', button: allButton });
    tree.append(favoritesButton, allButton);
    [...all.children.values()].sort(byName).forEach((node) => tree.append(renderNode(node)));
    updateActive();
  };
  panel.querySelector<HTMLButtonElement>('.folder-panel-head button')!.addEventListener('click', () => panel.classList.remove('is-open'));
  document.body.append(panel);
  setItems(items);
  return { element: panel, updateActive, setItems };
}
