"""Build an incremental wallpaper catalogue and lightweight web derivatives.

Source images remain untouched in ./images. The generated files in ./public are
safe to delete and recreate at any time.
"""

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "images"
PUBLIC = Path(os.environ.get("WALLPAPER_PUBLIC_DIR", ROOT / "public")).resolve()
THUMB_DIR = PUBLIC / "thumbs"
HOMEPAGE_DIR = PUBLIC / "homepage"
CACHE_FILE = PUBLIC / ".catalog-cache.json"
CATALOG_FILE = PUBLIC / "catalog.json"
MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".avif"}
HOMEPAGE_BOUND = (2560, 1440)
HOMEPAGE_TARGET_BYTES = 220 * 1024
HOMEPAGE_DERIVATIVE_VERSION = "homepage-v2-neutral-2560-webp"


def source_key(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def stable_id(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def image_info(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def aspect_label(width: int, height: int, original_name: str) -> str:
    ratio = width / height
    named = original_name.lower()
    if "电脑" in named:
        return f"电脑 · {width}×{height}"
    if "手机" in named:
        return f"手机 · {width}×{height}"
    if "ipad" in named or "平板" in named:
        return f"平板 · {width}×{height}"
    if ratio >= 1.2:
        return f"横屏 · {width}×{height}"
    if ratio <= 0.83:
        return f"竖屏 · {width}×{height}"
    return f"方形 · {width}×{height}"


def primary_sort_key(item: dict) -> tuple[int, int, int, str]:
    """The homepage must show exactly the largest source in one media folder."""
    pixels = item["width"] * item["height"]
    return pixels, item["width"], item["height"], item["name"]


def make_thumbnail(source_name: str, target_name: str, size: int) -> str:
    """Decode once and produce one wall thumbnail at the requested bound."""
    source = Path(source_name)
    target = Path(target_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        if image.mode == "RGBA":
            canvas = Image.new("RGB", image.size, "#101114")
            canvas.paste(image, mask=image.getchannel("A"))
            image = canvas
        image.save(target, "WEBP", quality=82, method=4)
    return target_name


def make_homepage_background(source_name: str, target_name: str) -> str:
    """Produce a small, visually neutral desktop background for Homepage.

    Homepage's original bundled image is a 2560px WebP of about 166 KiB.  The
    system gallery deliberately keeps its lossless originals, so this separate
    derivative gives clients a similarly quick first paint without changing a
    user's downloadable asset.  It deliberately does *not* bake in brightness
    or saturation changes: contrast belongs to one runtime scrim behind the
    dashboard, so white and colourful wallpapers retain their source character.
    """
    source = Path(source_name)
    target = Path(target_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode == "RGBA":
            canvas = Image.new("RGB", image.size, "#101114")
            canvas.paste(image, mask=image.getchannel("A"))
            image = canvas
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.thumbnail(HOMEPAGE_BOUND, Image.Resampling.LANCZOS)
        # Most 16:9 wallpapers reach roughly the original 166 KiB at q55.
        # Some detailed illustrations need a little more data, capped at a
        # still-small 220 KiB before quality is reduced further.
        for quality in (60, 55, 50, 45):
            image.save(target, "WEBP", quality=quality, method=4)
            if target.stat().st_size <= HOMEPAGE_TARGET_BYTES:
                break
    return target_name


def load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {}
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def previous_homepage_names() -> set[str]:
    """Keep one catalogue generation of immutable Homepage assets as a grace.

    A deployed Homepage can still reference the previous content-addressed URL
    until its trusted sync update arrives. Retaining names from the immediately
    preceding catalogue prevents a transient 404 during that hand-off.
    """
    if not CATALOG_FILE.exists():
        return set()
    try:
        catalog = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    names = set()
    for wallpaper in catalog.get("wallpapers", []):
        homepage = wallpaper.get("homepage") if isinstance(wallpaper, dict) else None
        if isinstance(homepage, str) and homepage.startswith("public/homepage/"):
            names.add(Path(homepage).name)
    return names


FALLBACK_PLACEHOLDER = "#171b25"


def thumbnail_color(path: Path) -> str:
    try:
        with Image.open(path) as image:
            red, green, blue = image.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    except (OSError, ValueError):
        # A missing or failed thumbnail must not take the whole catalog down;
        # the tile simply keeps the neutral placeholder colour.
        return FALLBACK_PLACEHOLDER
    # Slightly darkened so the image fading in never flashes a bright rectangle.
    return f"#{red * 72 // 100:02x}{green * 72 // 100:02x}{blue * 72 // 100:02x}"


def direct_media_folders() -> list[tuple[Path, list[Path]]]:
    folders: list[tuple[Path, list[Path]]] = []
    for directory in SOURCE.rglob("*"):
        if not directory.is_dir():
            continue
        files = sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS)
        if files:
            folders.append((directory, files))
    return folders


def grouped_variants(files: list[Path]) -> dict[str, list[Path]]:
    """Use the filesystem as the only grouping signal.

    One directory containing images is exactly one wallpaper. Every file in
    that directory is a selectable version, regardless of its filename. This
    keeps the catalog stable when files are renamed or new exports are added.
    """
    return {"__folder__": list(files)}


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit("images directory is missing")

    PUBLIC.mkdir(exist_ok=True)
    HOMEPAGE_DIR.mkdir(exist_ok=True)
    cache = load_cache()
    previous_homepage = previous_homepage_names()
    next_cache: dict[str, dict] = {}
    wallpapers: list[dict] = []
    pending: list[tuple[str, str, int]] = []
    homepage_pending: list[tuple[str, str]] = []

    root_strays = [path for path in SOURCE.iterdir() if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS]
    if root_strays:
        print(f"warning: {len(root_strays)} image(s) directly inside images/ are ignored; each wallpaper needs its own folder")

    for folder, files in direct_media_folders():
        folder_key = folder.relative_to(SOURCE).as_posix()
        groups = grouped_variants(files)
        for group_key, group_files in sorted(groups.items()):
            variants = []
            latest_mtime = 0.0
            for path in group_files:
                key = source_key(path)
                stat = path.stat()
                latest_mtime = max(latest_mtime, stat.st_mtime)
                fingerprint = f"{stat.st_size}:{stat.st_mtime_ns}"
                cached = cache.get(key, {})
                if cached.get("fingerprint") == fingerprint:
                    width, height = cached["width"], cached["height"]
                else:
                    try:
                        width, height = image_info(path)
                    except OSError as error:
                        # One unreadable file must not abort the whole build.
                        print(f"warning: skipping unreadable image {key}: {error}")
                        continue
                next_cache[key] = {"fingerprint": fingerprint, "width": width, "height": height}
                variants.append({
                    "name": path.name,
                    "source": key,
                    "width": width,
                    "height": height,
                    "bytes": stat.st_size,
                    "label": aspect_label(width, height, path.name),
                })

            if not variants:
                continue
            primary = max(variants, key=primary_sort_key)
            homepage_candidates = [item for item in variants if item["width"] / item["height"] >= 1.2]
            homepage_variant = max(homepage_candidates, key=primary_sort_key) if homepage_candidates else None
            # Folder path is the sole identity. Filenames never decide whether
            # an image appears as a new wallpaper or a selectable variant.
            item_key = folder_key
            wallpaper_id = stable_id(item_key)
            primary_path = ROOT / primary["source"]
            primary_cache = next_cache[primary["source"]]
            # The content fingerprint is part of the file name, so the thumbs
            # location can be served as immutable: a changed source image gets a
            # new URL instead of silently replacing a long-cached one.
            # Two bounds are produced: 1280 for large cards and the preview
            # first paint, 640 for typical wall densities. The browser picks
            # the smallest sufficient one via srcset, which cuts the decoded-
            # bitmap memory of the wall roughly fourfold with no visual loss.
            def derivative_name(version: str) -> str:
                fingerprint = f"{primary_cache['fingerprint']}:{version}"
                return f"{wallpaper_id}-{stable_id(fingerprint)[:10]}.webp"

            thumb_name = derivative_name("thumb-v7-fingerprint-named-1280-q82")
            small_name = derivative_name("thumb-v7-small-640-q82")
            for name, size in ((thumb_name, 1280), (small_name, 640)):
                if not (THUMB_DIR / name).exists():
                    pending.append((str(primary_path), str(THUMB_DIR / name), size))
            homepage = None
            if homepage_variant:
                homepage_source = homepage_variant["source"]
                homepage_cache = next_cache[homepage_source]
                homepage_fingerprint = f"{homepage_cache['fingerprint']}:{HOMEPAGE_DERIVATIVE_VERSION}"
                homepage_name = f"{wallpaper_id}-{stable_id(homepage_fingerprint)[:10]}.webp"
                if not (HOMEPAGE_DIR / homepage_name).exists():
                    homepage_pending.append((str(ROOT / homepage_source), str(HOMEPAGE_DIR / homepage_name)))
                homepage = f"public/homepage/{homepage_name}"
            wallpapers.append({
                "id": wallpaper_id,
                "title": folder.name,
                "folder": folder_key,
                "collection": folder.relative_to(SOURCE).parent.as_posix(),
                "width": primary["width"],
                "height": primary["height"],
                "thumbnail": f"public/thumbs/{thumb_name}",
                "thumbnailSmall": f"public/thumbs/{small_name}",
                "preview": f"public/thumbs/{thumb_name}",
                "homepage": homepage,
                "_homepage_path": str(HOMEPAGE_DIR / homepage_name) if homepage else None,
                # Newest-first sorting uses the most recently modified source
                # file in the folder (epoch seconds); the wall reads it directly.
                "mtime": int(latest_mtime),
                "primary": primary,
                "variants": sorted(variants, key=primary_sort_key, reverse=True),
            })

    jobs = min(8, max(1, os.cpu_count() or 1))
    failures = 0
    generated = 0
    if pending or homepage_pending:
        print(f"thumbnail jobs: {len(pending)}; Homepage jobs: {len(homepage_pending)} using {jobs} workers")
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(make_thumbnail, source, target, size): source for source, target, size in pending}
            futures.update({pool.submit(make_homepage_background, source, target): source for source, target in homepage_pending})
            for index, future in enumerate(as_completed(futures), 1):
                try:
                    future.result()
                    generated += 1
                except Exception as error:
                    failures += 1
                    print(f"warning: thumbnail failed for {futures[future]}: {error}")
                if index % 25 == 0 or index == len(futures):
                    print(f"thumbnail progress: {index}/{len(futures)}")

    for wallpaper in wallpapers:
        wallpaper["placeholder"] = thumbnail_color(THUMB_DIR / Path(wallpaper["thumbnailSmall"]).name)
        generated_homepage = wallpaper.pop("_homepage_path", None)
        if generated_homepage and Path(generated_homepage).is_file():
            # Homepage appearance is a single administrator-controlled global
            # setting, not a per-image classifier. The derivative is neutral.
            wallpaper.pop("homepageMaterial", None)
        else:
            # A failed derivative must never be published as a broken global
            # background URL. The sync endpoint will reject this item safely.
            wallpaper["homepage"] = None

    wallpapers.sort(key=lambda item: (item["collection"], item["title"]))
    # Readers may be serving the previous complete catalog while this process is
    # running.  Replace both files atomically so no browser receives a partial
    # JSON document.
    catalog_tmp = CATALOG_FILE.with_suffix(".json.tmp")
    cache_tmp = CACHE_FILE.with_suffix(".json.tmp")
    catalog_tmp.write_text(json.dumps({"version": 2, "count": len(wallpapers), "wallpapers": wallpapers}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    cache_tmp.write_text(json.dumps(next_cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    catalog_tmp.replace(CATALOG_FILE)
    cache_tmp.replace(CACHE_FILE)

    # Only after the new catalog is live may thumbnails that no wallpaper
    # references any more (deleted folders, superseded fingerprints) go away.
    expected_thumbs = {Path(wallpaper[key]).name for wallpaper in wallpapers for key in ("thumbnail", "thumbnailSmall")}
    if THUMB_DIR.exists():
        for candidate in THUMB_DIR.iterdir():
            if candidate.is_file() and candidate.name not in expected_thumbs:
                candidate.unlink(missing_ok=True)

    expected_homepage = {Path(wallpaper["homepage"]).name for wallpaper in wallpapers if wallpaper.get("homepage")} | previous_homepage
    if HOMEPAGE_DIR.exists():
        for candidate in HOMEPAGE_DIR.iterdir():
            if candidate.is_file() and candidate.name not in expected_homepage:
                candidate.unlink(missing_ok=True)

    print(f"catalog: {len(wallpapers)} wallpapers; generated derivatives: {generated}; failed derivatives: {failures}")


if __name__ == "__main__":
    main()
