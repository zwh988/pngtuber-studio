"""Render a processed take (M4-1, S3a): the I/O edge of the audio chain.

Order of processing (decision 2026-10-30, M5-0): trim to the speech bounds (measured
inside the manual cut points, with a short fade at a manual cut edge), time-stretch
(only when the placement has a stretch), the plugin stages from the processing spec,
one loudness gain, then a peak limiter. The result is written as a float WAV at the
take's own sample rate, with exactly the number of samples the timeline computes
(``processed_samples``), so blocks and audio always agree.

CPU only. Pedalboard and pyloudnorm are imported when first needed, so the pure
modules (and tests of them) never need either. The raw take is only read (rule 1).
Every number here (limiter release, tolerances) is a starting value to tune by ear.
"""

import os
import threading
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile

from backend.audio.loudness import (
    Basis,
    db_to_linear,
    is_short,
    peak_dbfs,
    plan_gain,
    rms_dbfs,
)
from backend.audio.trim import (
    TrimBounds,
    apply_edge_fades,
    edge_fades,
    manual_cuts_from_spec,
    processed_samples,
)
from backend.project.schema import STRETCH_MAX, STRETCH_MIN

LIMITER_RELEASE_MS = 100.0
# A little under the ceiling after the safety scale-down, so float rounding can
# never leave a sample above it.
GUARD_FACTOR = 0.9999

# Stage name in the processing spec -> Pedalboard class name.
PLUGIN_CLASSES: dict[str, str] = {
    "low_shelf": "LowShelfFilter",
    "peak": "PeakFilter",
    "high_shelf": "HighShelfFilter",
    "compressor": "Compressor",
    "pitch_shift": "PitchShift",
    "chorus": "Chorus",
}


class ProcessError(Exception):
    """The processed take could not be made."""


@dataclass(frozen=True)
class RenderReport:
    """What one render did, for logs, the check script and tests."""

    samples: int
    sample_rate: int
    stretched: bool
    gain_db: float
    basis: Basis
    measured_db: float | None  # level before the gain (None: silent)
    clamped: bool  # the wanted gain was beyond the boost or cut limit
    silent: bool  # nothing to measure, no gain applied
    limited: bool  # the limiter (and safety scale-down) had to act
    peak_db: float  # sample peak of the written file


def read_mono(path: Path) -> tuple[np.ndarray, int]:
    """A take file as mono float32 plus its sample rate."""
    try:
        data, rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    except (OSError, RuntimeError) as exc:
        raise ProcessError(f"cannot read take file {path.name}: {exc}") from exc
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    return np.ascontiguousarray(mono, dtype=np.float32), int(rate)


def render_processed(
    raw_path: Path,
    dest: Path,
    spec: Mapping[str, Any],
    stretch: float,
    bounds: TrimBounds,
) -> RenderReport:
    """Make the processed take ``dest`` from ``raw_path`` and report what was done.

    ``bounds`` must be the trim bounds of this very file (``trim_bounds_for``);
    a mismatch raises ``ProcessError``. ``spec`` is ``processing_spec(chain)``,
    with the take's manual cut points added (``spec_with_manual_trim``); ``bounds``
    must then have been measured with those cut points.
    """
    if not STRETCH_MIN <= stretch <= STRETCH_MAX:  # also false for NaN
        raise ProcessError(
            f"stretch must be between {STRETCH_MIN} and {STRETCH_MAX}"
        )
    target, ceiling = _loudness_settings(spec)
    stages = spec.get("stages")
    if not isinstance(stages, list):
        raise ProcessError("the processing spec has no stage list")

    mono, rate = read_mono(raw_path)
    if bounds.total != mono.size or bounds.sample_rate != rate:
        raise ProcessError("the trim bounds do not match the take file")
    kept = mono[bounds.start : bounds.end]
    if kept.size == 0:
        raise ProcessError("the take has no audio")
    if not np.all(np.isfinite(kept)):
        raise ProcessError("the take contains NaN or infinite values")

    try:
        cut_start, cut_end = manual_cuts_from_spec(spec)
        fade_in, fade_out = edge_fades(bounds, cut_start, cut_end)
    except ValueError as exc:
        raise ProcessError(f"the manual trim cannot be used: {exc}") from exc

    pb = _pedalboard()
    expected = processed_samples(int(kept.size), stretch)
    samples = np.array(kept, dtype=np.float32)  # a copy: the raw array stays as read
    if fade_in or fade_out:
        samples = apply_edge_fades(samples, fade_in, fade_out).astype(np.float32)
    if stretch > 1.0:
        samples = _time_stretch(pb, samples, rate, stretch, expected)
    samples = _run_stages(pb, samples, rate, stages)

    level, basis = _measure_level(samples, rate)
    plan = plan_gain(level, target, basis=basis)
    samples = samples * np.float32(db_to_linear(plan.gain_db))

    ceiling_linear = db_to_linear(ceiling)
    limited = False
    if float(np.max(np.abs(samples))) > ceiling_linear:
        limited = True
        samples = _limit(pb, samples, rate, ceiling)
        peak = float(np.max(np.abs(samples)))
        if peak > ceiling_linear:
            samples = samples * np.float32(ceiling_linear * GUARD_FACTOR / peak)

    samples = _fit(np.asarray(samples, dtype=np.float32), expected)
    if not np.all(np.isfinite(samples)):
        raise ProcessError("the processed audio contains NaN or infinite values")
    _write_atomic(dest, samples, rate)
    return RenderReport(
        samples=int(samples.size),
        sample_rate=rate,
        stretched=stretch > 1.0,
        gain_db=plan.gain_db,
        basis=plan.basis,
        measured_db=plan.measured_db,
        clamped=plan.clamped,
        silent=plan.silent,
        limited=limited,
        peak_db=peak_dbfs(samples),
    )


