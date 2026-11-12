import { api } from './api';
import { assistantSection } from './agent-panel';
import { accountIcon } from './auth-modal';
import type { FavoritesStore } from './favorites';
import { createLibraryManager } from './library-manager';
import { closeButton, createModal } from './modal';
import { openHomepageAppearance } from './homepage-wallpaper';
import { createSystemFoldersBlock } from './system-folders';
import { showWallToast } from './toast';

export type HubSection = 'account' | 'library' | 'official' | 'homepage' | 'assistant';

export interface Hub {
  open: (section?: HubSection) => void;
  close: () => void;
}

/** 管理中心: one centered surface for everything that is not wall browsing —
 * account, personal library, the admin-only official library and the
 * assistant downloads. Sections are lazily built on first visit. */
export function createHub(favorites: FavoritesStore, onLibraryChanged: () => Promise<void>): Hub {
  const modal = createModal('hub', '管理中心');
  const isAdmin = favorites.role === 'admin';

  const sections: { id: HubSection; label: string; hidden?: boolean }[] = [
    { id: 'account', label: '账户' },
    { id: 'library', label: '我的图库' },
    { id: 'official', label: '默认图库', hidden: !isAdmin },
    { id: 'homepage', label: 'Homepage 外观', hidden: !isAdmin },
    { id: 'assistant', label: '壁纸助手' },
  ];

  modal.panel.innerHTML = `
    <nav class="hub-nav" aria-label="管理中心导航">
      <div class="hub-title">管理中心</div>
      ${sections
        .filter((section) => !section.hidden)
        .map((section) => `<button type="button" class="hub-nav-item" data-section="${section.id}">${section.label}</button>`)
        .join('')}
    </nav>
    <div class="hub-body"></div>`;
  modal.panel.prepend(closeButton('关闭管理中心'));
  modal.panel.querySelector<HTMLButtonElement>('.modal-close')!.addEventListener('click', modal.close);

  const body = modal.panel.querySelector<HTMLElement>('.hub-body')!;
  const navButtons = [...modal.panel.querySelectorAll<HTMLButtonElement>('.hub-nav-item')];
  const built = new Map<HubSection, HTMLElement>();

  const buildAccount = (): HTMLElement => {
    const section = document.createElement('div');
    section.className = 'hub-section';
    section.innerHTML = `
      <h3>账户</h3>
      <div class="hub-account">
        <span class="hub-account-icon">${accountIcon}</span>
        <div><strong></strong><small>${isAdmin ? '管理员' : '已登录'}</small></div>
      </div>
      <p class="hub-account-note">收藏与个人图库已同步到此账号。</p>
      ${
        favorites.isLocalAccount
          ? `<form class="hub-password" data-form="password">
               <h4>修改密码</h4>
               <input name="current" type="password" autocomplete="current-password" minlength="1" maxlength="256" required placeholder="当前密码" />
               <input name="next" type="password" autocomplete="new-password" minlength="6" maxlength="256" required placeholder="新密码（至少 6 位）" />
               <button type="submit" class="auth-secondary">更新密码</button>
             </form>`
          : ''
      }
      <div class="hub-account-actions">
        <button type="button" class="auth-secondary" data-action="logout-all">退出其他设备</button>
        <button type="button" class="auth-secondary" data-action="logout">退出登录</button>
      </div>`;
    section.querySelector('strong')!.textContent = favorites.accountName ?? '我的账户';
    const avatarUrl = favorites.avatarUrl;
    if (avatarUrl) {
      const icon = section.querySelector<HTMLElement>('.hub-account-icon')!;
      const avatar = document.createElement('img');
      avatar.className = 'hub-account-avatar';
      avatar.alt = '';
      avatar.referrerPolicy = 'no-referrer';
      avatar.src = avatarUrl;
      // A portrait that fails to load quietly reverts to the generic glyph.
      avatar.addEventListener('error', () => {
        icon.innerHTML = accountIcon;
      });
      icon.replaceChildren(avatar);
    }
    section.querySelector<HTMLButtonElement>('[data-action="logout"]')!.addEventListener('click', async () => {
      try {
        await api<void>('api/v1/auth/logout', { method: 'POST' }, favorites.csrfToken);
        location.reload();
      } catch (error) {
        showWallToast(error instanceof Error ? error.message : '退出登录失败', 'error');
      }
    });
    section.querySelector<HTMLButtonElement>('[data-action="logout-all"]')!.addEventListener('click', async () => {
      try {
        await api<void>('api/v1/auth/logout-all', { method: 'POST' }, favorites.csrfToken);
        showWallToast('已退出其他设备', 'success');
      } catch (error) {
        showWallToast(error instanceof Error ? error.message : '操作失败', 'error');
      }
    });
    const passwordForm = section.querySelector<HTMLFormElement>('[data-form="password"]');
    passwordForm?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const submit = passwordForm.querySelector<HTMLButtonElement>('button[type="submit"]')!;
      const data = new FormData(passwordForm);
      submit.disabled = true;
      try {
        await api<void>(
          'api/v1/auth/local/password',
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ current_password: data.get('current'), new_password: data.get('next') }) },
          favorites.csrfToken,
        );
        passwordForm.reset();
        showWallToast('密码已更新，其他设备需重新登录', 'success');
      } catch (error) {
        showWallToast(error instanceof Error ? error.message : '修改密码失败', 'error');
      } finally {
        submit.disabled = false;
      }
    });
    return section;
  };

  const buildLibrary = (official: boolean): HTMLElement => {
    const section = document.createElement('div');
    section.className = 'hub-section';
    const heading = document.createElement('h3');
    heading.textContent = official ? '默认图库' : '我的图库';
    section.append(heading);
    if (official) {
      // The default gallery is what visitors see without doing anything:
      // in-app official folders (local volume or S3) plus the read-only
      // mounted catalogue whose visibility is governed here.
      const inApp = document.createElement('h4');
      inApp.textContent = '站内文件夹';
      section.append(inApp);
    }
    section.append(createLibraryManager({ official, csrfToken: () => favorites.csrfToken, onChanged: onLibraryChanged }).element);
    if (official) section.append(createSystemFoldersBlock(() => favorites.csrfToken, onLibraryChanged));
    return section;
  };

  const buildAssistant = (): HTMLElement => {
    const section = document.createElement('div');
    section.className = 'hub-section';
    section.innerHTML = '<h3>壁纸助手</h3>';
    void assistantSection().then((content) => section.append(content));
    return section;
  };

  const buildHomepageAppearance = (): HTMLElement => {
    const section = document.createElement('div');
    section.className = 'hub-section hp-appearance-hub';
    section.innerHTML = `
      <h3>Homepage 外观</h3>
      <p>调整背景的压暗、虚化和饱和度，以及 Liquid Glass 卡片的虚化、底色不透明度、饱和度和折射强度。默认实时同步至全部 Homepage。</p>
      <button type="button" class="auth-primary">调整外观</button>`;
    section.querySelector<HTMLButtonElement>('button')!.addEventListener('click', () => void openHomepageAppearance());
    return section;
  };

  const builders: Record<HubSection, () => HTMLElement> = {
    account: buildAccount,
    library: () => buildLibrary(false),
    official: () => buildLibrary(true),
    homepage: buildHomepageAppearance,
    assistant: buildAssistant,
  };

  const show = (section: HubSection) => {
    if (!built.has(section)) built.set(section, builders[section]());
    body.replaceChildren(built.get(section)!);
    navButtons.forEach((button) => button.classList.toggle('is-active', button.dataset['section'] === section));
  };

  navButtons.forEach((button) => button.addEventListener('click', () => show(button.dataset['section'] as HubSection)));

  return {
    open: (section: HubSection = 'account') => {
      show(section);
      modal.open();
    },
    close: modal.close,
  };
}
