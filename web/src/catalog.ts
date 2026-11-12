import type { Catalog, IndexStatus } from './types';

export async function loadCatalog(): Promise<Catalog> {
  // The catalogue is served by the API so the administrator's mounted-folder
  // visibility policy is applied per session; the static file is not exposed.
  const response = await fetch('api/v1/catalog', { credentials: 'same-origin' });
  if (!response.ok) throw new Error('无法加载壁纸目录');
  return response.json();
}

export interface IndexBuildWatch {
  /** Whether the catalog currently rendered on the page has any wallpapers. */
  hasContent: () => boolean;
  /** Called once when a first-time build reports permanent failure. */
  onFailed: () => void;
}

/**
 * Poll the build status the container maintains. Reload once a rebuild
 * publishes a fresh catalog. An empty library also reports "ready", so a
 * reload must additionally be gated on the catalog gaining content —
 * reloading on "ready" alone would loop forever.
 */
export function watchIndexBuild({ hasContent, onFailed }: IndexBuildWatch): void {
  let sawBuilding = false;
  const poll = window.setInterval(() => {
    void (async () => {
      try {
        const response = await fetch('public/index-status.json', { cache: 'no-store' });
        if (!response.ok) {
          if (hasContent()) window.clearInterval(poll);
          return;
        }
        const status: IndexStatus = await response.json();
        if (status.state === 'building') sawBuilding = true;
        if (status.state === 'failed' && !hasContent()) {
          onFailed();
          return;
        }
        if (status.state === 'ready') {
          if (sawBuilding) {
            location.reload();
            return;
          }
          if (!hasContent()) {
            // Keep polling so a rebuild after adding images is still noticed.
            const fresh = await fetch('api/v1/catalog', { cache: 'no-store', credentials: 'same-origin' });
            if (fresh.ok && ((await fresh.json()) as Catalog).count) location.reload();
          } else {
            window.clearInterval(poll);
          }
        }
      } catch {
        // The next poll will retry; a first index should not make the wall noisy.
      }
    })();
  }, 2_500);
}
