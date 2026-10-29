"""Render a time-stretched copy of a take (M3-9, S8c): the I/O edge for Tighten.

The raw take is never touched (CLAUDE.md rule 1). The stretched copy is written to
``media/takes_fx/`` beside ``media/takes_raw/`` and reused whenever it exists
(rule 3: same inputs, same file). Pitch is kept (Pedalboard's Rubber Band stretch).
CPU only, a fraction of a second for a spoken line.
"""

import os
import threading
from pathlib import Path

import numpy as np
import soundfile

from backend.project.schema import STRETCH_MAX, STRETCH_MIN
from backend.voice.stretch import stretched_duration_ms, stretched_name

FX_DIR_NAME = "takes_fx"


class StretchError(Exception):
    """The stretched copy could not be made."""


def stretched_path(raw_path: Path, stretch: float) -> Path:
    """Where the stretched copy of ``raw_path`` lives (``media/takes_fx/...``)."""
    return raw_path.parent.parent / FX_DIR_NAME / stretched_name(raw_path.stem, stretch)


def ensure_stretched(raw_path: Path, stretch: float) -> Path:
    """Path of the stretched copy, rendering it first when it does not exist yet."""
    if not STRETCH_MIN < stretch <= STRETCH_MAX:  # also false for NaN
        raise StretchError(
            f"stretch must be above {STRETCH_MIN} and at most {STRETCH_MAX}"
        )
    dest = stretched_path(raw_path, stretch)
    if dest.is_file():
        return dest
    _render(raw_path, dest, stretch)
    return dest


def _render(raw_path: Path, dest: Path, stretch: float) -> None:
    try:
        data, rate = soundfile.read(str(raw_path), dtype="float32", always_2d=True)
    except (OSError, RuntimeError) as exc:
        raise StretchError(f"cannot read take file {raw_path.name}: {exc}") from exc
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    if mono.size == 0:
        raise StretchError("the take has no audio")

    try:
        import pedalboard
    except ImportError as exc:
        raise StretchError(
            "Pedalboard is not installed: run `uv add pedalboard`"
        ) from exc
    try:
        out = pedalboard.time_stretch(
            mono.reshape(1, -1),
            float(rate),
            stretch_factor=stretch,
            pitch_shift_in_semitones=0.0,
        )
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        raise StretchError(f"time-stretch failed: {exc}") from exc

    samples = np.asarray(out, dtype=np.float32)
    if samples.ndim == 2:
        samples = samples[0]
    expected = stretched_duration_ms(int(mono.size), stretch)  # in samples here
    # A result far from the expected length means the stretch ran the wrong way
    # or the library behaves differently than assumed: stop rather than misalign.
    if abs(samples.size - expected) > max(expected * 0.05, rate * 0.02):
        raise StretchError(
            f"stretched audio has {samples.size} samples, expected about {expected}"
        )
    # Match the length the timeline computes, so blocks and audio line up exactly.
    if samples.size > expected:
        samples = samples[:expected]
    elif samples.size < expected:
        samples = np.pad(samples, (0, expected - samples.size))
    if not np.all(np.isfinite(samples)):
        raise StretchError("stretched audio contains NaN or infinite values")

    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            soundfile.write(str(tmp), samples, int(rate), subtype="FLOAT", format="WAV")
            os.replace(tmp, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    except (OSError, RuntimeError) as exc:
        raise StretchError(f"cannot write {dest.name}: {exc}") from exc
