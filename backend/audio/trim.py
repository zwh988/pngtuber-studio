"""Silence trimming maths (M4-1): where speech starts and ends in a raw take. Pure.

Numpy only, no files and no audio library. The take is trimmed *before* any time
stretch, so these bounds depend on the raw audio alone and the length a placed line
plays for is plain arithmetic (see ``processed_duration_ms``). The bounds are cached in
a small JSON sidecar next to the processed files; ``bounds_from_data`` returns None for
a stale or damaged sidecar so the caller simply measures again.

Starting values are guesses to tune by ear. Changing one changes the processing spec
(and so every processed key), which re-renders the takes; nothing else needs to change.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import floor
from typing import Any

import numpy as np

from backend.voice.stretch import stretched_duration_ms

TRIM_THRESHOLD_DB = -45.0  # a 10 ms frame quieter than this counts as silence
TRIM_FRAME_MS = 10
TRIM_PAD_BEFORE_MS = 40  # kept before the first loud frame
TRIM_PAD_AFTER_MS = 80  # kept after the last loud frame (lets the word tail ring out)

SIDECAR_VERSION = 1


def trim_params() -> dict[str, float | int]:
    """The trim settings as plain data (part of the processing spec)."""
    return {
        "threshold_db": TRIM_THRESHOLD_DB,
        "frame_ms": TRIM_FRAME_MS,
        "pad_before_ms": TRIM_PAD_BEFORE_MS,
        "pad_after_ms": TRIM_PAD_AFTER_MS,
    }


@dataclass(frozen=True)
class TrimBounds:
    """Kept range ``[start, end)`` of a take, in samples."""

    start: int
    end: int
    total: int  # samples in the whole raw take
    sample_rate: int
    silent: bool = False  # nothing loud found: the whole take is kept

    @property
    def kept(self) -> int:
        return self.end - self.start


def _samples_for_ms(ms: float, sample_rate: int) -> int:
    return round(sample_rate * ms / 1000)


def find_speech_bounds(
    samples: np.ndarray,
    sample_rate: int,
    *,
    threshold_db: float = TRIM_THRESHOLD_DB,
    frame_ms: float = TRIM_FRAME_MS,
    pad_before_ms: float = TRIM_PAD_BEFORE_MS,
    pad_after_ms: float = TRIM_PAD_AFTER_MS,
) -> TrimBounds:
    """Bounds of the loud part of a mono take, with a little room kept on each side.

    A take with no loud frame at all (or no samples) is kept whole and flagged
    ``silent``: trimming it away would leave nothing to play.
    """
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    data = np.asarray(samples)
    if data.ndim != 1:
        raise ValueError("samples must be mono (one dimension)")
    if not np.all(np.isfinite(data)):
        raise ValueError("samples must be finite")
    total = int(data.size)
    if total == 0:
        return TrimBounds(0, 0, 0, sample_rate, silent=True)

    frame = max(1, _samples_for_ms(frame_ms, sample_rate))
    squares = data.astype(np.float64) ** 2
    starts = np.arange(0, total, frame)
    sums = np.add.reduceat(squares, starts)
    counts = np.minimum(frame, total - starts)
    rms = np.sqrt(sums / counts)
    loud = np.flatnonzero(rms > 10.0 ** (threshold_db / 20.0))
    if loud.size == 0:
        return TrimBounds(0, total, total, sample_rate, silent=True)

    first, last = int(loud[0]), int(loud[-1])
    start = max(0, first * frame - _samples_for_ms(pad_before_ms, sample_rate))
    end = min(total, (last + 1) * frame + _samples_for_ms(pad_after_ms, sample_rate))
    return TrimBounds(start, end, total, sample_rate)


# --- Lengths: one place, so the timeline and the renderer always agree -----------


def samples_to_ms(samples: int, sample_rate: int) -> int:
    """Samples to whole milliseconds, rounded half up."""
    if samples < 0 or sample_rate <= 0:
        raise ValueError("samples must not be negative and sample_rate must be positive")
    return floor(Fraction(samples * 1000, sample_rate) + Fraction(1, 2))


def processed_samples(kept_samples: int, stretch: float) -> int:
    """Samples a trimmed take has once sped up by ``stretch`` (round half up).

    Same arithmetic as ``stretched_duration_ms``, applied to a sample count.
    """
    return stretched_duration_ms(kept_samples, stretch)


def trimmed_duration_ms(bounds: TrimBounds) -> int:
    """Length of the trimmed take before any stretch (what Tighten works from)."""
    return samples_to_ms(bounds.kept, bounds.sample_rate)


def processed_duration_ms(bounds: TrimBounds, stretch: float) -> int:
    """How long the processed take plays on the timeline, in ms."""
    return samples_to_ms(processed_samples(bounds.kept, stretch), bounds.sample_rate)


# --- Sidecar (pure encode and decode; the file I/O lives elsewhere) ---------------


def sidecar_name(raw_stem: str) -> str:
    """Sidecar file name for the raw take file ``raw_stem`` (``abc`` -> ``abc.trim.json``)."""
    if not raw_stem:
        raise ValueError("raw_stem must not be empty")
    return f"{raw_stem}.trim.json"


def bounds_to_data(bounds: TrimBounds) -> dict[str, Any]:
    return {
        "version": SIDECAR_VERSION,
        "params": trim_params(),
        "start": bounds.start,
        "end": bounds.end,
        "total": bounds.total,
        "sample_rate": bounds.sample_rate,
        "silent": bounds.silent,
    }


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def bounds_from_data(data: Any, *, expect_total: int | None = None) -> TrimBounds | None:
    """Decode a sidecar, or None when it is damaged or out of date.

    Out of date means: a different sidecar version, different trim settings than the
    current ones, or (when ``expect_total`` is given) a take of a different length.
    """
    if not isinstance(data, dict):
        return None
    if data.get("version") != SIDECAR_VERSION or data.get("params") != trim_params():
        return None
    start, end, total = data.get("start"), data.get("end"), data.get("total")
    rate, silent = data.get("sample_rate"), data.get("silent")
    if not all(_is_int(v) for v in (start, end, total, rate)) or not isinstance(silent, bool):
        return None
    if rate <= 0 or not 0 <= start <= end <= total:
        return None
    if expect_total is not None and total != expect_total:
        return None
    return TrimBounds(start, end, total, rate, silent)

