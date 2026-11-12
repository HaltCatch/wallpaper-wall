"""Request DTOs.  Validation of shape and format lives here; authorization
and business rules live in the repository and services."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, field_validator

FOLDER_VISIBILITIES = ("private", "authenticated", "public")


def _validate_folder_name(value: str) -> str:
    normalized = value.strip()
    if not normalized or "/" in normalized:
        raise ValueError("文件夹名称不能为空或包含斜杠")
    return normalized


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: str | None = None
    official: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _validate_folder_name(value)


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    visibility: str | None = None
    inherit_acl: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return None if value is None else _validate_folder_name(value)

    @field_validator("visibility")
    @classmethod
    def validate_visibility(cls, value: str | None) -> str | None:
        if value is not None and value not in FOLDER_VISIBILITIES:
            raise ValueError("未知可见性")
        return value


class GrantReplace(BaseModel):
    identifiers: list[str] = Field(default_factory=list, max_length=100)


class FavoriteMerge(BaseModel):
    wallpaper_ids: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(default_factory=list, max_length=5_000)


class LocalCredentials(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=256)
    # Only consulted when the deployment sets WALLPAPER_INVITE_CODES; ignored
    # for login and when registration is open.
    invite_code: str | None = Field(default=None, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3 or any(not (character.isascii() and (character.isalnum() or character in "_.-")) for character in normalized):
            raise ValueError("用户名只能使用字母、数字、点、下划线或连字符")
        return normalized


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=6, max_length=256)
