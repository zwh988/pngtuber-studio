"""Loudness maths (M4-1): how much gain brings a take to its target. Pure.

The measuring itself (pyloudnorm, or the RMS fallback for very short takes) happens in
the render module; this file only holds the settings and the arithmetic, so it can be
tested without audio libraries.
"""

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

TARGET_MIN_LUFS = -40.0
TARGET_MAX_LUFS = -5.0
CEILING_DB = -1.0  # the limiter after the gain keeps samples under this
SHORT_TAKE_MS = 400  # BS.1770 measures in 400 ms blocks: shorter takes use RMS instead
MAX_BOOST_DB = 20.0  # never raise a take by more than this
MAX_CUT_DB = 30.0  # never lower a take by more than this
# RMS of speech sits close to its LUFS value, so no offset to start with. Tune by ear.
RMS_TO_LUFS_OFFSET_DB = 0.0

Basis = Literal["lufs", "rms"]


def loudness_params(target_lufs: float) -> dict[str, float | int]:
    """The loudness settings as plain data (part of the processing spec)."""
    return {
        "target_lufs": float(target_lufs),
        "ceiling_db": CEILING_DB,
        "short_take_ms": SHORT_TAKE_MS,
        "max_boost_db": MAX_BOOST_DB,
        "max_cut_db": MAX_CUT_DB,
        "rms_offset_db": RMS_TO_LUFS_OFFSET_DB,
    }


def is_short(n_samples: int, sample_rate: int) -> bool:
    """True when the take is too short for a LUFS measurement (under 400 ms)."""
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    return n_samples * 1000 < SHORT_TAKE_MS * sample_rate


def peak_dbfs(samples: np.ndarray) -> float:
    """Sample peak in dBFS; ``-inf`` for silence or no samples."""
    data = np.asarray(samples, dtype=np.float64)
    if data.size == 0:
        return -math.inf
    peak = float(np.max(np.abs(data)))
    return 20.0 * math.log10(peak) if peak > 0 else -math.inf


def rms_dbfs(samples: np.ndarray) -> float:
    """RMS level in dBFS; ``-inf`` for silence or no samples."""
    data = np.asarray(samples, dtype=np.float64)
    if data.size == 0:
        return -math.inf
    rms = math.sqrt(float(np.mean(data**2)))
    return 20.0 * math.log10(rms) if rms > 0 else -math.inf


@dataclass(frozen=True)
class GainPlan:
    gain_db: float
    basis: Basis
    measured_db: float | None  # the level measured (None when silent)
    clamped: bool  # the wanted gain was beyond the boost or cut limit
    silent: bool  # nothing to measure: no gain applied


def plan_gain(measured_db: Any, target_lufs: float, *, basis: Basis) -> GainPlan:
    """Gain in dB that moves ``measured_db`` to ``target_lufs``, within the limits.

    ``basis`` says what was measured: ``lufs`` (pyloudnorm) or ``rms`` (short takes).
    A level that is missing, NaN or ``-inf`` means silence: gain 0, flagged ``silent``.
    """
    if basis not in ("lufs", "rms"):
        raise ValueError("basis must be 'lufs' or 'rms'")
    if not math.isfinite(target_lufs):
        raise ValueError("target must be a finite number")
    if (
        measured_db is None
        or isinstance(measured_db, bool)
        or not isinstance(measured_db, (int, float))
        or not math.isfinite(measured_db)
    ):
        return GainPlan(0.0, basis, None, False, True)
    level = float(measured_db)
    if basis == "rms":
        level += RMS_TO_LUFS_OFFSET_DB
    wanted = target_lufs - level
    gain = min(max(wanted, -MAX_CUT_DB), MAX_BOOST_DB)
    return GainPlan(gain, basis, float(measured_db), gain != wanted, False)


def db_to_linear(db: float) -> float:
    return 10.0 ** (db / 20.0)


def predicted_peak_db(peak_db: float, gain_db: float) -> float:
    """Sample peak after the gain (``-inf`` stays ``-inf``); above the ceiling means the
    limiter will work."""
    return peak_db + gain_db
