"""Processed takes on disk (M4-1, S3a): trim sidecars, the cache, one render per key.

``media/takes_fx/<key16>.wav`` is the processed take for one (raw take, stretch,
processing spec) key (rule 3: same key, same file, never rendered twice).
``media/takes_fx/<raw stem>.trim.json`` keeps the trim bounds of a raw take, so the
timeline can learn how long a processed take plays without decoding it each time.
Everything in ``takes_fx`` can be re-created; raw takes are only read (rule 1).
"""

import contextlib
import json
import os
import threading
from pathlib import Path

import soundfile

from backend.audio.render import ProcessError, read_mono, render_processed
from backend.audio.trim import (
    TrimBounds,
    bounds_from_data,
    bounds_to_data,
    find_speech_bounds_in_region,
    manual_cuts_from_spec,
    manual_region,
    sidecar_name,
)
from backend.project.schema import STRETCH_MAX, STRETCH_MIN
from backend.voice.keys import processed_key, processed_name
from backend.voice.stretchrender import FX_DIR_NAME

_CACHE_LIMIT = 2048


def fx_dir(raw_path: Path) -> Path:
    """``media/takes_fx`` beside the ``media/takes_raw`` folder of ``raw_path``."""
    return raw_path.parent.parent / FX_DIR_NAME


def sidecar_path(raw_path: Path) -> Path:
    return fx_dir(raw_path) / sidecar_name(raw_path.stem)


def processed_path(
    raw_path: Path, raw_key: str, stretch: float, spec: dict[str, object]
) -> Path:
    """Where the processed take for these inputs lives (it may not exist yet)."""
    _check_stretch(stretch)
    try:
        key = processed_key(raw_key=raw_key, stretch=stretch, spec=spec)
    except (TypeError, ValueError) as exc:
        raise ProcessError(f"cannot key the processed take: {exc}") from exc
    return fx_dir(raw_path) / processed_name(key)


# --- trim bounds -----------------------------------------------------------------


CacheKey = tuple[str, int, int, int | None, int | None]


class TrimCache:
    """In-memory trim bounds keyed by file path, size, modification time and the
    manual cut points they were measured with."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[CacheKey, TrimBounds] = {}

    def get(self, key: CacheKey) -> TrimBounds | None:
        with self._lock:
            return self._items.get(key)

    def put(self, key: CacheKey, bounds: TrimBounds) -> None:
        with self._lock:
            if len(self._items) >= _CACHE_LIMIT:
                self._items.clear()
            self._items[key] = bounds


def measure_bounds(
    raw_path: Path,
    manual_start_ms: int | None = None,
    manual_end_ms: int | None = None,
) -> TrimBounds:
    """Decode a raw take and find where its speech starts and ends, inside the
    manual cut points when there are any (M5-0: the manual cut is the outer step)."""
    samples, rate = read_mono(raw_path)
    try:
        start, end = manual_region(int(samples.size), rate, manual_start_ms, manual_end_ms)
        return find_speech_bounds_in_region(samples, rate, start, end)
    except ValueError as exc:
        raise ProcessError(f"cannot measure {raw_path.name}: {exc}") from exc


def trim_bounds_for(
    raw_path: Path,
    cache: TrimCache | None = None,
    *,
    manual_start_ms: int | None = None,
    manual_end_ms: int | None = None,
) -> TrimBounds:
    """Trim bounds of a raw take: memory cache, then the sidecar, then measuring.

    A sidecar is used only when it is newer than the take, matches its length and
    sample rate and was made with the current trim settings and the same manual cut
    points. Writing a fresh sidecar is best effort: failing to write it never fails
    the caller.
    """
    try:
        stat = raw_path.stat()
    except OSError as exc:
        raise ProcessError(f"take file not found: {raw_path.name}") from exc
    key = (str(raw_path), stat.st_size, stat.st_mtime_ns, manual_start_ms, manual_end_ms)
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            return hit
    bounds = _read_sidecar(raw_path, stat.st_mtime_ns, manual_start_ms, manual_end_ms)
    if bounds is None:
        bounds = measure_bounds(raw_path, manual_start_ms, manual_end_ms)
        _write_sidecar(raw_path, bounds, manual_start_ms, manual_end_ms)
    if cache is not None:
        cache.put(key, bounds)
    return bounds


def _read_sidecar(
    raw_path: Path,
    raw_mtime_ns: int,
    manual_start_ms: int | None,
    manual_end_ms: int | None,
) -> TrimBounds | None:
    side = sidecar_path(raw_path)
    try:
        if side.stat().st_mtime_ns < raw_mtime_ns:
            return None
        data = json.loads(side.read_text(encoding="utf-8"))
        info = soundfile.info(str(raw_path))
    except (OSError, ValueError, RuntimeError):
        return None
    bounds = bounds_from_data(
        data,
        expect_total=int(info.frames),
        expect_manual_start_ms=manual_start_ms,
        expect_manual_end_ms=manual_end_ms,
    )
    if bounds is None or bounds.sample_rate != int(info.samplerate):
        return None
    return bounds


def _write_sidecar(
    raw_path: Path,
    bounds: TrimBounds,
    manual_start_ms: int | None,
    manual_end_ms: int | None,
) -> None:
    side = sidecar_path(raw_path)
    tmp = side.with_name(f"{side.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        side.parent.mkdir(parents=True, exist_ok=True)
        data = bounds_to_data(
            bounds, manual_start_ms=manual_start_ms, manual_end_ms=manual_end_ms
        )
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, side)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)


# --- the processed file ----------------------------------------------------------

_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(name: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(name, threading.Lock())


def _check_stretch(stretch: float) -> None:
    if not STRETCH_MIN <= stretch <= STRETCH_MAX:  # also false for NaN
        raise ProcessError(
            f"stretch must be between {STRETCH_MIN} and {STRETCH_MAX}"
        )


def ensure_processed(
    raw_path: Path,
    raw_key: str,
    stretch: float,
    spec: dict[str, object],
    *,
    cache: TrimCache | None = None,
) -> Path:
    """Path of the processed take, rendering it first when it does not exist yet.

    An existing file is reused as is (rule 3) and its modification time is
    refreshed, so clean-up sees it as recently used. Two threads asking for the
    same file render it once; the second waits and then reuses the result.
    ``spec`` is the take's own spec (``spec_with_manual_trim``): its manual cut
    points decide the trim bounds.
    """
    dest = processed_path(raw_path, raw_key, stretch, spec)
    if dest.is_file():
        _touch(dest)
        return dest
    with _lock_for(str(dest)):
        if dest.is_file():
            return dest
        try:
            start_ms, end_ms = manual_cuts_from_spec(spec)
        except ValueError as exc:
            raise ProcessError(f"bad manual trim in the processing spec: {exc}") from exc
        bounds = trim_bounds_for(
            raw_path, cache, manual_start_ms=start_ms, manual_end_ms=end_ms
        )
        render_processed(raw_path, dest, spec, stretch, bounds)
    return dest


def _touch(path: Path) -> None:
    with contextlib.suppress(OSError):
        os.utime(path)
