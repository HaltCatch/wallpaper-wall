import { getSettings, isAndroid, setWallpaperUrl, type WallpaperTarget } from './settings';
import { closeButton, createModal, type Modal } from './modal';
import { showWallToast } from './toast';
import type { Wallpaper } from './types';

interface AssistantPlatform {
  label: string;
  downloadLabel?: string;
  filename?: string;
  steps: string[];
}

export function assistantPlatform(): AssistantPlatform {
  const ua = navigator.userAgent || '';
  const isApplePhone = /iPad|iPhone|iPod/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  if (isApplePhone)
    return {
      label: 'iPhone / iPad',
      steps: [
        'iPhone/iPad 助手源码已随项目提供；请按完整说明用 Xcode 构建并以自己的签名安装。',
        '回到壁纸预览，点击预览里的 <b>设为壁纸</b> 按钮；图片会保存到照片，最后由 iOS 在系统界面确认设为壁纸。',
      ],
    };
  if (/Android/i.test(ua))
    return {
      label: 'Android',
      downloadLabel: '下载 Android 助手',
      filename: 'WallpaperWall-Android-Agent.apk',
      steps: [
        '下载后点击 APK 安装；系统提示未知来源时，允许浏览器安装此应用。',
        '回到壁纸预览，点击 <b>设为壁纸</b>，在网页上选择桌面 / 锁屏 / 两者；助手会在后台设置并弹出成功或失败提示，无需在应用内再操作。',
      ],
    };
  if (/Macintosh|Mac OS X/i.test(ua))
    return {
      label: 'macOS',
      downloadLabel: '下载 macOS 助手（Apple Silicon）',
      filename: 'wallpaperwall-agent',
      steps: [
        '下载后在终端执行 <code>chmod +x wallpaperwall-agent</code>，再执行 <code>./wallpaperwall-agent install</code>。',
        '首次设置时按 macOS 提示允许自动化；之后回到预览点击预览里的 <b>设为壁纸</b> 按钮即可。',
      ],
    };
  if (/Linux/i.test(ua))
    return {
      label: 'Linux',
      steps: [
        '桌面助手源码已随项目提供；在 <code>wallpaper-agent</code> 目录执行 <code>cargo build --release</code>，再执行 <code>./target/release/wallpaperwall-agent install</code>。',
        '支持 GNOME、KDE Plasma 和 Xfce；安装完成后回到预览点击预览里的 <b>设为壁纸</b> 按钮。',
      ],
    };
  return {
    label: 'Windows',
    downloadLabel: '下载 Windows 助手',
    filename: 'WallpaperWall-Agent.exe',
    steps: ['下载后双击一次安装，无需管理员权限；成功会弹出确认提示。', '回到壁纸预览，点击预览里的 <b>设为壁纸</b> 按钮即可设置。'],
  };
}

/** Assistant download instructions, rendered as embeddable content for the
 * 管理中心 rather than as a floating panel of its own. */
export async function assistantSection(): Promise<HTMLElement> {
  const platform = assistantPlatform();
  const settings = await getSettings();
  // A configured base switches to RustFS/CDN. Leaving it empty uses the
  // assistant packages baked into the website image.
  const base = String(settings.assistantDownloadsBaseUrl ?? 'public/downloads').trim().replace(/\/+$/, '');
  const download = platform.filename
    ? `<a class="agent-download" href="${base}/${encodeURIComponent(platform.filename)}" download="${platform.filename}">${platform.downloadLabel}</a>`
    : '<p class="agent-download is-unavailable">此平台不提供预构建安装包</p>';
  const content = document.createElement('div');
  content.className = 'agent-content';
  content.innerHTML = `<p>让“设为桌面壁纸”在本机完成。</p>${download}<p class="agent-platform-title">${platform.label} 安装说明</p><ol>${platform.steps.map((step) => `<li>${step}</li>`).join('')}</ol><a class="agent-readme" href="public/downloads/README.html" target="_blank" rel="noopener">查看完整说明</a>`;
  return content;
}

let helpModal: Modal | undefined;

/** Standalone assistant-install dialog. Unlike the 管理中心 (which needs a
 * signed-in session), this works on any page — including the logged-out detail
 * view — so a first-time visitor who has not installed the helper can be guided
 * to it. */
