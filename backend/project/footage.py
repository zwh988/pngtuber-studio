"""Footage detection: ffprobe wrapper and Source construction (M1-3).

Pure parts: ``parse_rate``, ``parse_probe``, ``plan_scan``.
I/O parts: ``run_ffprobe``, ``list_footage_files``, ``scan_footage``.
Footage is only ever read, never copied or modified (CLAUDE.md rule 2).
"""

import json
import math
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.project.schema import Source, new_id

FOOTAGE_DIR = "footage"
VIDEO_EXTENSIONS = frozenset(
    {".mkv", ".mp4", ".mov", ".avi", ".webm", ".m4v", ".flv", ".ts"}
)


class FootageError(Exception):
    """Base class for footage errors."""


class FfprobeNotFoundError(FootageError):
    """ffprobe.exe is missing, so no footage can be read."""


class ProbeError(FootageError):
    """A single file could not be probed or parsed."""


# --------------------------------------------------------------------------
# Pure parsing
# --------------------------------------------------------------------------


def parse_rate(text: str) -> tuple[int, int]:
    """Parse an ffprobe rational like ``60/1`` or ``60000/1001``."""
    raw = str(text).strip()
    num_s, sep, den_s = raw.partition("/")
    try:
        num = int(num_s)
        den = int(den_s) if sep else 1
    except ValueError as exc:
        raise ProbeError(f"unreadable frame rate: {text!r}") from exc
    if num <= 0 or den <= 0:
        raise ProbeError(f"invalid frame rate: {text!r}")
    return num, den


def _video_stream(streams: Sequence[dict[str, Any]]) -> dict[str, Any]:
    for stream in streams:
        if stream.get("codec_type") != "video":
            continue
        if stream.get("disposition", {}).get("attached_pic") == 1:
            continue  # cover art, not real video
        return stream
    raise ProbeError("no video stream found")


def _frame_rate(stream: dict[str, Any]) -> tuple[int, int]:
    # avg_frame_rate is exact for constant-frame-rate files such as OBS
    # recordings; fall back to r_frame_rate when it is 0/0.
    for key in ("avg_frame_rate", "r_frame_rate"):
        value = stream.get(key)
        if value is None:
            continue
        try:
            return parse_rate(value)
        except ProbeError:
            continue
    raise ProbeError("no usable frame rate in video stream")


def _duration_ms(data: dict[str, Any], stream: dict[str, Any]) -> int:
    candidates = (data.get("format", {}).get("duration"), stream.get("duration"))
    for candidate in candidates:
        try:
            seconds = float(candidate)
        except (TypeError, ValueError):
            continue
        if math.isfinite(seconds) and seconds >= 0:
            return round(seconds * 1000)
    raise ProbeError("no duration found")


def parse_probe(
    data: dict[str, Any], rel_path: str, source_id: str | None = None
) -> Source:
    """Turn ffprobe JSON (``-show_streams -show_format``) into a Source.

    ``rel_path`` is the path relative to the project folder (POSIX style).
    """
    streams = data.get("streams")
    if not isinstance(streams, list):
        raise ProbeError(f"{rel_path}: ffprobe output has no streams list")
    try:
        video = _video_stream(streams)
        fps_num, fps_den = _frame_rate(video)
        duration_ms = _duration_ms(data, video)
    except ProbeError as exc:
        raise ProbeError(f"{rel_path}: {exc}") from exc
    audio_tracks = sum(1 for s in streams if s.get("codec_type") == "audio")
    try:
        return Source(
            id=source_id or new_id(),
            path=rel_path,
            duration_ms=duration_ms,
            fps_num=fps_num,
            fps_den=fps_den,
            width=video.get("width"),
            height=video.get("height"),
            audio_tracks=audio_tracks,
        )
    except ValidationError as exc:
        raise ProbeError(f"{rel_path}: invalid probe data: {exc}") from exc


@dataclass(frozen=True)
class ScanPlan:
    to_probe: list[str]  # files on disk with no Source yet
    present: list[Source]  # known sources whose file is on disk
    missing: list[Source]  # known sources whose file is not on disk


def plan_scan(found: Iterable[str], known: Sequence[Source]) -> ScanPlan:
    """Compare files found on disk with known Sources (case-insensitive,
    because Windows paths are)."""
    found_list = list(found)
    found_keys = {p.casefold() for p in found_list}
    known_keys = {s.path.casefold() for s in known}
    return ScanPlan(
        to_probe=[p for p in found_list if p.casefold() not in known_keys],
        present=[s for s in known if s.path.casefold() in found_keys],
        missing=[s for s in known if s.path.casefold() not in found_keys],
    )


# --------------------------------------------------------------------------
# I/O edges
# --------------------------------------------------------------------------


def default_ffprobe_path() -> Path:
    """``bin/ffprobe.exe`` at the repo root (backend/project/ -> repo root)."""
    return Path(__file__).resolve().parents[2] / "bin" / "ffprobe.exe"


def run_ffprobe(
    path: Path, ffprobe: Path | None = None, timeout_s: float = 60.0
) -> dict[str, Any]:
    """Run ffprobe on one file and return its parsed JSON."""
    exe = ffprobe or default_ffprobe_path()
    if not exe.is_file():
        raise FfprobeNotFoundError(
            f"ffprobe not found at {exe}. Download the pinned ffmpeg build "
            "(see PROJECT_STATE.md, 'ffmpeg') and copy ffprobe.exe into bin/."
        )
    cmd = [
        str(exe),
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            check=False,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(f"{path.name}: ffprobe timed out") from exc
    except OSError as exc:
        raise ProbeError(f"{path.name}: could not run ffprobe: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        raise ProbeError(f"{path.name}: ffprobe failed: {detail}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"{path.name}: ffprobe returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ProbeError(f"{path.name}: unexpected ffprobe output")
    return data


def list_footage_files(project_folder: Path) -> list[str]:
    """Video files under ``<project>/footage/`` as relative POSIX paths."""
    footage = project_folder / FOOTAGE_DIR
    if not footage.is_dir():
        return []
    found = [
        p.relative_to(project_folder).as_posix()
        for p in sorted(footage.rglob("*"))
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    return found


@dataclass
class ScanResult:
    new_sources: list[Source] = field(default_factory=list)
    present: list[Source] = field(default_factory=list)
    missing: list[Source] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (rel_path, message)


def scan_footage(
    project_folder: Path,
    known: Sequence[Source] = (),
    *,
    probe: Callable[[Path], dict[str, Any]] | None = None,
) -> ScanResult:
    """Scan ``footage/`` and build Sources for files not yet known.

    Does not modify the project: callers add ``new_sources`` through the
    command layer. Known sources keep their ids. A missing ffprobe raises
    ``FfprobeNotFoundError``; a bad single file is reported in ``errors``.
    """
    probe_fn = probe or run_ffprobe
    plan = plan_scan(list_footage_files(project_folder), known)
    result = ScanResult(present=plan.present, missing=plan.missing)
    for rel in plan.to_probe:
        try:
            result.new_sources.append(parse_probe(probe_fn(project_folder / rel), rel))
        except ProbeError as exc:
            result.errors.append((rel, str(exc)))
    return result
