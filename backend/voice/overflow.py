"""Overflow detection for placed lines (M3-9 groundwork). Pure, no I/O.

A placed line overflows when its audio runs past the next placement's start (spec 6,
CLAUDE.md rule 10: warn but allow). The caller passes timeline start times (already
mapped through the clip list) and the duration of the audio actually used.
"""

import itertools
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class PlacedLine:
    placement_id: str
    start_ms: int  # timeline time
    duration_ms: int  # duration of the audio that plays (raw take in M3)
    allow_overlap: bool = False


@dataclass(frozen=True)
class Overflow:
    placement_id: str
    next_placement_id: str
    overflow_ms: int  # always > 0
    allowed: bool  # the line has allow_overlap; the UI shows no warning


def _ordered(items: Iterable[PlacedLine]) -> list[PlacedLine]:
    ordered = sorted(items, key=lambda p: (p.start_ms, p.placement_id))
    seen: set[str] = set()
    for item in ordered:
        if item.start_ms < 0 or item.duration_ms < 0:
            raise ValueError(f"placement {item.placement_id}: negative start or duration")
        if item.placement_id in seen:
            raise ValueError(f"duplicate placement id {item.placement_id}")
        seen.add(item.placement_id)
    return ordered


def find_overflows(items: Iterable[PlacedLine]) -> list[Overflow]:
    """Every line that ends after the next line starts, in timeline order.

    Only the immediately following placement is considered. Lines with ``allow_overlap``
    are still returned, flagged ``allowed=True``; callers warn only for the rest.
    """
    ordered = _ordered(items)
    result: list[Overflow] = []
    for current, following in itertools.pairwise(ordered):
        overflow = current.start_ms + current.duration_ms - following.start_ms
        if overflow > 0:
            result.append(
                Overflow(
                    placement_id=current.placement_id,
                    next_placement_id=following.placement_id,
                    overflow_ms=overflow,
                    allowed=current.allow_overlap,
                )
            )
    return result


def available_slack_ms(items: Iterable[PlacedLine], placement_id: str) -> int:
    """How far earlier a line could start without running into the previous line's end.

    With no previous line the limit is the start of the timeline. Never negative.
    """
    ordered = _ordered(items)
    for index, item in enumerate(ordered):
        if item.placement_id != placement_id:
            continue
        if index == 0:
            return item.start_ms
        previous = ordered[index - 1]
        return max(0, item.start_ms - (previous.start_ms + previous.duration_ms))
    raise ValueError(f"unknown placement id {placement_id}")
