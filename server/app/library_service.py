"""User-library mutations that coordinate SQLite metadata and object storage."""

from __future__ import annotations

import logging

from .repository import Repository
from .storage import StorageRouter


logger = logging.getLogger(__name__)


class UserLibraryService:
    def __init__(self, repository: Repository, storage: StorageRouter) -> None:
        self.repository = repository
        self.storage = storage

    def clear_folder(self, folder_id: str, owner_id: str) -> int:
        # Metadata is removed first so a failed remote delete can only leave an
        # unreachable opaque object, never an ACL bypass. S3 lifecycle rules can
        # independently reap such rare remnants.
        objects = self.repository.delete_folder_media(folder_id, owner_id)
        for key, driver in objects:
            try:
                self.storage.for_driver(driver).delete(key)
            except Exception:
                logger.exception("failed to delete orphaned object %s (driver %s)", key, driver)
        return len(objects)
