"""Importing music and sound effects for the audio lanes (M8-1).

A dropped file is copied into the project's ``audio/`` folder (decision 1,
2026-11-20): the copy is what the project uses, and the original is never
touched. Dropping the same file again (same name and size) reuses the copy.
Each copy is decoded once with ffmpeg to a 48 kHz 16-bit WAV in
``media/audio_decoded/<file id>.wav``; preview, waveform peaks and export all
read that WAV, so they hear the same samples (rule 5). The decoded WAV can be
made again at any time.

Pure parts: ``AUDIO_EXTENSIONS``, ``is_audio_file``, ``parse_audio_probe``,
``copy_name``, ``find_reuse``, ``decode_args``.
I/O parts: ``copy_into_project``, ``decode_to_wav``, ``ensure_decoded``,
``import_audio_file``.
"""

import math
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import soundfile as sf
from pydantic import BaseModel, Field

from backend.project.schema import AudioFile, new_id
from backend.project.timeline import TimelineState

AUDIO_DIR = "audio"
DECODED_DIR = "media/audio_decoded"
DECODED_RATE = 48_000
AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".flac", ".ogg", ".m4a"})

Probe = Callable[[Path], dict[str, Any]]
# (source, dest, channels): writes the decoded WAV to ``dest``.
Decode = Callable[[Path, Path, int], None]


class AudioImportError(Exception):
    """A dropped file cannot be used; the message is for the user."""


class AudioImportRequest(BaseModel):
    """Files dropped on the timeline (full paths from the pywebview drop handler)."""

    paths: list[str] = Field(min_length=1, max_length=50)
    # The lane under the drop point; None: the first lane.
    lane_id: str | None = None
    timeline_ms: int = Field(ge=0)
    # True: dropped on "+ Audio lane", so the files go on a new lane below the last.
    new_lane: bool = False


class ImportedAudio(BaseModel):
    name: str
    clip_id: str
    lane_id: str
    lane_name: str
    timeline_ms: int
    # True when the file was already in the project and nothing was copied.
    reused: bool


class AudioImportResult(BaseModel):
    imported: list[ImportedAudio] = Field(default_factory=list)
    # One sentence per file that could not be imported (the others still are).
    errors: list[str] = Field(default_factory=list)
    timeline: TimelineState


@dataclass(frozen=True)
class AudioProbe:
    duration_ms: int
    sample_rate: int
    channels: int


# --------------------------------------------------------------------------
# Pure
# --------------------------------------------------------------------------


def is_audio_file(name: str) -> bool:
    return PurePosixPath(name.replace("\\", "/")).suffix.lower() in AUDIO_EXTENSIONS


