"""Emotion presets edited in Settings (M7 S5). App-wide, not per project.

The built-in presets stay in ``templates/emotion_presets.json`` (part of the app,
replaced by updates). Edited values go to ``%APPDATA%\\PNGtuberStudio\\
emotion_presets.json`` in the same format, and that file wins when it is valid. Only
the values of the built-in presets can be edited (same names, same order), so no
line can end up with an emotion that is gone. "Reset to built-in" deletes the file.

Edited values change the raw cache key of lines that use them (the key holds the
resolved exaggeration and cfg_weight, rule 3), so the next Generate makes a new take;
old takes stay (rule 1). A preset's expression only feeds the avatar's auto-keys.

``build_presets_state`` and ``check_edit`` are pure; the rest is file I/O.
"""

import json
import os
from pathlib import Path

from pydantic import BaseModel

from backend.voice.presets import (
    CFG_WEIGHT_MAX,
    CFG_WEIGHT_MIN,
    EXAGGERATION_MAX,
    EXAGGERATION_MIN,
    EmotionPreset,
    PresetError,
    load_presets_file,
    parse_presets,
)

USER_PRESETS_NAME = "emotion_presets.json"


class PresetItem(BaseModel):
    name: str
    exaggeration: float
    cfg_weight: float
    expression: str
    # the built-in values, for "changed" marks and a per-row reset in the UI
    builtin_exaggeration: float
    builtin_cfg_weight: float
    builtin_expression: str


class PresetsState(BaseModel):
    """``GET /api/settings`` ``presets`` and the presets routes."""

    presets: list[PresetItem]
    customized: bool  # the user file is in use
    path: str  # where edited values are saved
    problem: str | None = None  # the user file is broken: built-in values in use
    exaggeration_min: float = EXAGGERATION_MIN
    exaggeration_max: float = EXAGGERATION_MAX
    cfg_weight_min: float = CFG_WEIGHT_MIN
    cfg_weight_max: float = CFG_WEIGHT_MAX


class PresetEdit(BaseModel):
    name: str
    exaggeration: float
    cfg_weight: float
    expression: str


# ---- pure -----------------------------------------------------------------------


def encode_presets(presets: dict[str, EmotionPreset]) -> dict[str, object]:
    return {
        "presets": {
            p.name: {
                "exaggeration": round(p.exaggeration, 3),
                "cfg_weight": round(p.cfg_weight, 3),
                "expression": p.expression,
            }
            for p in presets.values()
        }
    }


def check_edit(
    builtin: dict[str, EmotionPreset], edits: list[PresetEdit]
) -> dict[str, EmotionPreset]:
    """The edited presets, validated like the file. The names must be the built-in
    ones in the same order: values change, presets are not added or removed."""
    if [e.name for e in edits] != list(builtin):
        raise PresetError(
            "the presets must be the built-in ones (" + ", ".join(builtin) + ") in that order"
        )
    data = {
        "presets": {
            e.name: {
                "exaggeration": e.exaggeration,
                "cfg_weight": e.cfg_weight,
                "expression": e.expression,
            }
            for e in edits
        }
    }
    parsed = parse_presets(data)
    return {
        name: EmotionPreset(
            name=name,
            exaggeration=round(p.exaggeration, 3),
            cfg_weight=round(p.cfg_weight, 3),
            expression=p.expression,
        )
        for name, p in parsed.items()
    }


def merge_with_builtin(
    builtin: dict[str, EmotionPreset], user: dict[str, EmotionPreset]
) -> dict[str, EmotionPreset]:
    """Built-in names and order, user values where the user file has that name. A
    preset added to the built-ins by an update appears with its built-in values."""
    return {name: user.get(name, preset) for name, preset in builtin.items()}


def build_presets_state(
    builtin: dict[str, EmotionPreset],
    effective: dict[str, EmotionPreset],
    *,
    customized: bool,
    path: Path,
    problem: str | None,
) -> PresetsState:
    items = [
        PresetItem(
            name=name,
            exaggeration=effective[name].exaggeration,
            cfg_weight=effective[name].cfg_weight,
            expression=effective[name].expression,
            builtin_exaggeration=b.exaggeration,
            builtin_cfg_weight=b.cfg_weight,
            builtin_expression=b.expression,
        )
        for name, b in builtin.items()
    ]
    return PresetsState(presets=items, customized=customized, path=str(path), problem=problem)


# ---- I/O ------------------------------------------------------------------------


def default_user_presets_path() -> Path:
    r"""``%APPDATA%\PNGtuberStudio\emotion_presets.json`` (as ``recent.json``)."""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "PNGtuberStudio" / USER_PRESETS_NAME


def load_effective(
    user_path: Path | None, builtin_path: Path | None = None
) -> tuple[dict[str, EmotionPreset], dict[str, EmotionPreset], bool, str | None]:
    """``(builtin, effective, customized, problem)``. A missing user file means
    built-in values; a broken one too, with ``problem`` saying why."""
    builtin = load_presets_file(builtin_path)
    if user_path is None or not user_path.is_file():
        return builtin, builtin, False, None
    try:
        user = load_presets_file(user_path)
    except PresetError as exc:
        problem = f"your edited presets could not be read ({exc}); the built-in values are in use"
        return builtin, builtin, False, problem
    return builtin, merge_with_builtin(builtin, user), True, None


def save_user_presets(path: Path, presets: dict[str, EmotionPreset]) -> None:
    """Atomic write (temp file, then replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(encode_presets(presets), indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def delete_user_presets(path: Path) -> None:
    path.unlink(missing_ok=True)
