"""Voice FX presets (M4-2): pure parsing, plus one thin file loader.

The file is ``templates/fx_presets.json``: ``{"presets": {"<name>": <FxChain fields>}}``.
Each preset is a full ``FxChain`` (EQ gains, compressor, effects, loudness target), so
applying one is just setting the project's chain. Starting values are guesses to tune
by ear, which is why they live in a file and not in code.
"""

import json
from pathlib import Path
from typing import Any

from backend.audio.chainspec import FxChainError, validate_chain
from backend.project.schema import FxChain

DEFAULT_PRESET = "Clean"  # required: the neutral chain the others are heard against


class FxPresetError(ValueError):
    """The presets file is malformed, or a preset has an unusable value."""


def parse_fx_presets(data: Any) -> dict[str, FxChain]:
    """Validate decoded JSON and return the presets in file order.

    Unknown keys are rejected so typos are caught. A ``Clean`` preset is required.
    """
    if not isinstance(data, dict) or not isinstance(data.get("presets"), dict):
        raise FxPresetError("presets file must be an object with a 'presets' object")
    extra_top = set(data) - {"presets"}
    if extra_top:
        raise FxPresetError(f"unknown keys in presets file: {sorted(extra_top)}")

    presets: dict[str, FxChain] = {}
    for name, body in data["presets"].items():
        if not isinstance(name, str) or not name or name != name.strip():
            raise FxPresetError(f"invalid preset name: {name!r}")
        if not isinstance(body, dict):
            raise FxPresetError(f"preset '{name}' must be an object")
        try:
            chain = FxChain.model_validate(body)
        except ValueError as exc:  # pydantic's ValidationError is a ValueError
            raise FxPresetError(f"preset '{name}' is not a valid chain: {exc}") from exc
        try:
            validate_chain(chain)
        except FxChainError as exc:
            raise FxPresetError(f"preset '{name}': {exc}") from exc
        presets[name] = chain
    if DEFAULT_PRESET not in presets:
        raise FxPresetError(f"presets must include '{DEFAULT_PRESET}'")
    return presets


# --- I/O at the edge --------------------------------------------------------


def default_fx_presets_path() -> Path:
    """``<repo>/templates/fx_presets.json``."""
    return Path(__file__).resolve().parents[2] / "templates" / "fx_presets.json"


def load_fx_presets_file(path: Path | None = None) -> dict[str, FxChain]:
    target = path if path is not None else default_fx_presets_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise FxPresetError(f"cannot read presets file {target}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FxPresetError(f"presets file {target} is not valid JSON: {exc}") from exc
    return parse_fx_presets(data)
