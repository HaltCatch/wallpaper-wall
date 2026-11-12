/** Generic centered modal: one overlay + backdrop + panel, closed by the
 * backdrop, the Escape key or `close()`. All dialog surfaces (login, 管理中心)
 * share this shell so stacking, focus and dismissal behave consistently. */

export interface Modal {
  overlay: HTMLElement;
  panel: HTMLElement;
  open: () => void;
  close: () => void;
  isOpen: () => boolean;
}

export function createModal(className: string, label: string): Modal {
  const overlay = document.createElement('div');
  overlay.className = `modal-overlay ${className}`;
  const backdrop = document.createElement('div');
  backdrop.className = 'modal-backdrop';
  const panel = document.createElement('section');
  panel.className = 'modal-panel';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-label', label);
  overlay.append(backdrop, panel);
  document.body.append(overlay);

  const onKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') close();
  };
  const open = () => {
    overlay.classList.add('is-open');
    document.addEventListener('keydown', onKeydown);
  };
  const close = () => {
    overlay.classList.remove('is-open');
    document.removeEventListener('keydown', onKeydown);
  };
  backdrop.addEventListener('click', close);
  return { overlay, panel, open, close, isOpen: () => overlay.classList.contains('is-open') };
}

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Style the confirm button as destructive. */
  danger?: boolean;
}

/** In-app replacement for window.confirm, styled like the rest of the dialogs.
 * Resolves true on confirm, false on cancel / backdrop / Escape. */
export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    const modal = createModal('confirm-dialog', options.title);
    modal.panel.innerHTML = `
      <h3 class="confirm-title"></h3>
      <p class="confirm-message"></p>
      <div class="confirm-actions">
        <button type="button" class="auth-secondary" data-action="cancel"></button>
        <button type="button" class="confirm-accept" data-action="ok"></button>
      </div>`;
    // Titles and messages can contain user-provided folder names, so assign
    // them as text rather than through innerHTML.
    modal.panel.querySelector('.confirm-title')!.textContent = options.title;
    modal.panel.querySelector('.confirm-message')!.textContent = options.message;
    const cancel = modal.panel.querySelector<HTMLButtonElement>('[data-action="cancel"]')!;
    const accept = modal.panel.querySelector<HTMLButtonElement>('[data-action="ok"]')!;
    cancel.textContent = options.cancelLabel ?? '取消';
    accept.textContent = options.confirmLabel ?? '确定';
    accept.classList.toggle('is-danger', Boolean(options.danger));

    let settled = false;
    const settle = (result: boolean) => {
      if (settled) return;
      settled = true;
      modal.close();
      window.setTimeout(() => modal.overlay.remove(), 220);
      resolve(result);
    };
    accept.addEventListener('click', () => settle(true));
    cancel.addEventListener('click', () => settle(false));
    // The shared shell closes on backdrop click / Escape; treat those as cancel.
    modal.overlay.querySelector('.modal-backdrop')!.addEventListener('click', () => settle(false));
    modal.overlay.addEventListener('keydown', (event) => {
      if ((event as KeyboardEvent).key === 'Escape') settle(false);
    });
    modal.open();
    accept.focus();
  });
}

export function closeButton(label: string): HTMLButtonElement {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'modal-close';
  button.setAttribute('aria-label', label);
  button.textContent = '×';
  return button;
}
