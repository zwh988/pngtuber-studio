"""Silence trimming maths (M4-1) and the manual take trim (M5-0): where a take is kept. Pure.

Numpy only, no files and no audio library. The take is trimmed *before* any time
stretch, so these bounds depend on the raw audio and the take's manual cut points alone
and the length a placed line plays for is plain arithmetic (see ``processed_duration_ms``).
The bounds are cached in a small JSON sidecar next to the processed files;
``bounds_from_data`` returns None for a stale or damaged sidecar so the caller simply
measures again.

Manual trim (M5-0): the user may cut a take at either end, in raw take time. The cut is
the outermost step: the region between the cuts is what the automatic silence trim then
measures inside. Bounds are always in samples of the whole raw take, so every length
function below works on them unchanged. A short fade at each manual cut edge hides the
click of cutting on a non-zero sample.

Starting values are guesses to tune by ear. Changing one changes the processing spec
(and so the processed keys of the takes it touches), which re-renders those takes;
nothing else needs to change.
"""

from collections.abc import Mapping
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

MANUAL_FADE_MS = 8  # raised-cosine fade at each manual cut edge
MANUAL_MIN_KEEP_MS = 200  # a manual trim must leave at least this much

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
    """Kept range ``[start, end)`` of a take, in samples of the whole raw take."""

    start: int
    end: int
    total: int  # samples in the whole raw take
    sample_rate: int
    silent: bool = False  # nothing loud found: the whole (manual) region is kept

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


# --- Manual trim (M5-0) --------------------------------------------------------------


