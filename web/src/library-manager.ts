import { api, uploadWithProgress } from './api';
import { confirmDialog } from './modal';
import { showWallToast } from './toast';

const ACCEPTED_UPLOAD_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

export interface LibraryFolder {
  id: string;
  parent_id: string | null;
  name: string;
  visibility: 'private' | 'authenticated' | 'public';
  inherit_acl: boolean;
  official: boolean;
}

interface FolderListResponse {
  folders: LibraryFolder[];
  official?: LibraryFolder[];
}

interface FolderGrant {
  id: string;
  username: string | null;
  display_name: string;
  email: string | null;
}

export interface LibraryManagerOptions {
  /** Manage the admin-run official library instead of the personal one. */
  official: boolean;
  csrfToken: () => string | undefined;
  /** Called after any mutation so the wall can refresh its contents. */
  onChanged: () => Promise<void>;
}

export interface LibraryManager {
  element: HTMLElement;
  reload: () => Promise<void>;
}

const VISIBILITY_LABELS: Record<LibraryFolder['visibility'], string> = {
  private: '私有',
  authenticated: '登录可见',
  public: '公开',
};

/** Folder management with real forms: rename, visibility (incl. inheriting the
 * parent ACL), targeted viewer grants, upload, clear and delete. Used both for
 * the personal library and — by administrators — the official library. */
