"""Render an audio clip's FX (M8-4): its whole decoded file through its chain. CPU only.

The input is the decoded WAV of the clip's file (``media/audio_decoded``, any channel
count); the output keeps its rate, channels and length and goes to
``media/audio_fx/<key>.wav`` (``clip_fx_key``), so clips sharing a file and a chain share
one render, and moving or trimming a clip never re-renders (decision 3). The stages are
the voice chain's (``backend/audio/render.py`` builds the Pedalboard plugins); loudness
levelling, when on, measures the whole file and is followed by the same limiter.
"""

import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile

from backend.audio.loudness import db_to_linear, is_short, plan_gain, rms_dbfs
from backend.audio.render import (
    GUARD_FACTOR,
    LIMITER_RELEASE_MS,
    ProcessError,
    _build_plugin,
    _loudness_settings,
    _pedalboard,
    _write_atomic,
)

AUDIO_FX_DIR = "media/audio_fx"


@dataclass(frozen=True)
class ClipFxReport:
    samples: int
    channels: int
    sample_rate: int
    gain_db: float  # the levelling gain, 0 when levelling is off
    limited: bool


def _fit_planar(audio: np.ndarray, length: int) -> np.ndarray:
    """Cut or zero-pad a (channels, samples) array to ``length`` samples."""
    if audio.shape[1] > length:
        return audio[:, :length]
    if audio.shape[1] < length:
        return np.pad(audio, ((0, 0), (0, length - audio.shape[1])))
    return audio


def _level(planar: np.ndarray, rate: int) -> tuple[float, str]:
    """Integrated LUFS over all channels, or RMS for files too short for BS.1770."""
    if is_short(int(planar.shape[1]), rate):
        return rms_dbfs(planar.reshape(-1)), "rms"
    import pyloudnorm

    try:
        meter = pyloudnorm.Meter(rate)
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            level = float(meter.integrated_loudness(planar.T.astype(np.float64)))
    except ValueError:
        return rms_dbfs(planar.reshape(-1)), "rms"
    return level, "lufs"


def render_clip_fx(src: Path, dest: Path, spec: Mapping[str, Any]) -> ClipFxReport:
    """Make ``dest`` from the decoded file ``src`` through ``spec`` (``clip_processing_spec``)."""
    try:
        data, rate = soundfile.read(str(src), dtype="float32", always_2d=True)
    except (OSError, RuntimeError) as exc:
        raise ProcessError(f"cannot read {src.name}: {exc}") from exc
    if data.size == 0:
        raise ProcessError("the audio file has no samples")
    length = int(data.shape[0])
    planar = np.ascontiguousarray(data.T)  # (channels, samples), as Pedalboard wants it
    pb = _pedalboard()
    stages = spec.get("stages") or []
    if stages:
        board = pb.Pedalboard([_build_plugin(pb, stage) for stage in stages])
        try:
            planar = np.asarray(board(planar, float(rate)), dtype=np.float32)
        except (TypeError, ValueError, RuntimeError) as exc:
            raise ProcessError(f"the clip chain failed: {exc}") from exc
        planar = _fit_planar(planar, length)

    gain_db = 0.0
    limited = False
    if spec.get("loudness") is not None:
        target, ceiling = _loudness_settings(spec)
        level, basis = _level(planar, rate)
        plan = plan_gain(level, target, basis=basis)  # type: ignore[arg-type]
        gain_db = plan.gain_db
        planar = planar * np.float32(db_to_linear(gain_db))
        ceiling_linear = db_to_linear(ceiling)
        if float(np.max(np.abs(planar))) > ceiling_linear:
            limited = True
            limiter = pb.Limiter(threshold_db=ceiling, release_ms=LIMITER_RELEASE_MS)
            planar = _fit_planar(np.asarray(pb.Pedalboard([limiter])(planar, float(rate)), dtype=np.float32), length)
            peak = float(np.max(np.abs(planar)))
            if peak > ceiling_linear:
                planar = planar * np.float32(ceiling_linear * GUARD_FACTOR / peak)

    if not np.all(np.isfinite(planar)):
        raise ProcessError("the processed audio contains NaN or infinite values")
    _write_atomic(dest, np.ascontiguousarray(planar.T), rate)
    return ClipFxReport(length, int(planar.shape[0]), rate, gain_db, limited)
