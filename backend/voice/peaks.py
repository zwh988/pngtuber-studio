"""Waveform peaks of a take, for the voice lane (M3-7, decision 12).

Peaks are computed on demand and never stored in ``project.json``. The maths is
pure (``compute_peaks``, ``build_peaks_report``); ``read_take_peaks`` is the thin
file wrapper, with a small in-memory cache keyed by file, size and mtime.
"""

from pathlib import Path

import numpy as np
import soundfile as sf
from pydantic import BaseModel

MIN_BUCKETS = 8
MAX_BUCKETS = 4000
_CACHE_LIMIT = 64


class PeaksError(Exception):
    """A take file could not be read or the request was out of range."""


class PeaksReport(BaseModel):
    take_id: str
    duration_ms: int
    sample_rate: int
    buckets: int
    # Lowest and highest sample of each bucket, -1.0 to 1.0, left to right.
    lows: list[float]
    highs: list[float]


_cache: dict[tuple[str, int, int, int], PeaksReport] = {}


def compute_peaks(samples: np.ndarray, buckets: int) -> tuple[list[float], list[float]]:
    """Lowest and highest sample in each of ``buckets`` equal slices.

    Always returns ``buckets`` values per list. Silence and empty input give
    zeros; with fewer samples than buckets each bucket still covers one sample.
    Values are clipped to [-1, 1] and rounded to 4 decimals.
    """
    if buckets < 1:
        raise ValueError("buckets must be at least 1")
    data = np.nan_to_num(
        np.asarray(samples, dtype=np.float32).reshape(-1),
        nan=0.0,
        posinf=1.0,
        neginf=-1.0,
    )
    count = int(data.size)
    if count == 0:
        return [0.0] * buckets, [0.0] * buckets
    edges = np.linspace(0, count, buckets + 1)
    starts = np.minimum(np.floor(edges[:-1]).astype(np.int64), count - 1)
    ends = np.minimum(
        np.maximum(np.floor(edges[1:]).astype(np.int64), starts + 1), count
    )
    lows: list[float] = []
    highs: list[float] = []
    for start, end in zip(starts, ends, strict=True):
        chunk = data[int(start) : int(end)]
        lows.append(round(max(-1.0, min(1.0, float(chunk.min()))), 4))
        highs.append(round(max(-1.0, min(1.0, float(chunk.max()))), 4))
    return lows, highs


def build_peaks_report(
    take_id: str, samples: np.ndarray, sample_rate: int, buckets: int
) -> PeaksReport:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    lows, highs = compute_peaks(samples, buckets)
    frames = int(np.asarray(samples).reshape(-1).size)
    return PeaksReport(
        take_id=take_id,
        duration_ms=round(frames * 1000 / sample_rate),
        sample_rate=sample_rate,
        buckets=buckets,
        lows=lows,
        highs=highs,
    )


def read_take_peaks(path: Path, take_id: str, buckets: int) -> PeaksReport:
    """Peaks of a take WAV (channels averaged to mono). Raises ``PeaksError``."""
    if not MIN_BUCKETS <= buckets <= MAX_BUCKETS:
        raise PeaksError(f"buckets must be between {MIN_BUCKETS} and {MAX_BUCKETS}")
    try:
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns, buckets)
        cached = _cache.get(key)
        if cached is not None:
            return cached
        data, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    except (OSError, RuntimeError) as exc:
        raise PeaksError(f"cannot read take audio: {exc}") from exc
    report = build_peaks_report(take_id, data.mean(axis=1), int(sample_rate), buckets)
    if len(_cache) >= _CACHE_LIMIT:
        _cache.clear()
    _cache[key] = report
    return report