export function createLibraryManager({ official, csrfToken, onChanged }: LibraryManagerOptions): LibraryManager {
  const element = document.createElement('div');
  element.className = 'library-manager';
  element.innerHTML = `
    <div class="library-toolbar">
      <button type="button" class="library-action" data-action="new-folder">新建文件夹</button>
      <label class="library-action library-upload"><input type="file" accept="image/jpeg,image/png,image/webp" multiple hidden />上传图片</label>
    </div>
    <form class="library-create" hidden>
      <input name="name" maxlength="120" required placeholder="文件夹名称" />
      <button type="submit" class="library-action">创建</button>
      <button type="button" class="library-action is-quiet" data-action="cancel-create">取消</button>
    </form>
    <p class="library-hint">${official ? '默认图库对所有访客可见（可按文件夹调整），仅管理员可维护。选中文件夹后可上传或拖拽图片。' : '点击文件夹名称选中后可上传，或直接把图片拖拽到这里；点击 ⚙ 展开权限与管理。子文件夹默认继承上级权限。'}</p>
    <div class="library-status" hidden></div>
    <div class="library-tree"></div>`;

  const tree = element.querySelector<HTMLElement>('.library-tree')!;
  const fileInput = element.querySelector<HTMLInputElement>('input[type="file"]')!;
  const createForm = element.querySelector<HTMLFormElement>('.library-create')!;
  const statusLine = element.querySelector<HTMLElement>('.library-status')!;

  let folders: LibraryFolder[] = [];
  let selectedId: string | undefined;
  let editorId: string | undefined;

  const report = (error: unknown, fallback: string) => showWallToast(error instanceof Error ? error.message : fallback, 'error');
  const mutate = async (path: string, init: RequestInit): Promise<void> => {
    await api(path, { ...init, headers: { 'Content-Type': 'application/json', ...init.headers } }, csrfToken());
  };

  const reload = async () => {
    const data = await api<FolderListResponse>('api/v1/folders');
    folders = (official ? data.official : data.folders) ?? [];
    renderTree();
  };

  const changed = async () => {
    await reload();
    await onChanged();
  };

  const renderEditor = (folder: LibraryFolder): HTMLElement => {
    const editor = document.createElement('div');
    editor.className = 'library-editor';
    const canInherit = folder.parent_id !== null;
    const visibilityValue = folder.inherit_acl ? 'inherit' : folder.visibility;
    editor.innerHTML = `
      <form class="library-field" data-form="rename">
        <label>名称</label>
        <input name="name" maxlength="120" required />
        <button type="submit" class="library-action">保存</button>
      </form>
      <div class="library-field">
        <label>权限</label>
        <select data-field="visibility">
          ${canInherit ? '<option value="inherit">继承上级权限</option>' : ''}
          <option value="private">私有</option>
          <option value="authenticated">登录可见</option>
          <option value="public">公开</option>
        </select>
      </div>
      <form class="library-field" data-form="grants" ${folder.inherit_acl ? 'hidden' : ''}>
        <label>定向共享</label>
        <input name="grants" placeholder="用户名或 OIDC 邮箱，逗号分隔" />
        <button type="submit" class="library-action">保存</button>
      </form>
      ${folder.inherit_acl ? '<p class="library-note">此文件夹继承上级的权限与定向共享；如需单独设置，请先选择显式权限。</p>' : ''}
      <div class="library-danger">
        <button type="button" class="library-action is-danger" data-action="clear">清空壁纸</button>
        <button type="button" class="library-action is-danger" data-action="delete">删除文件夹</button>
      </div>`;

    const renameForm = editor.querySelector<HTMLFormElement>('[data-form="rename"]')!;
    const renameInput = renameForm.querySelector<HTMLInputElement>('input')!;
    renameInput.value = folder.name;
    renameForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      const name = renameInput.value.trim();
      if (!name || name === folder.name) return;
      try {
        await mutate(`api/v1/folders/${encodeURIComponent(folder.id)}`, { method: 'PATCH', body: JSON.stringify({ name }) });
        await changed();
      } catch (error) {
        report(error, '无法重命名文件夹');
      }
    });

    const visibilitySelect = editor.querySelector<HTMLSelectElement>('[data-field="visibility"]')!;
    visibilitySelect.value = visibilityValue;
    visibilitySelect.addEventListener('change', async () => {
      const value = visibilitySelect.value;
      const body = value === 'inherit' ? { inherit_acl: true } : { visibility: value, inherit_acl: false };
      try {
        await mutate(`api/v1/folders/${encodeURIComponent(folder.id)}`, { method: 'PATCH', body: JSON.stringify(body) });
        await changed();
      } catch (error) {
        visibilitySelect.value = visibilityValue;
        report(error, '无法修改权限');
      }
    });

    const grantsForm = editor.querySelector<HTMLFormElement>('[data-form="grants"]');
    if (grantsForm && !folder.inherit_acl) {
      const grantsInput = grantsForm.querySelector<HTMLInputElement>('input')!;
      void api<{ grants: FolderGrant[] }>(`api/v1/folders/${encodeURIComponent(folder.id)}/grants`)
        .then((current) => {
          grantsInput.value = current.grants.map((grant) => grant.username ?? grant.email ?? grant.id).join(', ');
        })
        .catch(() => undefined);
      grantsForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const identifiers = grantsInput.value.split(/[，,\n]/).map((entry) => entry.trim()).filter(Boolean);
        try {
          await mutate(`api/v1/folders/${encodeURIComponent(folder.id)}/grants`, { method: 'PUT', body: JSON.stringify({ identifiers }) });
          showWallToast(identifiers.length ? '定向共享已更新' : '定向共享已清除', 'success');
          await onChanged();
        } catch (error) {
          report(error, '无法更新共享账号');
        }
      });
    }

    editor.querySelector<HTMLButtonElement>('[data-action="clear"]')!.addEventListener('click', async () => {
      if (!(await confirmDialog({ title: '清空文件夹', message: `清空“${folder.name}”中的全部壁纸？此操作不可恢复。`, confirmLabel: '清空', danger: true }))) return;
      try {
        await mutate(`api/v1/folders/${encodeURIComponent(folder.id)}/wallpaper`, { method: 'DELETE' });
        showWallToast('文件夹内容已清空', 'success');
        await changed();
      } catch (error) {
        report(error, '无法清空文件夹');
      }
    });
    editor.querySelector<HTMLButtonElement>('[data-action="delete"]')!.addEventListener('click', async () => {
      if (!(await confirmDialog({ title: '删除文件夹', message: `删除空文件夹“${folder.name}”？`, confirmLabel: '删除', danger: true }))) return;
      try {
        await mutate(`api/v1/folders/${encodeURIComponent(folder.id)}`, { method: 'DELETE' });
        if (selectedId === folder.id) selectedId = undefined;
        if (editorId === folder.id) editorId = undefined;
        await changed();
      } catch (error) {
        report(error, '无法删除文件夹');
      }
    });
    return editor;
  };

  const renderTree = () => {
    tree.replaceChildren();
    const children = new Map<string | null, LibraryFolder[]>();
    folders.forEach((folder) => {
      const group = children.get(folder.parent_id) ?? [];
      group.push(folder);
      children.set(folder.parent_id, group);
    });
    const visit = (parentId: string | null, depth: number) => {
      (children.get(parentId) ?? [])
        .sort((left, right) => left.name.localeCompare(right.name, 'zh-CN', { numeric: true }))
        .forEach((folder) => {
          const row = document.createElement('div');
          row.className = 'library-row';
          row.classList.toggle('is-selected', folder.id === selectedId);
          row.style.setProperty('--library-depth', String(depth));
          const select = document.createElement('button');
          select.type = 'button';
          select.className = 'library-name';
          const badge = folder.inherit_acl ? '继承' : VISIBILITY_LABELS[folder.visibility];
          select.innerHTML = `<span></span><small>${badge}</small>`;
          select.querySelector('span')!.textContent = folder.name;
          select.addEventListener('click', () => {
            selectedId = selectedId === folder.id ? undefined : folder.id;
            renderTree();
          });
          const manage = document.createElement('button');
          manage.type = 'button';
          manage.className = 'library-manage';
          manage.title = '权限与管理';
          manage.setAttribute('aria-label', `管理文件夹 ${folder.name}`);
          manage.innerHTML =
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h9M17.5 8H20M4 16h2.5M11 16h9"/><circle cx="15" cy="8" r="2.2"/><circle cx="8.5" cy="16" r="2.2"/></svg>';
          manage.classList.toggle('is-open', editorId === folder.id);
          manage.addEventListener('click', () => {
            editorId = editorId === folder.id ? undefined : folder.id;
            renderTree();
          });
          row.append(select, manage);
          tree.append(row);
          if (editorId === folder.id) tree.append(renderEditor(folder));
          visit(folder.id, depth + 1);
        });
    };
    visit(null, 0);
    if (!folders.length) {
      const empty = document.createElement('p');
      empty.className = 'library-empty';
      empty.textContent = official ? '还没有默认图库文件夹，先新建一个。' : '还没有个人文件夹，先新建一个。';
      tree.append(empty);
    }
  };

  element.querySelector<HTMLButtonElement>('[data-action="new-folder"]')!.addEventListener('click', () => {
    createForm.hidden = !createForm.hidden;
    if (!createForm.hidden) createForm.querySelector('input')!.focus();
  });
  element.querySelector<HTMLButtonElement>('[data-action="cancel-create"]')!.addEventListener('click', () => {
    createForm.hidden = true;
    createForm.reset();
  });
  createForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const input = createForm.querySelector<HTMLInputElement>('input')!;
    const name = input.value.trim();
    if (!name) return;
    try {
      const folder = await api<LibraryFolder>(
        'api/v1/folders',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, parent_id: selectedId ?? null, official: official && !selectedId }),
        },
        csrfToken(),
      );
      selectedId = folder.id;
      createForm.hidden = true;
      createForm.reset();
      await changed();
    } catch (error) {
      report(error, '无法创建文件夹');
    }
  });

  const uploadFiles = async (dropped: File[]) => {
    if (!selectedId) {
      showWallToast('请先选择或新建一个文件夹', 'info');
      return;
    }
    // Filter to the formats the server accepts so a stray HEIC/PDF drop fails
    // fast with a clear message instead of a generic server rejection.
    const files = dropped.filter((file) => ACCEPTED_UPLOAD_TYPES.has(file.type) || /\.(jpe?g|png|webp)$/i.test(file.name));
    const skipped = dropped.length - files.length;
    if (!files.length) {
      showWallToast(skipped ? '仅支持 JPEG、PNG、WebP 图片' : '没有可上传的图片', 'info');
      return;
    }
    statusLine.hidden = false;
    statusLine.classList.add('is-progress');
    try {
      for (const [index, file] of files.entries()) {
        const body = new FormData();
        body.append('file', file, file.name);
        const label = `正在上传 ${index + 1}/${files.length}：${file.name}`;
        const setProgress = (fraction: number) => {
          statusLine.textContent = `${label}　${Math.round(fraction * 100)}%`;
          statusLine.style.setProperty('--progress', `${Math.round(fraction * 100)}%`);
        };
        setProgress(0);
        await uploadWithProgress(`api/v1/folders/${encodeURIComponent(selectedId)}/uploads`, body, csrfToken(), setProgress);
      }
      showWallToast(skipped ? `已上传 ${files.length} 张，跳过 ${skipped} 个不支持的文件` : `已上传 ${files.length} 张图片`, 'success');
      await changed();
    } catch (error) {
      report(error, '上传失败');
    } finally {
      statusLine.hidden = true;
      statusLine.classList.remove('is-progress');
      statusLine.textContent = '';
      statusLine.style.removeProperty('--progress');
    }
  };

  fileInput.addEventListener('change', async () => {
    if (fileInput.files?.length) await uploadFiles([...fileInput.files]);
    fileInput.value = '';
  });

  // Drag-and-drop straight onto the manager, targeting the selected folder.
  let dragDepth = 0;
  element.addEventListener('dragenter', (event) => {
    if (!event.dataTransfer?.types.includes('Files')) return;
    event.preventDefault();
    dragDepth += 1;
    element.classList.add('is-drop-target');
  });
  element.addEventListener('dragover', (event) => {
    if (event.dataTransfer?.types.includes('Files')) event.preventDefault();
  });
  element.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) element.classList.remove('is-drop-target');
  });
  element.addEventListener('drop', async (event) => {
    if (!event.dataTransfer?.files.length) return;
    event.preventDefault();
    dragDepth = 0;
    element.classList.remove('is-drop-target');
    await uploadFiles([...event.dataTransfer.files]);
  });

  void reload().catch((error: unknown) => report(error, '无法加载文件夹'));
  return { element, reload };
}
