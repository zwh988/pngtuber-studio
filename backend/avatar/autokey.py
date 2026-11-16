"""Auto-key (M5-7 backend, decision 12): virtual expression keys from line emotions. Pure.

With ``AvatarSettings.auto_key_expression`` on, each placed line that plays gives a
virtual expression key at its start, from the line's emotion: the art's
``emotion_map`` first, else the emotion preset's own ``expression``. Nothing is written
to ``project.json``; a manual key at the same time wins (``ExpressionLane``).

A preset whose expression only falls back to the default (``neutral``, or a name the
art lacks) adds **no** key, so it never overrides a manual key set earlier (decision
2026-11-16: the user's presets all mean "neutral").
"""

from collections.abc import Mapping, Sequence
from typing import Protocol

from backend.avatar.art import NEUTRAL, AvatarArt
from backend.avatar.lanes import ExpressionKey


class PlacedLine(Protocol):
    """The part of a ``TimelinePlacement`` auto-key needs."""

    line_id: str
    start_ms: int | None
    orphaned: bool
    take_id: str | None


def auto_expression_keys(
    placements: Sequence[PlacedLine],
    line_emotions: Mapping[str, str],
    preset_expressions: Mapping[str, str],
    art: AvatarArt | None,
    *,
    enabled: bool = True,
) -> list[ExpressionKey]:
    """Virtual keys at the starts of the playing placements (ordered by time)."""
    if not enabled or art is None or not art.usable:
        return []
    keys: list[ExpressionKey] = []
    for placed in placements:
        if placed.orphaned or placed.start_ms is None or placed.take_id is None:
            continue
        emotion = line_emotions.get(placed.line_id)
        if emotion is None:
            continue
        expression = _expression_for(art, emotion, preset_expressions.get(emotion))
        if expression is not None:
            keys.append(ExpressionKey(placed.start_ms, expression, manual=False))
    keys.sort(key=lambda k: k.t_ms)
    return keys


def _expression_for(art: AvatarArt, emotion: str, preset: str | None) -> str | None:
    mapped = art.emotion_map.get(emotion)
    if mapped is not None:
        return mapped
    if preset is None or preset.casefold() == NEUTRAL:
        return None
    found = art.get(preset)
    return found.id if found is not None and found.sprites else None