def parse_audio_probe(data: dict[str, Any], name: str) -> AudioProbe:
    """The first audio stream of ffprobe JSON (``-show_streams -show_format``)."""
    streams = data.get("streams")
    if not isinstance(streams, list):
        raise AudioImportError(f"{name}: ffprobe found no streams")
    stream = next(
        (s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"),
        None,
    )
    if stream is None:
        raise AudioImportError(f"{name}: the file has no sound")
    try:
        rate = int(stream.get("sample_rate", 0))
        channels = int(stream.get("channels", 0))
    except (TypeError, ValueError) as exc:
        raise AudioImportError(f"{name}: unreadable audio format") from exc
    duration_ms = None
    for candidate in (stream.get("duration"), data.get("format", {}).get("duration")):
        try:
            seconds = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(seconds) and seconds > 0:
            duration_ms = round(seconds * 1000)
            break
    if rate <= 0 or channels <= 0 or not duration_ms:
        raise AudioImportError(f"{name}: unreadable audio format")
    return AudioProbe(duration_ms=duration_ms, sample_rate=rate, channels=channels)


def copy_name(original: str, taken: Iterable[str]) -> str:
    """A file name for ``audio/`` that no other file uses (case-insensitive).

    ``song.mp3``, then ``song (2).mp3``, ``song (3).mp3`` ...
    """
    used = {name.casefold() for name in taken}
    path = PurePosixPath(original)
    stem, suffix = path.stem, path.suffix
    candidate = original
    number = 2
    while candidate.casefold() in used:
        candidate = f"{stem} ({number}){suffix}"
        number += 1
    return candidate


def find_reuse(
    known: Sequence[AudioFile], name: str, size_bytes: int
) -> AudioFile | None:
    """An already imported file with the same original name and size."""
    key = name.casefold()
    for audio_file in known:
        if audio_file.name.casefold() == key and audio_file.size_bytes == size_bytes:
            return audio_file
    return None


def decode_args(ffmpeg: Path, source: Path, dest: Path, channels: int) -> list[str]:
    """ffmpeg arguments for the decoded WAV: 48 kHz, 16-bit, mono or stereo."""
    return [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1" if channels == 1 else "2",
        "-ar",
        str(DECODED_RATE),
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        str(dest),
    ]


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------


def decoded_path(project_folder: Path, file_id: str) -> Path:
    return project_folder / DECODED_DIR / f"{file_id}.wav"


def copy_into_project(project_folder: Path, source: Path, name: str) -> Path:
    """Copy ``source`` to ``audio/<name>`` (temp file, then rename)."""
    folder = project_folder / AUDIO_DIR
    dest = folder / name
    folder.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        shutil.copyfile(source, tmp)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dest


def make_ffmpeg_decoder(ffmpeg: Path) -> Decode:
    """A ``Decode`` that runs ffmpeg (argument list, no console window)."""

    def decode(source: Path, dest: Path, channels: int) -> None:
        if not ffmpeg.is_file():
            raise AudioImportError(
                f"ffmpeg not found at {ffmpeg}. Run install.bat again to download it."
            )
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            result = subprocess.run(
                decode_args(ffmpeg, source, dest, channels),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
                check=False,
                creationflags=flags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AudioImportError(f"{source.name}: could not decode: {exc}") from exc
        if result.returncode != 0:
            detail = result.stderr.strip().splitlines()[-1:] or [
                f"exit {result.returncode}"
            ]
            raise AudioImportError(f"{source.name}: could not decode: {detail[0]}")

    return decode


_decode_lock = threading.Lock()


def ensure_decoded(project_folder: Path, audio_file: AudioFile, decode: Decode) -> Path:
    """The decoded WAV of ``audio_file``, made now when it is missing."""
    return _ensure_decoded(
        project_folder / audio_file.path,
        decoded_path(project_folder, audio_file.id),
        audio_file.channels,
        decode,
    )


def _ensure_decoded(source: Path, dest: Path, channels: int, decode: Decode) -> Path:
    with _decode_lock:
        if dest.is_file():
            return dest
        if not source.is_file():
            raise AudioImportError(f"{source.name} is missing from the project")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.stem + ".tmp.wav")
        try:
            decode(source, tmp, channels)
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
    return dest


def decoded_duration_ms(path: Path) -> int:
    info = sf.info(str(path))
    return round(info.frames * 1000 / info.samplerate)


def import_audio_file(
    project_folder: Path,
    source: Path,
    known: Sequence[AudioFile],
    *,
    probe: Probe,
    decode: Decode,
) -> tuple[AudioFile, bool]:
    """Bring one dropped file into the project.

    Returns the ``AudioFile`` to use and whether it was already in the project
    (``True``: nothing to register). A new ``AudioFile`` still has to be added
    with the ``AddAudioFile`` command. A copy left in ``audio/`` by an undone
    import (same name and size) is used again instead of copied twice.
    """
    name = source.name
    if not is_audio_file(name):
        raise AudioImportError(
            f"{name}: not a supported audio file (WAV, MP3, FLAC, OGG or M4A)"
        )
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise AudioImportError(f"{name}: cannot read the file: {exc}") from exc
    existing = find_reuse(known, name, size)
    if existing is not None:
        ensure_decoded(project_folder, existing, decode)
        return existing, True

    folder = project_folder / AUDIO_DIR
    on_disk = folder / name
    taken = [PurePosixPath(f.path).name for f in known]
    copied = False
    if (
        name.casefold() not in {t.casefold() for t in taken}
        and on_disk.is_file()
        and on_disk.stat().st_size == size
    ):
        dest = on_disk  # left by an undone import
    else:
        if folder.is_dir():
            taken += [p.name for p in folder.iterdir()]
        try:
            dest = copy_into_project(project_folder, source, copy_name(name, taken))
        except OSError as exc:
            raise AudioImportError(
                f"{name}: cannot copy it into the project: {exc}"
            ) from exc
        copied = True
    file_id = new_id()
    decoded = decoded_path(project_folder, file_id)
    try:
        try:
            info = parse_audio_probe(probe(dest), name)
        except AudioImportError:
            raise
        except Exception as exc:  # ffprobe missing or failed
            raise AudioImportError(str(exc)) from exc
        _ensure_decoded(dest, decoded, info.channels, decode)
        duration_ms = decoded_duration_ms(decoded)
        if duration_ms <= 0:
            raise AudioImportError(f"{name}: the file has no sound")
    except BaseException:
        # A file that cannot be used leaves nothing behind.
        decoded.unlink(missing_ok=True)
        if copied:
            dest.unlink(missing_ok=True)
        raise
    audio_file = AudioFile(
        id=file_id,
        path=f"{AUDIO_DIR}/{dest.name}",
        name=name,
        size_bytes=size,
        # The decoded WAV's length: what preview and export play (ffprobe's
        # duration of an MP3 can be an estimate).
        duration_ms=duration_ms,
        sample_rate=info.sample_rate,
        channels=info.channels,
    )
    return audio_file, False
