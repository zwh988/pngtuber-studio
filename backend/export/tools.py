"""ffmpeg for the export (M6): where it is and whether NVENC opens (rule 14: argument lists)."""

import subprocess
import sys
import threading
from pathlib import Path

PROBE_TIMEOUT_S = 30.0

_cache: dict[Path, str | None] = {}
_cache_lock = threading.Lock()


def default_ffmpeg_path() -> Path:
    """``bin/ffmpeg.exe`` at the repo root (backend/export/ -> repo root)."""
    return Path(__file__).resolve().parents[2] / "bin" / "ffmpeg.exe"


def nvenc_probe_args(ffmpeg: Path) -> list[str]:
    """A tenth of a second of black encoded with h264_nvenc to nowhere."""
    return [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=256x144:r=30:d=0.1",
        "-c:v",
        "h264_nvenc",
        "-f",
        "null",
        "-",
    ]


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else "no output"


def encoder_problem(ffmpeg: Path | None = None, *, refresh: bool = False) -> str | None:
    """None when ffmpeg runs and opens NVENC, else a message for the pre-flight.

    The probe runs once per ffmpeg path and app run (about half a second); a failure
    is checked again each time, so installing ffmpeg needs no restart.
    """
    path = ffmpeg if ffmpeg is not None else default_ffmpeg_path()
    with _cache_lock:
        if not refresh and path in _cache:
            return _cache[path]
    if not path.is_file():
        return f"ffmpeg was not found at {path} (see PROJECT_STATE.md, How to run)."
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            nvenc_probe_args(path),
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            creationflags=flags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ffmpeg could not be run: {exc}"
    if result.returncode != 0:
        return f"NVENC (h264_nvenc) could not be opened: {_last_line(result.stderr)}"
    with _cache_lock:
        _cache[path] = None
    return None