class ManualTrimError(ValueError):
    """The manual cut points are not acceptable (the message is fit to show the user)."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_manual_trim(
    start_ms: int | None,
    end_ms: int | None,
    duration_ms: int,
    *,
    min_keep_ms: int = MANUAL_MIN_KEEP_MS,
) -> tuple[int | None, int | None]:
    """Check cut points in raw take time and return them in their one canonical form.

    ``None`` means no cut on that side. A cut at 0 (start) or at the take's end is
    the same as no cut and comes back as ``None``, so "no manual trim" has exactly one
    representation (and one cache key). Raises ``ManualTrimError`` otherwise.
    """
    if not _is_int(duration_ms) or duration_ms <= 0:
        raise ManualTrimError("the take has no length")
    for name, value in (("start", start_ms), ("end", end_ms)):
        if value is not None and (not _is_int(value) or value < 0):
            raise ManualTrimError(f"the {name} cut must be a whole number of ms, 0 or more")
    start = 0 if start_ms is None else start_ms
    end = duration_ms if end_ms is None else end_ms
    if end > duration_ms:
        raise ManualTrimError("the end cut is past the end of the take")
    if start >= end:
        raise ManualTrimError("the start cut must come before the end cut")
    if end - start < min(min_keep_ms, duration_ms):
        raise ManualTrimError(f"a trim must keep at least {min_keep_ms} ms")
    return (None if start == 0 else start, None if end == duration_ms else end)


def manual_region(
    total: int, sample_rate: int, start_ms: int | None, end_ms: int | None
) -> tuple[int, int]:
    """The kept region ``[start, end)`` in samples; cuts past the end are clamped.

    Raises ``ValueError`` when the cuts leave nothing (callers validate the cuts first
    with ``validate_manual_trim``; this is the tolerant version used while rendering).
    """
    if total < 0 or sample_rate <= 0:
        raise ValueError("total must not be negative and sample_rate must be positive")
    if total == 0:
        return (0, 0)
    start = 0 if start_ms is None else min(total, _samples_for_ms(start_ms, sample_rate))
    end = total if end_ms is None else min(total, _samples_for_ms(end_ms, sample_rate))
    if end <= start:
        raise ValueError("the manual cut leaves nothing of the take")
    return (start, end)


def find_speech_bounds_in_region(
    samples: np.ndarray,
    sample_rate: int,
    region_start: int,
    region_end: int,
    *,
    threshold_db: float = TRIM_THRESHOLD_DB,
    frame_ms: float = TRIM_FRAME_MS,
    pad_before_ms: float = TRIM_PAD_BEFORE_MS,
    pad_after_ms: float = TRIM_PAD_AFTER_MS,
) -> TrimBounds:
    """Silence bounds measured only inside ``[region_start, region_end)`` of the take.

    The padding never reaches past the region, and a region with nothing loud is kept
    whole (``silent``). The result is in samples of the whole take.
    """
    data = np.asarray(samples)
    if data.ndim != 1:
        raise ValueError("samples must be mono (one dimension)")
    total = int(data.size)
    if not 0 <= region_start <= region_end <= total:
        raise ValueError("the region must lie inside the take")
    inner = find_speech_bounds(
        data[region_start:region_end],
        sample_rate,
        threshold_db=threshold_db,
        frame_ms=frame_ms,
        pad_before_ms=pad_before_ms,
        pad_after_ms=pad_after_ms,
    )
    return TrimBounds(
        region_start + inner.start,
        region_start + inner.end,
        total,
        sample_rate,
        inner.silent,
    )


def edge_fades(
    bounds: TrimBounds,
    manual_start_ms: int | None,
    manual_end_ms: int | None,
    *,
    fade_ms: float = MANUAL_FADE_MS,
) -> tuple[int, int]:
    """Fade lengths ``(in, out)`` in samples for the kept range.

    A fade is wanted only where the kept range begins or ends exactly on a manual cut.
    If the silence trim already moved the edge inside the cut, that edge is quiet and
    needs none. The two fades never add up to more than the kept length.
    """
    region = manual_region(bounds.total, bounds.sample_rate, manual_start_ms, manual_end_ms)
    length = _samples_for_ms(fade_ms, bounds.sample_rate)
    fade_in = length if manual_start_ms is not None and bounds.start == region[0] else 0
    fade_out = length if manual_end_ms is not None and bounds.end == region[1] else 0
    cap = bounds.kept // 2
    return (min(fade_in, cap), min(fade_out, cap))


def apply_edge_fades(samples: np.ndarray, fade_in: int, fade_out: int) -> np.ndarray:
    """A copy of a mono take with a raised-cosine fade in and fade out. Pure."""
    data = np.asarray(samples)
    if data.ndim != 1:
        raise ValueError("samples must be mono (one dimension)")
    if not (_is_int(fade_in) and _is_int(fade_out)) or fade_in < 0 or fade_out < 0:
        raise ValueError("fade lengths must be whole numbers of samples, 0 or more")
    if fade_in + fade_out > data.size:
        raise ValueError("the fades are longer than the take")
    out = data.astype(data.dtype if data.dtype.kind == "f" else np.float64, copy=True)
    if fade_in:
        ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade_in) / fade_in))
        out[:fade_in] *= ramp.astype(out.dtype)
    if fade_out:
        ramp = 0.5 * (1.0 - np.cos(np.pi * np.arange(fade_out) / fade_out))
        out[out.size - fade_out :] *= ramp[::-1].astype(out.dtype)
    return out


def spec_with_manual_trim(
    spec: Mapping[str, Any], start_ms: int | None, end_ms: int | None
) -> dict[str, Any]:
    """The processing spec of one take: the chain's spec plus its manual cut points.

    With no manual cut this is an equal copy of ``spec``, so a take that was never
    trimmed keeps its processed key (and its processed file). With a cut, the entry
    holds the cut points and the fade length, so changing either re-keys that take only
    (CLAUDE.md rule 3). Pass the result to ``processed_key`` as its ``spec``.
    """
    out = dict(spec)
    if start_ms is None and end_ms is None:
        return out
    entry: dict[str, int | float] = {"fade_ms": MANUAL_FADE_MS}
    if start_ms is not None:
        entry["start_ms"] = start_ms
    if end_ms is not None:
        entry["end_ms"] = end_ms
    out["manual_trim"] = entry
    return out


def manual_cuts_from_spec(spec: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """The manual cut points ``(start_ms, end_ms)`` held in a take's processing spec.

    The inverse of ``spec_with_manual_trim``: ``(None, None)`` when the spec has no
    manual trim entry. Raises ``ValueError`` for a malformed entry.
    """
    entry = spec.get("manual_trim")
    if entry is None:
        return (None, None)
    if not isinstance(entry, Mapping):
        raise ValueError("the manual trim entry must be a mapping")  # noqa: TRY004
    start, end = entry.get("start_ms"), entry.get("end_ms")
    for value in (start, end):
        if value is not None and (not _is_int(value) or value < 0):
            raise ValueError("manual cut points must be whole ms, 0 or more")
    return (start, end)


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


def bounds_to_data(
    bounds: TrimBounds,
    *,
    manual_start_ms: int | None = None,
    manual_end_ms: int | None = None,
) -> dict[str, Any]:
    """Sidecar content. The manual cut points the bounds were measured with go in too."""
    return {
        "version": SIDECAR_VERSION,
        "params": trim_params(),
        "manual_start_ms": manual_start_ms,
        "manual_end_ms": manual_end_ms,
        "start": bounds.start,
        "end": bounds.end,
        "total": bounds.total,
        "sample_rate": bounds.sample_rate,
        "silent": bounds.silent,
    }


def bounds_from_data(
    data: Any,
    *,
    expect_total: int | None = None,
    expect_manual_start_ms: int | None = None,
    expect_manual_end_ms: int | None = None,
) -> TrimBounds | None:
    """Decode a sidecar, or None when it is damaged or out of date.

    Out of date means: a different sidecar version, different trim settings than the
    current ones, different manual cut points than expected (a sidecar without the cut
    fields counts as "no manual cut", as written before M5), or (when ``expect_total``
    is given) a take of a different length.
    """
    if not isinstance(data, dict):
        return None
    if data.get("version") != SIDECAR_VERSION or data.get("params") != trim_params():
        return None
    for cut in (data.get("manual_start_ms"), data.get("manual_end_ms")):
        if cut is not None and not _is_int(cut):
            return None
    if data.get("manual_start_ms") != expect_manual_start_ms:
        return None
    if data.get("manual_end_ms") != expect_manual_end_ms:
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
