"""Object storage ports and adapters.

User files use opaque keys.  Display names never form a filesystem path or a
bucket key, preventing traversal bugs and making local/S3 behaviour identical.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .config import Settings
from .filenames import content_disposition


class StorageBackend(ABC):
    #: Whether media(): should redirect the browser to a signed URL (S3-style)
    #: instead of streaming bytes through the API (local volume).
    supports_signed_urls: bool = False

    @abstractmethod
    def put_file(self, key: str, source: Path, content_type: str) -> None: ...

    @abstractmethod
    def open(self, key: str) -> BinaryIO: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def signed_download_url(self, key: str, filename: str, expires_seconds: int) -> str: ...


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if self.root.resolve() not in candidate.parents:
            raise ValueError("invalid object key")
        return candidate

    def put_file(self, key: str, source: Path, content_type: str) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def open(self, key: str) -> BinaryIO:
        return self._path(key).open("rb")

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def signed_download_url(self, key: str, filename: str, expires_seconds: int) -> str:
        # Local files are served only after API authorization; this is a stable
        # internal marker, never a browser-facing signed URL.
        raise NotImplementedError("local media is served by the API")


class S3StorageBackend(StorageBackend):
    supports_signed_urls = True

    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"}),
        )

    def put_file(self, key: str, source: Path, content_type: str) -> None:
        self.client.upload_file(str(source), self.bucket, key, ExtraArgs={"ContentType": content_type})

    def open(self, key: str) -> BinaryIO:
        # Streaming through the API is intentionally avoided for S3; callers
        # must use a signed redirect after authorization.
        raise NotImplementedError("S3 media is served with signed redirects")

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    def signed_download_url(self, key: str, filename: str, expires_seconds: int) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": content_disposition(filename),
            },
            ExpiresIn=expires_seconds,
        )


class StorageRouter:
    """Routes each object to the backend that actually holds it.

    New uploads always go to the configured (active) driver, while reads and
    deletes use the driver recorded on the object row.  This is what makes
    switching WALLPAPER_STORAGE_DRIVER between local and S3 safe: media
    uploaded before the switch keeps serving from its original backend.
    """

    def __init__(self, active_driver: str, backends: dict[str, StorageBackend]) -> None:
        self.active_driver = active_driver
        self._backends = backends

    @property
    def active(self) -> StorageBackend:
        return self._backends[self.active_driver]

    def for_driver(self, driver: str) -> StorageBackend:
        backend = self._backends.get(driver or "local")
        if backend is None:
            raise LookupError(
                f"object was stored with driver '{driver}' but that backend is not configured; "
                "restore the matching WALLPAPER_S3_* settings to serve it"
            )
        return backend


def create_storage(settings: Settings) -> StorageRouter:
    # The local backend always exists (its directory is on the data volume);
    # the S3 backend is constructed whenever credentials are present so media
    # uploaded under a previous driver remains reachable after a switch.
    backends: dict[str, StorageBackend] = {"local": LocalStorageBackend(settings.uploads_dir)}
    if settings.s3_bucket and settings.s3_access_key and settings.s3_secret_key:
        backends["s3"] = S3StorageBackend(settings)
    return StorageRouter(settings.storage_driver, backends)
