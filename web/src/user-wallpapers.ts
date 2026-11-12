import { api } from './api';
import type { Variant, Wallpaper } from './types';

interface UserWallpaperRecord {
  id: string;
  title: string;
  width: number;
  height: number;
  folder_path: string;
  owner_name: string;
  owned: boolean;
  official: boolean;
  created_at?: string;
  primary: UserMediaRecord;
  variants: UserMediaRecord[];
  thumbnail?: UserMediaRecord | null;
  thumbnail_small?: UserMediaRecord | null;
}

interface UserMediaRecord {
  media_id: string;
  mediaUrl: string;
  original_name: string;
  width: number;
  height: number;
  bytes: number;
}

/** Converts the authenticated media DTO into the same view model used by the
 * static catalogue. The UI never needs to know which storage backend served
 * a particular wallpaper. */
export function toWallpaper(record: UserWallpaperRecord): Wallpaper {
  const variants: Variant[] = record.variants.map((variant) => ({
    name: variant.original_name,
    source: variant.mediaUrl,
    width: variant.width,
    height: variant.height,
    bytes: variant.bytes,
    label: `${variant.width} × ${variant.height}`,
  }));
  const primary = variants.find((variant) => variant.source === record.primary.mediaUrl) ?? variants[0]!;
  // Official folders are the admin-run default gallery; they group by their
  // own path instead of by uploader.
  const collection = record.official ? '默认图库' : record.owned ? '我的壁纸' : '共享图库';
  const folder = record.official
    ? `默认图库/${record.folder_path}`
    : record.owned
      ? `我的壁纸/${record.folder_path}`
      : `共享图库/${record.owner_name}/${record.folder_path}`;
  return {
    id: record.id,
    title: record.title,
    folder,
    collection,
    width: record.width,
    height: record.height,
    thumbnail: record.thumbnail?.mediaUrl ?? primary.source,
    thumbnailSmall: record.thumbnail_small?.mediaUrl,
    preview: record.thumbnail?.mediaUrl ?? primary.source,
    mtime: record.created_at ? Math.floor(Date.parse(record.created_at) / 1000) || undefined : undefined,
    primary,
    variants,
  };
}

export async function loadUserWallpapers(): Promise<Wallpaper[]> {
  const response = await api<{ wallpapers: UserWallpaperRecord[] }>('api/v1/wallpapers/user');
  return response.wallpapers.map(toWallpaper);
}
