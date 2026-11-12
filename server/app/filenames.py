"""Safe display filenames and RFC-compatible download headers."""

from __future__ import annotations

from urllib.parse import quote


def safe_filename(filename: str) -> str:
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(character for character in basename if character >= " " and character != "\x7f" and character not in {'"', ';'})
    return cleaned[:180] or "wallpaper"


def content_disposition(filename: str, disposition: str = "inline") -> str:
    safe = safe_filename(filename)
    fallback = "".join(character if character.isascii() and (character.isalnum() or character in "._-") else "_" for character in safe)
    fallback = fallback[:180] or "wallpaper"
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(safe, safe='')}"
