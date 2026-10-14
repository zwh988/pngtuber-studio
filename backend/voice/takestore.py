"""Take files on disk (M3-4): atomic writes, copies, sizes, deletes.

The thin I/O edge for ``media/takes_raw/``. All decisions live in ``takes.py``.
Raw takes are written as mono float32 WAV (M3 decision), replaced atomically
(temp file, then ``os.replace``), so a crash never leaves a half-written take under
its real name.
"""

import os
import shutil
from collections.abc import Collection
from pathlib import Path

import numpy as np
import soundfile

from backend.voice.takes import RAW_DIR, TakeError

WAV_SUBTYPE = "FLOAT"  # 32-bit float, as the worker produces it (no quantization)


class TakeStore:
    def __init__(self, project_folder: Path) -> None:
        self._folder = Path(project_folder)

    def path(self, rel: str) -> Path:
        """Disk path of a take file; only paths inside ``media/takes_raw/``."""
        if not rel.startswith(f"{RAW_DIR}/") or ".." in rel.split("/"):
            raise TakeError(f"take files live in {RAW_DIR}/, not {rel!r}")
        return self._folder / rel

    def write_raw(self, rel: str, samples: np.ndarray, sample_rate: int) -> int:
        """Write mono float samples to ``rel`` atomically. Returns duration in ms."""
        array = np.asarray(samples, dtype=np.float32)
        if array.ndim != 1 or array.size == 0:
            raise TakeError("take audio must be a non-empty 1-D mono array")
        if sample_rate <= 0:
            raise TakeError("sample_rate must be positive")
        if not np.all(np.isfinite(array)):
            raise TakeError("take audio contains NaN or infinite values")
        dest = self.path(rel)
        tmp = dest.with_name(dest.name + ".tmp")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                soundfile.write(
                    str(tmp), array, sample_rate, subtype=WAV_SUBTYPE, format="WAV"
                )
                os.replace(tmp, dest)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
        except (OSError, RuntimeError) as exc:
            raise TakeError(f"cannot write take file {rel}: {exc}") from exc
        return round(array.size * 1000 / sample_rate)

    def copy_raw(self, source_rel: str, dest_rel: str) -> None:
        """Copy one take file to another name, atomically."""
        source = self.path(source_rel)
        dest = self.path(dest_rel)
        tmp = dest.with_name(dest.name + ".tmp")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(source, tmp)
                os.replace(tmp, dest)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise TakeError(f"cannot copy take file {source_rel}: {exc}") from exc

    def size(self, rel: str) -> int | None:
        """Size in bytes, or None when the file is missing or unreadable."""
        try:
            path = self.path(rel)
            return path.stat().st_size if path.is_file() else None
        except (OSError, TakeError):
            return None

    def unreferenced(self, referenced: Collection[str]) -> dict[str, int]:
        """Files in ``media/takes_raw/`` that are not in ``referenced``."""
        known = set(referenced)
        folder = self._folder / RAW_DIR
        found: dict[str, int] = {}
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            return found
        for entry in entries:
            rel = f"{RAW_DIR}/{entry.name}"
            if rel in known:
                continue
            try:
                if entry.is_file():
                    found[rel] = entry.stat().st_size
            except OSError:
                continue
        return found

    def delete_files(self, rels: Collection[str]) -> list[str]:
        """Delete files. A file that is already gone counts as deleted. Returns
        the files that could not be deleted."""
        failed: list[str] = []
        for rel in rels:
            try:
                self.path(rel).unlink(missing_ok=True)
            except (OSError, TakeError):
                failed.append(rel)
        return failed
