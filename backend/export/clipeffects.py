"""Clip effect registry for the export (M6, CLAUDE.md rule 13).

A clip effect turns its params into an ffmpeg video filter that the edit graph inserts
after the clip's trim and speed. None is registered in v1 (zoom, freeze and text are
out of scope); an unknown type is a pre-flight error, never silently dropped.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


class ClipEffectError(ValueError):
    """A clip effect cannot be used."""


@dataclass(frozen=True)
class ClipEffect:
    type: str
    label: str
    # params -> one ffmpeg filter (for example "hflip"); raises ClipEffectError
    video_filter: Callable[[Mapping[str, Any]], str]


REGISTRY: dict[str, ClipEffect] = {}


def register(effect: ClipEffect) -> None:
    if effect.type in REGISTRY:
        raise ValueError(f"clip effect {effect.type!r} is already registered")
    REGISTRY[effect.type] = effect


def get_effect(effect_type: str) -> ClipEffect | None:
    return REGISTRY.get(effect_type)


def video_filter_for(effect_type: str, params: Mapping[str, Any]) -> str:
    effect = REGISTRY.get(effect_type)
    if effect is None:
        raise ClipEffectError(f"unknown clip effect {effect_type!r}")
    return effect.video_filter(params)
