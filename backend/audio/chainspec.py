"""Voice chain to processing spec (M4-1): the plain-data recipe for a processed take. Pure.

``processing_spec(chain)`` lists everything that changes the audio apart from the raw
take and the stretch: the trim settings, the plugin stages (EQ, compressor, effects)
and the loudness settings. It is what ``processed_key`` hashes, so:

- an EQ band at 0 dB, a disabled compressor, or an effect set to do nothing leaves no
  stage, and moving those controls never re-renders anything (CLAUDE.md rule 3);
- changing a tuning constant (trim threshold, EQ frequency, limiter ceiling) changes
  the key, so stale files are never reused.

The render module turns each stage into a Pedalboard plugin by its ``plugin`` name.
Order of processing: trim, stretch, the stages in order, loudness gain, limiter.
"""

import math
from typing import Any

from backend.audio.effects import EffectError, effect_stage
from backend.audio.loudness import TARGET_MAX_LUFS, TARGET_MIN_LUFS, loudness_params
from backend.audio.trim import trim_params
from backend.project.schema import FxChain

PROCESSING_VERSION = 1  # bump when the render code itself changes what a spec produces

# (FxChain field, plugin, cutoff Hz, Q). Frequencies are guesses to tune by ear.
EQ_BANDS: tuple[tuple[str, str, float, float], ...] = (
    ("eq_bass_db", "low_shelf", 120.0, 0.707),
    ("eq_mid_db", "peak", 1500.0, 0.6),
    ("eq_treble_db", "high_shelf", 6000.0, 0.707),
)
EQ_GAIN_LIMIT_DB = 12.0
EQ_SKIP_BELOW_DB = 0.01  # a band closer to 0 than this is left out

# Compressor limits (checked only when it is enabled): name -> (low, high).
COMPRESSOR_RANGES: dict[str, tuple[float, float]] = {
    "threshold_db": (-60.0, 0.0),
    "ratio": (1.0, 20.0),
    "attack_ms": (0.1, 200.0),
    "release_ms": (5.0, 2000.0),
}


class FxChainError(ValueError):
    """The voice chain has a value the processing cannot use."""


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FxChainError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise FxChainError(f"{label} must be a finite number")
    return number


def _round(value: float) -> float:
    return round(value, 3)


def validate_chain(chain: FxChain) -> None:
    """Raise ``FxChainError`` when any part of the chain is unusable."""
    build_stages(chain)
    _target(chain)


def _target(chain: FxChain) -> float:
    target = _finite(chain.loudness_target_lufs, "loudness target")
    if not TARGET_MIN_LUFS <= target <= TARGET_MAX_LUFS:
        raise FxChainError(
            f"loudness target must be between {TARGET_MIN_LUFS} and {TARGET_MAX_LUFS} LUFS"
        )
    return target


def build_stages(chain: FxChain) -> list[dict[str, Any]]:
    """The ordered plugin stages for a chain: EQ bands, compressor, then effects."""
    stages: list[dict[str, Any]] = []

    for field, plugin, cutoff_hz, q in EQ_BANDS:
        gain = _finite(getattr(chain, field), field)
        if abs(gain) > EQ_GAIN_LIMIT_DB:
            raise FxChainError(
                f"{field} must be between -{EQ_GAIN_LIMIT_DB} and {EQ_GAIN_LIMIT_DB} dB"
            )
        if abs(gain) < EQ_SKIP_BELOW_DB:
            continue
        stages.append(
            {
                "plugin": plugin,
                "cutoff_frequency_hz": cutoff_hz,
                "gain_db": _round(gain),
                "q": q,
            }
        )

    comp = chain.compressor
    if comp.enabled:
        values: dict[str, float] = {}
        for name, (low, high) in COMPRESSOR_RANGES.items():
            number = _finite(getattr(comp, name), f"compressor {name}")
            if not low <= number <= high:
                raise FxChainError(f"compressor {name} must be between {low} and {high}")
            values[name] = _round(number)
        stages.append({"plugin": "compressor", **values})

    for spec in chain.effects:
        try:
            stage = effect_stage(spec.type, spec.params)
        except EffectError as exc:
            raise FxChainError(str(exc)) from exc
        if stage is not None:
            stages.append(stage)
    return stages


def processing_spec(chain: FxChain) -> dict[str, Any]:
    """Everything beyond the raw take and the stretch that decides a processed take."""
    stages = build_stages(chain)
    target = _target(chain)
    return {
        "version": PROCESSING_VERSION,
        "trim": trim_params(),
        "stages": stages,
        "loudness": loudness_params(target),
    }
