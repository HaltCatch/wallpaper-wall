export type ToastTone = 'info' | 'success' | 'error';

let toastTimer: number | undefined;

export function showWallToast(message: string, tone: ToastTone = 'info', duration = 3600): void {
  let toast = document.querySelector<HTMLElement>('.wall-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.className = 'wall-toast';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    document.body.append(toast);
  }
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.dataset.tone = tone;
  requestAnimationFrame(() => toast.classList.add('is-visible'));
  toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), duration);
}
