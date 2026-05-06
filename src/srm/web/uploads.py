"""Local file uploads helper (offline-friendly).

We store files under `config.uploads_dir` and serve them via `/uploads` mount.
"""

from __future__ import annotations

import imghdr
import re
import secrets
from pathlib import Path

from fastapi import UploadFile


class UploadError(ValueError):
    """Raised when upload payload is invalid."""


_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def save_image_upload(
    upload: UploadFile,
    *,
    uploads_dir: Path,
    subdir: str,
    stem: str,
    max_bytes: int = 8 * 1024 * 1024,
) -> str:
    """Save an uploaded image and return a relative path (POSIX-style)."""

    filename = (upload.filename or "upload").strip()
    ext = Path(filename).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise UploadError("Разрешены только изображения: .jpg/.jpeg/.png/.webp")

    ctype = (upload.content_type or "").strip().lower()
    if ctype and ctype not in {"image/jpeg", "image/png", "image/webp"}:
        raise UploadError("Недопустимый тип файла (MIME). Разрешены только изображения.")

    content = upload.file.read()
    if content is None or len(content) == 0:
        raise UploadError("Пустой файл.")
    if len(content) > max_bytes:
        raise UploadError("Файл слишком большой.")

    # Basic signature validation to reduce risk of spoofed extensions/MIME.
    detected = imghdr.what(None, h=content)
    if detected not in {"jpeg", "png", "webp"}:
        raise UploadError("Файл не похож на изображение (проверка сигнатуры).")
    if ext in {".jpg", ".jpeg"} and detected != "jpeg":
        raise UploadError("Расширение файла не соответствует содержимому (ожидался JPEG).")
    if ext == ".png" and detected != "png":
        raise UploadError("Расширение файла не соответствует содержимому (ожидался PNG).")
    if ext == ".webp" and detected != "webp":
        raise UploadError("Расширение файла не соответствует содержимому (ожидался WebP).")

    safe_stem = _SAFE_NAME_RE.sub("_", stem.strip())[:80] or "file"
    token = secrets.token_hex(4)
    rel = Path(subdir) / f"{safe_stem}-{token}{ext}"
    dest = uploads_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    # Always store URL-friendly path.
    return rel.as_posix()
