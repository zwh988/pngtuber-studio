"""Reference clip I/O (M3-1): decode, hash, copy into the project.

The checks themselves are pure and live in ``backend/voice/profile.py``. This
module is the thin edge that touches files. Rule 2 does not apply here: the
reference clip is not footage, so it is copied into ``media/voice/``.
"""

import hashlib
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import soundfile

from backend.voice.profile import (
    VOICE_DIR,
    AudioInfo,
    check_reference,
    reference_filename,
    reference_relpath,
)


class VoiceProfileError(Exception):
    """A reference clip could not be read, checked or imported."""


AudioInfoFn = Callable[[Path], AudioInfo]

_CHUNK = 1024 * 1024


def read_audio_info(path: Path) -> AudioInfo:
    """Decode the header of an audio file (no full decode)."""
    try:
        info = soundfile.info(str(path))
    except (RuntimeError, OSError) as exc:
        raise VoiceProfileError(f"cannot decode {path.name}: {exc}") from exc
    if info.samplerate <= 0:
        raise VoiceProfileError(f"{path.name} has no valid sample rate")
    return AudioInfo(
        duration_ms=round(info.frames * 1000 / info.samplerate),
        sample_rate=info.samplerate,
        channels=info.channels,
    )


def hash_file(path: Path) -> str:
    """SHA-256 of the file bytes, lowercase hex."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class FileHashCache:
    """Remembers file hashes in memory, keyed by path, size and mtime."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[int, int, str]] = {}

    def digest(self, path: Path) -> str:
        stat = path.stat()
        key = str(path)
        cached = self._entries.get(key)
        if cached is not None and cached[:2] == (stat.st_size, stat.st_mtime_ns):
            return cached[2]
        value = hash_file(path)
        self._entries[key] = (stat.st_size, stat.st_mtime_ns, value)
        return value


@dataclass(frozen=True)
class ImportedReference:
    rel_path: str  # relative POSIX path inside the project
    digest: str
    warnings: tuple[str, ...]


def import_reference(
    project_folder: Path,
    source: Path,
    *,
    audio_info: AudioInfoFn = read_audio_info,
    hashes: FileHashCache | None = None,
) -> ImportedReference:
    """Check a clip and copy it to ``media/voice/<stem>-<hash8><ext>``.

    The source is never changed. Importing the same file again reuses the copy.
    Raises ``VoiceProfileError`` for anything the user must fix.
    """
    cache = hashes if hashes is not None else FileHashCache()
    info = audio_info(source)
    check = check_reference(info)
    if not check.ok:
        raise VoiceProfileError(f"{source.name}: " + "; ".join(check.problems))
    try:
        digest = cache.digest(source)
        filename = reference_filename(source.name, digest)
    except ValueError as exc:
        raise VoiceProfileError(str(exc)) from exc
    except OSError as exc:
        raise VoiceProfileError(f"cannot read {source.name}: {exc}") from exc

    folder = project_folder / VOICE_DIR
    dest = folder / filename
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if not (dest.is_file() and dest.stat().st_size == source.stat().st_size):
            tmp = dest.with_name(dest.name + ".tmp")
            try:
                shutil.copyfile(source, tmp)
                os.replace(tmp, dest)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
    except OSError as exc:
        raise VoiceProfileError(
            f"cannot copy {source.name} into the project: {exc}"
        ) from exc
    return ImportedReference(
        rel_path=reference_relpath(filename),
        digest=digest,
        warnings=check.warnings,
    )
