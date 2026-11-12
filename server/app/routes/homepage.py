"""Administrator-controlled Homepage background synchronization."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Literal
from uuid import uuid4
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..deps import AdminUser, CsrfUser, ServicesDep, public_base_url

router = APIRouter(prefix="/api/v1/homepage-wallpaper", tags=["homepage-wallpaper"])


class HomepageWallpaperUpdate(BaseModel):
    wallpaper_id: str = Field(min_length=1, max_length=256)
    variant_source: str = Field(min_length=1, max_length=2048)


class HomepageAppearanceUpdate(BaseModel):
    """Bounded wallpaper and Liquid Glass material controls."""

    preset: Literal["clear", "regular", "prominent"]
    dim_opacity: float = Field(ge=0, le=0.6)
    blur_px: float = Field(ge=0, le=20)
    saturation: float = Field(ge=0.6, le=1)
    card_blur_px: float = Field(default=6, ge=0, le=20)
    card_opacity: float = Field(default=0, ge=0, le=0.6)
    card_saturation: float = Field(default=1.4, ge=0.6, le=2)
    card_refraction: float = Field(default=70, ge=0, le=100)


class HomepagePresetCreate(HomepageAppearanceUpdate):
    name: str = Field(min_length=1, max_length=64)
    expected_image_url: str = Field(min_length=1, max_length=2048)


def _image_url(request: Request, services: ServicesDep, source: str) -> str:
    # The catalogue always uses relative paths. Quote every segment to avoid a
    # user-controlled path becoming a query, fragment, or a second origin.
    if not source.startswith("public/homepage/") or ".." in source.split("/"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="该壁纸没有可用的 Homepage 优化版本")
    base = services.settings.public_image_base_url or public_base_url(request)
    return f"{base}/{quote(source, safe='/')}"


def _signature(secret: str, method: str, request_path: str, body: bytes, timestamp: str) -> str:
    digest = hashlib.sha256(body).hexdigest()
    signed = f"{method}\n{request_path}\n{timestamp}\n{digest}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def _require_main_target(target_id: str) -> None:
    if target_id != "main":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未知 Homepage 目标")


def _sync_url(services: ServicesDep, request_path: str) -> str:
    return f"{services.settings.homepage_sync_url.rstrip('/')}{request_path}"


def _trusted_put(services: ServicesDep, request_path: str, body: bytes) -> dict[str, object]:
    timestamp = str(int(time.time()))
    try:
        response = httpx.put(
            _sync_url(services, request_path),
            content=body,
            headers={
                "content-type": "application/json",
                "x-homepage-wallpaper-timestamp": timestamp,
                "x-homepage-wallpaper-request-id": str(uuid4()),
                "x-homepage-wallpaper-signature": _signature(services.settings.homepage_sync_secret, "PUT", request_path, body, timestamp),
            },
            timeout=5.0,
        )
    except httpx.HTTPError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Homepage 同步服务不可达") from error
    if request_path == "/internal/wallpaper/presets" and response.status_code in (404, 409, 422):
        messages = {"preset-name-exists": "这个预设名称已存在，请换一个名字", "wallpaper-changed": "Homepage 图片已经改变，请重新打开外观编辑器后保存", "preset-limit": "最多保存 50 个预设，请先在 Homepage 删除不需要的预设", "invalid-preset": "预设名称或参数无效"}
        raise HTTPException(status_code=response.status_code, detail=messages.get(response.json().get("error"), "预设保存失败，请重新打开编辑器后重试"))
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Homepage 同步服务拒绝了更新")
    state = response.json()
    return state if isinstance(state, dict) else {}


@router.put("/{target_id}")
def set_homepage_wallpaper(target_id: str, payload: HomepageWallpaperUpdate, request: Request, services: ServicesDep, user: CsrfUser) -> dict[str, object]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    _require_main_target(target_id)
    if not services.settings.homepage_sync_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Homepage 壁纸同步尚未配置")

    resolved = services.system_catalog.public_wallpaper_variant(payload.wallpaper_id, payload.variant_source)
    if not resolved:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="只能将已生成优化版本的公开系统图库壁纸设为 Homepage 背景")

    body = json.dumps(
        {
            "target": target_id,
            "wallpaperId": payload.wallpaper_id,
            "variantSource": payload.variant_source,
            "imageUrl": _image_url(request, services, resolved["homepage"]),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return {"ok": True, "state": _trusted_put(services, "/internal/wallpaper", body)}


@router.get("/{target_id}")
def get_homepage_wallpaper(target_id: str, services: ServicesDep, _: AdminUser) -> dict[str, object]:
    """Return the authoritative current global state to the admin UI only."""

    _require_main_target(target_id)
    if not services.settings.homepage_sync_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Homepage 壁纸同步尚未配置")
    try:
        response = httpx.get(_sync_url(services, "/api/hp-wallpaper/current"), timeout=5.0)
    except httpx.HTTPError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Homepage 同步服务不可达") from error
    if response.status_code != status.HTTP_200_OK:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Homepage 尚未设置背景")
    state = response.json()
    return {"ok": True, "state": state}


@router.put("/{target_id}/appearance")
def set_homepage_appearance(target_id: str, payload: HomepageAppearanceUpdate, services: ServicesDep, user: CsrfUser) -> dict[str, object]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    _require_main_target(target_id)
    if not services.settings.homepage_sync_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Homepage 壁纸同步尚未配置")
    body = json.dumps(
        {
            "target": target_id,
            "appearance": {
                "preset": payload.preset,
                "dimOpacity": payload.dim_opacity,
                "blurPx": payload.blur_px,
                "saturation": payload.saturation,
                **({"cardBlurPx": payload.card_blur_px} if "card_blur_px" in payload.model_fields_set else {}),
                **({"cardOpacity": payload.card_opacity} if "card_opacity" in payload.model_fields_set else {}),
                **({"cardSaturation": payload.card_saturation} if "card_saturation" in payload.model_fields_set else {}),
                **({"cardRefraction": payload.card_refraction} if "card_refraction" in payload.model_fields_set else {}),
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return {"ok": True, "state": _trusted_put(services, "/internal/wallpaper/appearance", body)}


@router.post("/{target_id}/presets")
def save_homepage_preset(target_id: str, payload: HomepagePresetCreate, services: ServicesDep, user: CsrfUser) -> dict[str, object]:
    """Save the current trusted image and the editor's complete parameter draft.

    This does not apply a draft or change the global image/revision. The peer
    verifies the expected image to avoid saving a different concurrent choice.
    """
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    _require_main_target(target_id)
    if not services.settings.homepage_sync_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Homepage 壁纸同步尚未配置")
    body = json.dumps({"target": target_id, "name": payload.name, "expectedImageUrl": payload.expected_image_url, "appearance": {
        "preset": payload.preset, "dimOpacity": payload.dim_opacity, "blurPx": payload.blur_px, "saturation": payload.saturation,
        "cardBlurPx": payload.card_blur_px, "cardOpacity": payload.card_opacity, "cardSaturation": payload.card_saturation, "cardRefraction": payload.card_refraction,
    }}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"ok": True, **_trusted_put(services, "/internal/wallpaper/presets", body)}
