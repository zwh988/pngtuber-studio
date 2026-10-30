"""Voice effect registry (M4-1, CLAUDE.md rule 13): which effects the Effects slot offers.

Each effect declares its parameters (type, default, range) and the plugin it maps to.
Adding an effect is one ``register`` call: the chain builder, the validation and the UI
description all read from here. Pure, no audio library. The render module turns a stage
``{"plugin": ..., **params}`` into the matching Pedalboard plugin.

Only effects that keep the audio length belong here for now. A reverb tail would change
the length, and the timeline needs the length ahead of rendering (decision: left out).
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal


class EffectError(ValueError):
    """Unknown effect, or parameters that are missing, unknown or out of range."""


@dataclass(frozen=True)
class ParamDef:
    name: str
    label: str
    kind: Literal["float", "int"]
    default: float
    minimum: float
    maximum: float
    unit: str = ""


@dataclass(frozen=True)
class VoiceEffect:
    type: str
    label: str
    plugin: str  # stage name the render module maps to a Pedalboard plugin
    params: tuple[ParamDef, ...]
    # True when these parameters change nothing (the stage is then left out of the chain).
    is_noop: Callable[[Mapping[str, float | int]], bool] | None = None


REGISTRY: dict[str, VoiceEffect] = {}


def register(effect: VoiceEffect) -> None:
    if effect.type in REGISTRY:
        raise EffectError(f"effect '{effect.type}' is already registered")
    REGISTRY[effect.type] = effect


def effect_types() -> list[str]:
    return list(REGISTRY)


def get_effect(effect_type: str) -> VoiceEffect:
    effect = REGISTRY.get(effect_type)
    if effect is None:
        raise EffectError(f"unknown effect '{effect_type}'")
    return effect


def _check_number(value: Any, param: ParamDef, effect_type: str) -> float | int:
    label = f"{effect_type}.{param.name}"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EffectError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise EffectError(f"{label} must be a finite number")
    if not param.minimum <= number <= param.maximum:
        raise EffectError(f"{label} must be between {param.minimum} and {param.maximum}")
    if param.kind == "int":
        if number != int(number):
            raise EffectError(f"{label} must be a whole number")
        return int(number)
    return round(number, 3)


def normalize_params(effect_type: str, params: Mapping[str, Any]) -> dict[str, float | int]:
    """Validated parameters in declaration order, defaults filled in, floats rounded."""
    effect = get_effect(effect_type)
    known = {p.name for p in effect.params}
    unknown = set(params) - known
    if unknown:
        raise EffectError(f"{effect_type} has unknown parameters: {sorted(unknown)}")
    out: dict[str, float | int] = {}
    for param in effect.params:
        value = params.get(param.name, param.default)
        out[param.name] = _check_number(value, param, effect_type)
    return out


def effect_stage(effect_type: str, params: Mapping[str, Any]) -> dict[str, Any] | None:
    """The chain stage for an effect, or None when its settings change nothing."""
    effect = get_effect(effect_type)
    values = normalize_params(effect_type, params)
    if effect.is_noop is not None and effect.is_noop(values):
        return None
    return {"plugin": effect.plugin, **values}


def describe_effects() -> list[dict[str, Any]]:
    """What the UI needs to build the effect controls."""
    return [
        {
            "type": e.type,
            "label": e.label,
            "params": [
                {
                    "name": p.name,
                    "label": p.label,
                    "kind": p.kind,
                    "default": p.default,
                    "min": p.minimum,
                    "max": p.maximum,
                    "unit": p.unit,
                }
                for p in e.params
            ],
        }
        for e in REGISTRY.values()
    ]


# --- The effects offered in M4 ---------------------------------------------------

register(
    VoiceEffect(
        type="pitch_shift",
        label="Pitch shift",
        plugin="pitch_shift",
        params=(ParamDef("semitones", "Semitones", "float", 0.0, -12.0, 12.0, "st"),),
        is_noop=lambda p: p["semitones"] == 0,
    )
)
register(
    VoiceEffect(
        type="chorus",
        label="Chorus",
        plugin="chorus",
        params=(
            ParamDef("rate_hz", "Rate", "float", 1.0, 0.1, 10.0, "Hz"),
            ParamDef("depth", "Depth", "float", 0.25, 0.0, 1.0),
            ParamDef("centre_delay_ms", "Centre delay", "float", 7.0, 1.0, 30.0, "ms"),
            ParamDef("feedback", "Feedback", "float", 0.0, 0.0, 0.95),
            ParamDef("mix", "Mix", "float", 0.5, 0.0, 1.0),
        ),
        is_noop=lambda p: p["mix"] == 0,
    )
)