export function openAssistantHelp(note?: string): void {
  if (!helpModal) {
    helpModal = createModal('assistant-help', '安装壁纸助手');
    helpModal.panel.prepend(closeButton('关闭'));
    helpModal.panel.querySelector<HTMLButtonElement>('.modal-close')!.addEventListener('click', () => helpModal!.close());
  }
  const panel = helpModal.panel;
  panel.querySelectorAll('.assistant-help-body, .assistant-help-note').forEach((node) => node.remove());
  if (note) {
    const heading = document.createElement('p');
    heading.className = 'assistant-help-note';
    heading.textContent = note;
    panel.append(heading);
  }
  const body = document.createElement('div');
  body.className = 'assistant-help-body';
  void assistantSection().then((section) => body.append(section));
  panel.append(body);
  helpModal.open();
}

const TARGET_KEY = 'wallpaper-wall:android-target';
const TARGET_OPTIONS: { id: WallpaperTarget; label: string }[] = [
  { id: 'home', label: '桌面壁纸' },
  { id: 'lock', label: '锁屏壁纸' },
  { id: 'both', label: '桌面和锁屏' },
];

/** Ask, on the web, where the wallpaper should be applied so the Android helper
 * can set it directly. Resolves undefined when dismissed. The last pick is
 * remembered and surfaced as the highlighted option. */
function chooseAndroidTarget(): Promise<WallpaperTarget | undefined> {
  return new Promise((resolve) => {
    const modal = createModal('wp-target-dialog', '设为壁纸');
    const last = localStorage.getItem(TARGET_KEY);
    modal.panel.innerHTML = `
      <h3 class="wp-target-title">设为壁纸</h3>
      <p class="wp-target-note">选择应用位置，助手会在后台完成设置并提示结果。</p>
      <div class="wp-target-actions">
        ${TARGET_OPTIONS.map((option) => `<button type="button" class="wp-target-option${option.id === last ? ' is-preferred' : ''}" data-target="${option.id}">${option.label}</button>`).join('')}
      </div>
      <button type="button" class="auth-text-action" data-action="cancel">取消</button>`;
    let settled = false;
    const settle = (result?: WallpaperTarget) => {
      if (settled) return;
      settled = true;
      modal.close();
      window.setTimeout(() => modal.overlay.remove(), 220);
      resolve(result);
    };
    modal.panel.querySelectorAll<HTMLButtonElement>('.wp-target-option').forEach((button) => {
      button.addEventListener('click', () => {
        const target = button.dataset['target'] as WallpaperTarget;
        localStorage.setItem(TARGET_KEY, target);
        settle(target);
      });
    });
    modal.panel.querySelector<HTMLButtonElement>('[data-action="cancel"]')!.addEventListener('click', () => settle());
    modal.overlay.querySelector('.modal-backdrop')!.addEventListener('click', () => settle());
    modal.overlay.addEventListener('keydown', (event) => {
      if ((event as KeyboardEvent).key === 'Escape') settle();
    });
    modal.open();
  });
}

/** Hand the deep link to the native helper and, on desktop, notice when nothing
 * took it. A custom protocol has no success callback, so instead of claiming
 * success we watch for the tab losing focus (the helper or its confirmation
 * dialog opening). If focus never leaves within a short window the helper is
 * almost certainly not installed, and we open the install guide.
 *
 * Android is different: the target (home/lock/both) is picked here, passed in
 * the `intent://` link, and the helper applies it directly and reports back
 * with a toast — no in-app picker, no lingering screen. The intent already
 * carries a browser fallback URL for the not-installed case. */
export async function setWallpaperViaHelper(item: Wallpaper, source: string): Promise<void> {
  if (isAndroid()) {
    const target = await chooseAndroidTarget();
    if (!target) return;
    showWallToast('正在设置壁纸…', 'info', 2000);
    location.href = await setWallpaperUrl(item, source, target);
    return;
  }
  const url = await setWallpaperUrl(item, source);
  let handedOff = false;
  const markHandedOff = () => {
    handedOff = true;
  };
  window.addEventListener('blur', markHandedOff, { once: true });
  window.addEventListener('pagehide', markHandedOff, { once: true });
  document.addEventListener('visibilitychange', markHandedOff, { once: true });
  showWallToast('正在唤起壁纸助手…', 'info', 2400);
  location.href = url;
  window.setTimeout(() => {
    window.removeEventListener('blur', markHandedOff);
    window.removeEventListener('pagehide', markHandedOff);
    document.removeEventListener('visibilitychange', markHandedOff);
    // A registered handler always steals focus (the helper or its confirmation
    // dialog), firing one of the events above. If none did, nothing took the
    // link — guide the visitor to install the helper.
    if (!handedOff) {
      openAssistantHelp('没有检测到壁纸助手响应。请先按下方说明安装助手，再回到预览点击“设为壁纸”。');
    }
  }, 1500);
}
