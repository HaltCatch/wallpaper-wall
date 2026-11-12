import { api } from './api';
import { showWallToast } from './toast';

interface SystemFolder {
  path: string;
  wallpapers: number;
  visibility: 'public' | 'authenticated' | 'admin';
}

const LABELS: Record<SystemFolder['visibility'], string> = {
  public: '公开',
  authenticated: '登录可见',
  admin: '仅管理员',
};

/** Admin panel for the read-only mounted catalogue: content is maintained on
 * disk, but who can see each top-level folder is decided here. */
export function createSystemFoldersBlock(csrfToken: () => string | undefined, onChanged: () => Promise<void>): HTMLElement {
  const block = document.createElement('div');
  block.className = 'system-folders';
  block.innerHTML = `
    <h4>挂载目录</h4>
    <p class="library-hint">来自服务器只读挂载的 images 目录；内容在磁盘上维护，这里控制每个顶层文件夹对访客的可见性。</p>
    <div class="system-folder-list"></div>`;
  const list = block.querySelector<HTMLElement>('.system-folder-list')!;

  const reload = async () => {
    const data = await api<{ folders: SystemFolder[] }>('api/v1/system-folders');
    list.replaceChildren();
    if (!data.folders.length) {
      const empty = document.createElement('p');
      empty.className = 'library-empty';
      empty.textContent = '挂载目录为空或索引尚未生成。';
      list.append(empty);
      return;
    }
    data.folders.forEach((folder) => {
      const row = document.createElement('div');
      row.className = 'system-folder-row';
      const name = document.createElement('span');
      name.className = 'system-folder-name';
      name.textContent = folder.path;
      const count = document.createElement('small');
      count.textContent = `${folder.wallpapers} 张`;
      const select = document.createElement('select');
      (Object.keys(LABELS) as SystemFolder['visibility'][]).forEach((value) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = LABELS[value];
        select.append(option);
      });
      select.value = folder.visibility;
      select.addEventListener('change', async () => {
        try {
          await api(
            `api/v1/system-folders/${folder.path.split('/').map(encodeURIComponent).join('/')}`,
            { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ visibility: select.value }) },
            csrfToken(),
          );
          showWallToast(`“${folder.path}” 已设为${LABELS[select.value as SystemFolder['visibility']]}`, 'success');
          await onChanged();
        } catch (error) {
          select.value = folder.visibility;
          showWallToast(error instanceof Error ? error.message : '无法更新可见性', 'error');
        }
      });
      row.append(name, count, select);
      list.append(row);
    });
  };

  void reload().catch((error: unknown) => showWallToast(error instanceof Error ? error.message : '无法加载挂载目录', 'error'));
  return block;
}
