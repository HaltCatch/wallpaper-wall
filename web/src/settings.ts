import { appRoot, encodePath } from './paths';
import type { Settings, Wallpaper } from './types';

let settingsPromise: Promise<Settings> | undefined;

export function getSettings(): Promise<Settings> {
  settingsPromise ??= fetch(new URL('public/settings.json', appRoot()))
    .then((response): Promise<Settings> | Settings => (response.ok ? response.json() : {}))
    .catch((): Settings => ({}));
  return settingsPromise;
}

/** Absolute source-image URL: the configured CDN base, or this server. */
export async function publicImageUrl(source: string): Promise<string> {
  const settings = await getSettings();
  const base = String(settings.publicImageBaseUrl ?? '').trim().replace(/\/+$/, '');
  const path = encodePath(source);
  return base ? `${base}/${path}` : new URL(path, appRoot()).href;
}

/** Android application id of the wallpaper receiver (mobile/android). Chrome
 * for Android silently drops navigations to bare custom schemes, so the deep
 * link must be delivered through an `intent://` URI that names the package. */
const ANDROID_AGENT_PACKAGE = 'local.wallpaperwall.android';

export function isAndroid(): boolean {
  return /Android/i.test(navigator.userAgent || '');
}

/** Where a wallpaper should be applied. Chosen on the web so the native helper
 * can apply it directly without popping its own picker. */
export type WallpaperTarget = 'home' | 'lock' | 'both';

/** Deep link handled by the native wallpaper agent.
 *
 * Desktop (Windows / macOS / Linux) browsers hand a plain `wallpaperwall://`
 * URL straight to the registered protocol handler, so those platforms keep the
 * exact behaviour they already had. Android is the exception: navigating to a
 * custom scheme via `location.href` there does nothing (net::ERR_UNKNOWN_URL_
 * SCHEME), so the same parameters are wrapped in an `intent://` URI that pins
 * the receiver package and falls back to the download page when it is not yet
 * installed. */
export async function setWallpaperUrl(item: Wallpaper, source: string, target?: WallpaperTarget): Promise<string> {
  const settings = await getSettings();
  const scheme = String(settings.agentScheme ?? 'wallpaperwall').replace(/[^a-z0-9+.-]/gi, '') || 'wallpaperwall';
  const params = new URLSearchParams({
    id: item.id,
    title: item.title,
    source: await publicImageUrl(source),
  });
  // A target chosen on the web lets the Android helper apply the wallpaper
  // straight away instead of showing its own home/lock/both picker.
  if (target) params.set('target', target);
  if (isAndroid()) {
    // If the app is missing, send the visitor to the assistant download page
    // instead of failing with a browser error.
    const fallback = encodeURIComponent(new URL('public/downloads/README.html', appRoot()).href);
    return `intent://set?${params}#Intent;scheme=${scheme};package=${ANDROID_AGENT_PACKAGE};S.browser_fallback_url=${fallback};end`;
  }
  return `${scheme}://set?${params}`;
}

export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    window.prompt('复制图片链接', text);
  }
}