def render_aligned_raw(
    raw_path: Path,
    spec: Mapping[str, Any],
    stretch: float,
    bounds: TrimBounds,
) -> tuple[np.ndarray, int]:
    """The raw take cut, faded and stretched exactly like its processed take, but with
    no stages, no loudness gain and no limiter (M6-2 ``voice_raw.wav``). Same length
    as the processed take, so the raw and processed voice tracks line up. In memory."""
    if not STRETCH_MIN <= stretch <= STRETCH_MAX:  # also false for NaN
        raise ProcessError(f"stretch must be between {STRETCH_MIN} and {STRETCH_MAX}")
    mono, rate = read_mono(raw_path)
    if bounds.total != mono.size or bounds.sample_rate != rate:
        raise ProcessError("the trim bounds do not match the take file")
    kept = mono[bounds.start : bounds.end]
    if kept.size == 0:
        raise ProcessError("the take has no audio")
    try:
        cut_start, cut_end = manual_cuts_from_spec(spec)
        fade_in, fade_out = edge_fades(bounds, cut_start, cut_end)
    except ValueError as exc:
        raise ProcessError(f"the manual trim cannot be used: {exc}") from exc
    expected = processed_samples(int(kept.size), stretch)
    samples = np.array(kept, dtype=np.float32)
    if fade_in or fade_out:
        samples = apply_edge_fades(samples, fade_in, fade_out).astype(np.float32)
    if stretch > 1.0:
        samples = _time_stretch(_pedalboard(), samples, rate, stretch, expected)
    return _fit(np.asarray(samples, dtype=np.float32), expected), rate


# --- steps ----------------------------------------------------------------------


def _pedalboard() -> Any:
    try:
        import pedalboard
    except ImportError as exc:
        raise ProcessError(
            "Pedalboard is not installed: run `uv add pedalboard`"
        ) from exc
    return pedalboard


def _loudness_settings(spec: Mapping[str, Any]) -> tuple[float, float]:
    try:
        loud = spec["loudness"]
        return float(loud["target_lufs"]), float(loud["ceiling_db"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProcessError("the processing spec has no loudness settings") from exc


def _flat(audio: Any) -> np.ndarray:
    samples = np.asarray(audio, dtype=np.float32)
    return samples[0] if samples.ndim == 2 else samples


def _fit(samples: np.ndarray, length: int) -> np.ndarray:
    """Cut or zero-pad to exactly ``length`` samples."""
    if samples.size > length:
        return samples[:length]
    if samples.size < length:
        return np.pad(samples, (0, length - samples.size))
    return samples


def _time_stretch(
    pb: Any, samples: np.ndarray, rate: int, stretch: float, expected: int
) -> np.ndarray:
    try:
        out = pb.time_stretch(
            samples.reshape(1, -1),
            float(rate),
            stretch_factor=stretch,
            pitch_shift_in_semitones=0.0,
        )
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise ProcessError(f"time-stretch failed: {exc}") from exc
    stretched = _flat(out)
    # Far from the expected length means the stretch ran the wrong way or the
    # library behaves differently than assumed: stop rather than misalign.
    if abs(stretched.size - expected) > max(expected * 0.05, rate * 0.02):
        raise ProcessError(
            f"stretched audio has {stretched.size} samples, expected about {expected}"
        )
    return _fit(stretched, expected)


def _build_plugin(pb: Any, stage: Mapping[str, Any]) -> Any:
    name = stage.get("plugin")
    class_name = PLUGIN_CLASSES.get(name) if isinstance(name, str) else None
    if class_name is None:
        raise ProcessError(f"unknown plugin stage {name!r}")
    params = {key: value for key, value in stage.items() if key != "plugin"}
    try:
        return getattr(pb, class_name)(**params)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProcessError(f"cannot build the {name} stage: {exc}") from exc


def _run_stages(
    pb: Any, samples: np.ndarray, rate: int, stages: list[Any]
) -> np.ndarray:
    if not stages:
        return samples
    board = pb.Pedalboard([_build_plugin(pb, stage) for stage in stages])
    try:
        out = board(samples.reshape(1, -1), float(rate))
    except (TypeError, ValueError, RuntimeError) as exc:
        raise ProcessError(f"the voice chain failed: {exc}") from exc
    return _fit(_flat(out), samples.size)


def _measure_level(samples: np.ndarray, rate: int) -> tuple[float, Basis]:
    """Integrated LUFS (pyloudnorm), or RMS for takes too short for BS.1770."""
    if is_short(int(samples.size), rate):
        return rms_dbfs(samples), "rms"
    try:
        import pyloudnorm
    except ImportError as exc:
        raise ProcessError(
            "pyloudnorm is not installed: run `uv add pyloudnorm`"
        ) from exc
    try:
        meter = pyloudnorm.Meter(rate)
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            level = float(meter.integrated_loudness(samples.astype(np.float64)))
    except ValueError:
        return rms_dbfs(samples), "rms"
    return level, "lufs"


def _limit(pb: Any, samples: np.ndarray, rate: int, ceiling_db: float) -> np.ndarray:
    try:
        limiter = pb.Limiter(threshold_db=ceiling_db, release_ms=LIMITER_RELEASE_MS)
        out = pb.Pedalboard([limiter])(samples.reshape(1, -1), float(rate))
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise ProcessError(f"the limiter failed: {exc}") from exc
    return _fit(_flat(out), samples.size)


def _write_atomic(dest: Path, samples: np.ndarray, rate: int) -> None:
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            soundfile.write(str(tmp), samples, rate, subtype="FLOAT", format="WAV")
            os.replace(tmp, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    except (OSError, RuntimeError) as exc:
        raise ProcessError(f"cannot write {dest.name}: {exc}") from exc
