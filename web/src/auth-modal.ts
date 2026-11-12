import { api } from './api';
import { externalIcon } from './icons';
import type { FavoritesStore } from './favorites';
import { closeButton, createModal, type Modal } from './modal';
import { showWallToast } from './toast';

export const accountIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3.5"/><path d="M4.5 20c.8-3.65 3.2-5.5 7.5-5.5s6.7 1.85 7.5 5.5"/></svg>';

/** Centered sign-in dialog for logged-out visitors. Account management for
 * signed-in users lives in the 管理中心 (hub) instead. */
export function createAuthModal(favorites: FavoritesStore): Modal {
  const modal = createModal('auth-modal', '登录 Wallpaper Wall');
  let mode: 'login' | 'register' = 'login';

  const render = () => {
    const panel = modal.panel;
    const localForm = favorites.localEnabled
      ? `
      <form class="auth-form" data-auth-form>
        <label>账号<input name="username" autocomplete="username" minlength="3" maxlength="32" pattern="[A-Za-z0-9_.-]+" required placeholder="用户名" /></label>
        <label>密码<input name="password" type="password" autocomplete="${mode === 'login' ? 'current-password' : 'new-password'}" minlength="6" maxlength="256" required placeholder="至少 6 位" /></label>
        ${mode === 'register' && favorites.inviteRequired ? '<label>邀请码<input name="invite_code" maxlength="128" required placeholder="请输入邀请码" /></label>' : ''}
        <button class="auth-primary" type="submit">${mode === 'login' ? '登录' : '创建账号并登录'}</button>
      </form>
      ${favorites.registrationEnabled ? `<button class="auth-text-action" type="button" data-action="switch">${mode === 'login' ? '没有账号？立即注册' : '已有账号？返回登录'}</button>` : ''}`
      : '';
    const divider = favorites.localEnabled && favorites.oidcEnabled ? '<div class="auth-divider"><span>或</span></div>' : '';
    const oidc = favorites.oidcEnabled ? `<button class="auth-oidc" type="button" data-action="oidc"><span class="auth-oidc-mark">${externalIcon}</span>使用统一身份登录</button>` : '';
    const unavailable = !favorites.localEnabled && !favorites.oidcEnabled ? '<p class="auth-disabled">管理员尚未启用账户功能。</p>' : '';
    panel.innerHTML = `
      <div class="auth-brand">
        <span class="auth-brand-icon">${accountIcon}</span>
        <h2>${mode === 'login' ? '登录 Wallpaper Wall' : '创建账号'}</h2>
        <p class="auth-subtitle">登录后可同步收藏并维护个人图库。</p>
      </div>
      ${localForm}${divider}${oidc}${unavailable}`;
    panel.prepend(closeButton('关闭登录'));
    panel.querySelector<HTMLButtonElement>('.modal-close')!.addEventListener('click', modal.close);
    panel.querySelector<HTMLButtonElement>('[data-action="switch"]')?.addEventListener('click', () => {
      mode = mode === 'login' ? 'register' : 'login';
      render();
    });
    panel.querySelector<HTMLButtonElement>('[data-action="oidc"]')?.addEventListener('click', () => {
      location.assign('api/v1/auth/login');
    });
    const form = panel.querySelector<HTMLFormElement>('[data-auth-form]');
    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const submit = form.querySelector<HTMLButtonElement>('button[type="submit"]')!;
      const data = new FormData(form);
      const username = data.get('username');
      const password = data.get('password');
      if (typeof username !== 'string' || typeof password !== 'string') return;
      const inviteCode = data.get('invite_code');
      const body: Record<string, string> = { username, password };
      if (mode === 'register' && typeof inviteCode === 'string' && inviteCode) body['invite_code'] = inviteCode;
      submit.disabled = true;
      try {
        await api<{ ok: true }>(`api/v1/auth/local/${mode === 'login' ? 'login' : 'register'}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        location.reload();
      } catch (error) {
        showWallToast(error instanceof Error ? error.message : '登录失败', 'error');
        submit.disabled = false;
      }
    });
  };

  render();
  return modal;
}
