"""Folder management: personal libraries and the admin-run official library."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from ..deps import CsrfUser, RequiredUser, ServicesDep, limit_upload_attempt
from ..filenames import safe_filename
from ..repository import QuotaExceededError
from ..schemas import FolderCreate, FolderUpdate, GrantReplace
from ..uploads import UploadError

router = APIRouter(prefix="/api/v1/folders", tags=["folders"])


def _folder_dto(folder: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": folder["id"],
        "parent_id": folder["parent_id"],
        "name": folder["name"],
        "visibility": folder["visibility"],
        "inherit_acl": bool(folder["inherit_acl"]),
        "official": bool(folder["is_official"]),
    }


@router.get("")
def list_folders(services: ServicesDep, user: RequiredUser) -> dict[str, list[dict[str, Any]]]:
    payload = {"folders": [_folder_dto(folder) for folder in services.repository.list_personal_folders(user["id"])]}
    if user.get("role") == "admin":
        payload["official"] = [_folder_dto(folder) for folder in services.repository.list_official_folders()]
    return payload


@router.post("", status_code=status.HTTP_201_CREATED)
def create_folder(payload: FolderCreate, services: ServicesDep, user: CsrfUser) -> dict[str, Any]:
    try:
        folder = services.repository.create_folder(
            user["id"], payload.name, payload.parent_id, official=payload.official, is_admin=user.get("role") == "admin"
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail="无权在此位置创建文件夹") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _folder_dto(folder)


@router.patch("/{folder_id}")
def update_folder(folder_id: str, payload: FolderUpdate, services: ServicesDep, user: CsrfUser) -> dict[str, Any]:
    try:
        folder = services.repository.update_folder(folder_id, user["id"], payload.name, payload.visibility, payload.inherit_acl)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return _folder_dto(folder)


@router.delete("/{folder_id}")
def delete_folder(folder_id: str, services: ServicesDep, user: CsrfUser) -> dict[str, bool]:
    try:
        deleted = services.repository.delete_folder(folder_id, user["id"])
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not deleted:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return {"ok": True}


@router.delete("/{folder_id}/wallpaper")
def clear_folder_wallpaper(folder_id: str, services: ServicesDep, user: CsrfUser) -> dict[str, int | bool]:
    try:
        deleted_objects = services.library_service.clear_folder(folder_id, user["id"])
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="文件夹不存在") from error
    return {"ok": True, "deletedObjects": deleted_objects}


@router.get("/{folder_id}/grants")
def folder_grants(folder_id: str, services: ServicesDep, user: RequiredUser) -> dict[str, list[dict[str, Any]]]:
    if not services.repository.get_managed_folder(folder_id, user["id"]):
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return {"grants": services.repository.list_grants(folder_id, user["id"])}


@router.put("/{folder_id}/grants")
def replace_grants(folder_id: str, payload: GrantReplace, services: ServicesDep, user: CsrfUser) -> dict[str, bool]:
    try:
        services.repository.replace_grants_by_identifiers(folder_id, user["id"], payload.identifiers)
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="文件夹不存在") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"ok": True}


@router.post("/{folder_id}/uploads", status_code=status.HTTP_201_CREATED)
async def upload(folder_id: str, services: ServicesDep, user: CsrfUser, file: UploadFile = File(...)) -> dict[str, Any]:
    settings = services.settings
    limit_upload_attempt(services, user["id"])
    if not file.filename:
        raise HTTPException(status_code=422, detail="缺少文件名")
    if file.size is not None and file.size > settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="图片超过上传大小限制")
    try:
        try:
            record = services.repository.create_upload(
                folder_id, user["id"], safe_filename(file.filename), file.size, settings.user_storage_quota_bytes, storage_driver=services.storage.active_driver
            )
        except PermissionError as error:
            raise HTTPException(status_code=404, detail="文件夹不存在") from error
        except QuotaExceededError as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
        try:
            return services.upload_service.ingest(record, file.file)
        except QuotaExceededError as error:
            services.repository.update_upload_state(record["id"], "failed", str(error))
            raise HTTPException(status_code=413, detail=str(error)) from error
        except UploadError as error:
            services.repository.update_upload_state(record["id"], "failed", str(error))
            raise HTTPException(status_code=422, detail=str(error)) from error
        except PermissionError as error:
            services.repository.update_upload_state(record["id"], "failed", str(error))
            raise HTTPException(status_code=409, detail="文件夹已被删除或不可用") from error
        except Exception:
            services.repository.update_upload_state(record["id"], "failed", "存储或处理失败")
            raise
    finally:
        await file.close()
