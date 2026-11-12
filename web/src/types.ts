/** Shapes produced by scripts/build_catalog.py (catalog version 2). */

export interface Variant {
  name: string;
  source: string;
  width: number;
  height: number;
  bytes: number;
  label: string;
}

export interface Wallpaper {
  id: string;
  title: string;
  folder: string;
  collection: string;
  width: number;
  height: number;
  thumbnail: string;
  /** 640px variant for typical wall densities; absent in older catalogs. */
  thumbnailSmall?: string;
  preview: string;
  /** Darkened 2560px WebP derivative used only for the global Homepage background. */
  homepage?: string;
  placeholder?: string;
  /** Sort timestamp (epoch seconds): newest source file for system wallpapers,
   * upload time for user wallpapers. Absent in older catalogs. */
  mtime?: number;
  primary: Variant;
  variants: Variant[];
}

export interface Catalog {
  version: number;
  count: number;
  wallpapers: Wallpaper[];
}

/** public/settings.json, written by docker/entrypoint.sh from the environment. */
export interface Settings {
  publicImageBaseUrl?: string;
  agentScheme?: string;
  assistantDownloadsBaseUrl?: string;
}

/** public/index-status.json, maintained by docker/entrypoint.sh. */
export interface IndexStatus {
  state: 'building' | 'ready' | 'failed';
}
