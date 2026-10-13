"""Emotion presets (M3-2): pure parsing and resolution, plus one thin file loader.

Starting values come from spec section 6 and are guesses to tune by ear. The file
lives in ``templates/emotion_presets.json`` so they can be tuned without code changes.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_EMOTION = "neutral"
EXAGGERATION_MIN, EXAGGERATION_MAX = 0.0, 2.0
CFG_WEIGHT_MIN, CFG_WEIGHT_MAX = 0.0, 1.0


class PresetError(ValueError):
    """The presets file is malformed, or a lookup could not be resolved."""


@dataclass(frozen=True)
class EmotionPreset:
    name: str
    exaggeration: float
    cfg_weight: float
    expression: str  # default avatar expression (used from M5)


def _number(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PresetError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise PresetError(f"{label} must be between {low} and {high}")
    return number


def parse_presets(data: Any) -> dict[str, EmotionPreset]:
    """Validate decoded JSON and return the presets in file order.

    Expected shape: ``{"presets": {"<name>": {"exaggeration", "cfg_weight", "expression"}}}``.
    Unknown keys are rejected so typos are caught. A ``neutral`` preset is required.
    """
    if not isinstance(data, dict) or not isinstance(data.get("presets"), dict):
        raise PresetError("presets file must be an object with a 'presets' object")
    extra_top = set(data) - {"presets"}
    if extra_top:
        raise PresetError(f"unknown keys in presets file: {sorted(extra_top)}")

    presets: dict[str, EmotionPreset] = {}
    for name, body in data["presets"].items():
        if not isinstance(name, str) or not name or name != name.strip():
            raise PresetError(f"invalid preset name: {name!r}")
        if not isinstance(body, dict):
            raise PresetError(f"preset '{name}' must be an object")
        extra = set(body) - {"exaggeration", "cfg_weight", "expression"}
        if extra:
            raise PresetError(f"preset '{name}' has unknown keys: {sorted(extra)}")
        missing = {"exaggeration", "cfg_weight", "expression"} - set(body)
        if missing:
            raise PresetError(f"preset '{name}' is missing: {sorted(missing)}")
        expression = body["expression"]
        if not isinstance(expression, str) or not expression.strip():
            raise PresetError(f"preset '{name}': expression must be a non-empty string")
        presets[name] = EmotionPreset(
            name=name,
            exaggeration=_number(
                body["exaggeration"], f"preset '{name}' exaggeration",
                EXAGGERATION_MIN, EXAGGERATION_MAX,
            ),
            cfg_weight=_number(
                body["cfg_weight"], f"preset '{name}' cfg_weight",
                CFG_WEIGHT_MIN, CFG_WEIGHT_MAX,
            ),
            expression=expression.strip(),
        )
    if DEFAULT_EMOTION not in presets:
        raise PresetError(f"presets must include '{DEFAULT_EMOTION}'")
    return presets


def resolve_params(
    emotion: str,
    exaggeration_override: float | None,
    cfg_weight_override: float | None,
    presets: dict[str, EmotionPreset],
) -> tuple[float, float]:
    """Return ``(exaggeration, cfg_weight)`` for a line: preset values, then overrides."""
    preset = presets.get(emotion)
    if preset is None:
        raise PresetError(f"unknown emotion '{emotion}'")
    exaggeration = preset.exaggeration
    cfg_weight = preset.cfg_weight
    if exaggeration_override is not None:
        exaggeration = _number(
            exaggeration_override, "exaggeration", EXAGGERATION_MIN, EXAGGERATION_MAX
        )
    if cfg_weight_override is not None:
        cfg_weight = _number(cfg_weight_override, "cfg_weight", CFG_WEIGHT_MIN, CFG_WEIGHT_MAX)
    return exaggeration, cfg_weight


# --- I/O at the edge --------------------------------------------------------


def default_presets_path() -> Path:
    """``<repo>/templates/emotion_presets.json``."""
    return Path(__file__).resolve().parents[2] / "templates" / "emotion_presets.json"


def load_presets_file(path: Path | None = None) -> dict[str, EmotionPreset]:
    target = path if path is not None else default_presets_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise PresetError(f"cannot read presets file {target}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PresetError(f"presets file {target} is not valid JSON: {exc}") from exc
    return parse_presets(data)
