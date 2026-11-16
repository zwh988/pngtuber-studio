"""Downscaled preview sprites (M5-6 backend, decision 6). File I/O plus Pillow.

A full sprite (1179x2095 RGBA) decodes to about 10 MB in the browser, so the preview
gets copies about ``PREVIEW_HEIGHT`` pixels high in ``media/avatar_preview/``, made on
first request and re-creatable at any time. The name is a hash of the source file's
path, size, modification time and the height, so an edited sprite gets a new copy.
The export compositor (M6) uses the originals. The art itself is only read.
"""

import contextlib
import hashlib
import os
import threading
from pathlib import Path

PREVIEW_HEIGHT = 1000
PREVIEW_DIR_NAME = "avatar_preview"

_LOCKS: dict[str, threading.Lock] = {}
_GUARD = threading.Lock()


class PreviewError(Exception):
    """The preview copy could not be made."""


def preview_name(source: Path, height: int = PREVIEW_HEIGHT) -> str:
    stat = source.stat()
    blob = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}|{height}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16] + ".png"


def ensure_preview(source: Path, cache_dir: Path, height: int = PREVIEW_HEIGHT) -> Path:
    """Path of the downscaled copy of ``source``, making it first when needed. A sprite
    already at most ``height`` high is copied as is (same format, no upscaling)."""
    try:
        dest = cache_dir / preview_name(source, height)
    except OSError as exc:
        raise PreviewError(f"sprite not found: {source.name}") from exc
    if dest.is_file():
        return dest
    with _GUARD:
        lock = _LOCKS.setdefault(str(dest), threading.Lock())
    with lock:
        if dest.is_file():
            return dest
        try:
            from PIL import Image
        except ImportError as exc:
            raise PreviewError("Pillow is not installed: run `uv add pillow`") from exc
        tmp = dest.with_name(f"{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            with Image.open(source) as image:
                image.load()
                rgba = image.convert("RGBA")
                if rgba.height > height:
                    width = max(1, round(rgba.width * height / rgba.height))
                    rgba = rgba.resize((width, height), Image.Resampling.LANCZOS)
                rgba.save(tmp, format="PNG", optimize=False, compress_level=6)
            os.replace(tmp, dest)
        except (OSError, ValueError) as exc:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            raise PreviewError(f"cannot make the preview of {source.name}: {exc}") from exc
    return dest
