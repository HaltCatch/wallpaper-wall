"""Safe, bounded image ingestion and derivative generation."""

from __future__ import annotations

import hashlib
import logging
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import Settings
from .repository import MediaAsset, Repository
from .storage import StorageRouter


Image.MAX_IMAGE_PIXELS = 80_000_000
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
logger = logging.getLogger(__name__)


class UploadError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _image_info(path: Path) -> tuple[str, int, int]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            mime_type = Image.MIME.get(image.format or "", "")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise UploadError("上传文件不是受支持的有效图片") from error
    if not mime_type or mime_type not in ALLOWED_MIME_TYPES:
        raise UploadError("仅支持 JPEG、PNG 和 WebP 图片")
    if width < 1 or height < 1:
        raise UploadError("图片尺寸无效")
    if width * height > 80_000_000:
        raise UploadError("图片像素总量超过 8000 万限制")
    return mime_type, width, height


def _write_thumbnail(source: Path, target: Path, bound: int) -> tuple[int, int]:
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        image.thumbnail((bound, bound), Image.Resampling.LANCZOS)
        if image.mode == "RGBA":
            canvas = Image.new("RGB", image.size, "#101114")
            canvas.paste(image, mask=image.getchannel("A"))
            image = canvas
        image.save(target, "WEBP", quality=82, method=4)
        return image.size


class UploadService:
    def __init__(self, settings: Settings, repository: Repository, storage: StorageRouter) -> None:
        self.settings = settings
        self.repository = repository
        # New uploads always target the configured driver; the upload row
        # records it so reads and deletes stay correct after a driver switch.
        self.storage = storage.active

    def ingest(self, upload: dict[str, object], stream: BinaryIO) -> dict[str, object]:
        """Persist, inspect and publish one image variant.

        The temporary file lives on the same local data volume in both storage
        modes. This lets the server inspect bytes before an object becomes
        visible in S3 and keeps validation behaviour identical.
        """
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.settings.data_dir, prefix="upload-") as temp_dir:
            temp = Path(temp_dir)
            original = temp / "original"
            total = 0
            with original.open("wb") as target:
                while chunk := stream.read(1024 * 1024):
                    total += len(chunk)
                    if total > self.settings.upload_max_bytes:
                        raise UploadError("图片超过上传大小限制")
                    target.write(chunk)
            if total == 0:
                raise UploadError("不能上传空文件")
            mime_type, width, height = _image_info(original)
            digest = _sha256(original)
            object_key = str(upload["object_key"])
            original_asset = MediaAsset(object_key, str(upload["original_name"]), mime_type, total, width, height, digest, "original")
            derivatives: list[tuple[MediaAsset, Path]] = []
            key_parent = PurePosixPath(object_key).parent
            for kind, bound in (("thumbnail", 1280), ("thumbnail_small", 640)):
                target = temp / f"{kind}.webp"
                thumb_width, thumb_height = _write_thumbnail(original, target, bound)
                key = str(key_parent / f"{digest[:16]}-{kind}.webp")
                derivatives.append((MediaAsset(key, f"{kind}.webp", "image/webp", target.stat().st_size, thumb_width, thumb_height, _sha256(target), kind), target))
            uploaded_keys: list[str] = []
            self.repository.update_upload_state(str(upload["id"]), "processing")
            try:
                self.storage.put_file(object_key, original, mime_type)
                uploaded_keys.append(object_key)
                for asset, source in derivatives:
                    self.storage.put_file(asset.object_key, source, asset.mime_type)
                    uploaded_keys.append(asset.object_key)
                wallpaper = self.repository.publish_user_upload(upload, original_asset, [asset for asset, _ in derivatives], self.settings.user_storage_quota_bytes)
            except Exception:
                for key in reversed(uploaded_keys):
                    try:
                        self.storage.delete(key)
                    except Exception:
                        # The upload remains failed and can be reconciled from
                        # its opaque key prefix without corrupting DB state.
                        logger.exception("failed to roll back uploaded object %s", key)
                raise
        return wallpaper
