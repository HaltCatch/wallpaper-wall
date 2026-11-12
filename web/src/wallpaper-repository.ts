import { loadCatalog } from './catalog';
import type { Catalog, Wallpaper } from './types';
import { loadUserWallpapers } from './user-wallpapers';

/** Combines the immutable administrator catalogue with ACL-filtered user
 * content behind one page-facing data source. */
export class WallpaperRepository {
  private catalog: Catalog;
  private userWallpapers: Wallpaper[];

  private constructor(catalog: Catalog, userWallpapers: Wallpaper[]) {
    this.catalog = catalog;
    this.userWallpapers = userWallpapers;
  }

  static async load(): Promise<WallpaperRepository> {
    const [catalog, userWallpapers] = await Promise.all([
      loadCatalog(),
      loadUserWallpapers().catch(() => []),
    ]);
    return new WallpaperRepository(catalog, userWallpapers);
  }

  get catalogCount(): number {
    return this.catalog.count;
  }

  all(): Wallpaper[] {
    return [...this.catalog.wallpapers, ...this.userWallpapers];
  }

  find(id: string | null): Wallpaper | undefined {
    return id ? this.all().find((wallpaper) => wallpaper.id === id) : undefined;
  }

  /** Re-fetch both sources after a library or visibility-policy change. */
  async refresh(): Promise<void> {
    const [catalog, userWallpapers] = await Promise.all([
      loadCatalog().catch(() => this.catalog),
      loadUserWallpapers().catch(() => this.userWallpapers),
    ]);
    this.catalog = catalog;
    this.userWallpapers = userWallpapers;
  }

  async refreshUserWallpapers(): Promise<void> {
    this.userWallpapers = await loadUserWallpapers();
  }
}
