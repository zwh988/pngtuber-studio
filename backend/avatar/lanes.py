"""Avatar lanes (M5-5 core): fixed lane ids, ranges, defaults, and evaluation. Pure.

A lane is a list of keys in **timeline** time (the caller maps anchors through the clip
list first; orphaned keys are left out). A key's ``interpolation`` describes the segment
from that key to the next one: ``hold`` keeps its value, ``smooth`` eases to the next
value (smoothstep). Before the first key the first value holds, after the last the last
value holds; a lane without keys gives its base value (``AvatarSettings`` for the
transform lanes, the lane default otherwise).

The expression lane holds expression names and is always ``hold``.
"""

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Interpolation = Literal["hold", "smooth"]


@dataclass(frozen=True)
class LaneSpec:
    id: str
    label: str
    kind: Literal["enum", "number"]
    minimum: float = 0.0
    maximum: float = 1.0
    default: float = 0.0


EXPRESSION = "expression"

LANES: tuple[LaneSpec, ...] = (
    LaneSpec(EXPRESSION, "Expression", "enum"),
    LaneSpec("bounce", "Bounce", "number", 0.0, 3.0, 1.0),
    LaneSpec("float_amp", "Float amount", "number", 0.0, 3.0, 1.0),
    LaneSpec("float_speed", "Float speed", "number", 0.0, 4.0, 1.0),
    LaneSpec("blink_rate", "Blink rate", "number", 0.0, 4.0, 1.0),
    LaneSpec("mouth_sensitivity", "Mouth sensitivity", "number", 0.25, 4.0, 1.0),
    LaneSpec("scale", "Scale", "number", 0.05, 5.0, 1.0),
    LaneSpec("x", "X", "number", -0.5, 1.5, 0.85),
    LaneSpec("y", "Y", "number", -0.5, 1.5, 0.75),
    LaneSpec("rotation", "Rotation", "number", -180.0, 180.0, 0.0),
)
LANES_BY_ID: dict[str, LaneSpec] = {lane.id: lane for lane in LANES}
NUMBER_LANES: tuple[str, ...] = tuple(lane.id for lane in LANES if lane.kind == "number")


@dataclass(frozen=True)
class LaneKey:
    t_ms: int  # timeline time
    value: float
    interpolation: Interpolation = "hold"


def clamp_lane(lane_id: str, value: float) -> float:
    spec = LANES_BY_ID[lane_id]
    return min(spec.maximum, max(spec.minimum, value))


def smoothstep(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3.0 - 2.0 * u)


class Lane:
    """One numeric lane ready to evaluate. Keys at the same time: the last one wins."""

    def __init__(self, keys: Sequence[LaneKey], base: float) -> None:
        ordered = sorted(enumerate(keys), key=lambda item: (item[1].t_ms, item[0]))
        merged: list[LaneKey] = []
        for _, key in ordered:
            if merged and merged[-1].t_ms == key.t_ms:
                merged[-1] = key
            else:
                merged.append(key)
        self.keys = tuple(merged)
        self._times = [key.t_ms for key in self.keys]
        self.base = base

    def value_at(self, t_ms: float) -> float:
        if not self.keys:
            return self.base
        i = bisect.bisect_right(self._times, t_ms) - 1
        if i < 0:
            return self.keys[0].value
        key = self.keys[i]
        if key.interpolation == "hold" or i + 1 >= len(self.keys):
            return key.value
        nxt = self.keys[i + 1]
        u = (t_ms - key.t_ms) / (nxt.t_ms - key.t_ms)
        return key.value + (nxt.value - key.value) * smoothstep(u)

    def sample(self, start_ms: int, end_ms: int, step_ms: int) -> list[float]:
        """Values at ``start, start + step, ...`` below ``end`` (for drawing a curve)."""
        return [self.value_at(t) for t in range(start_ms, end_ms, step_ms)]


@dataclass(frozen=True)
class ExpressionKey:
    t_ms: int
    expression: str
    manual: bool = True  # False for an auto-key from a line's emotion (decision 12)


class ExpressionLane:
    """The expression at a time: the latest key at or before it; at equal times a
    manual key beats a virtual (auto) one. ``None`` before the first key."""

    def __init__(self, keys: Sequence[ExpressionKey]) -> None:
        ordered = sorted(
            enumerate(keys), key=lambda item: (item[1].t_ms, item[1].manual, item[0])
        )
        merged: list[ExpressionKey] = []
        for _, key in ordered:
            if merged and merged[-1].t_ms == key.t_ms:
                merged[-1] = key  # manual sorts after virtual, so it wins
            else:
                merged.append(key)
        self.keys = tuple(merged)
        self._times = [key.t_ms for key in self.keys]

    def value_at(self, t_ms: float) -> str | None:
        i = bisect.bisect_right(self._times, t_ms) - 1
        return None if i < 0 else self.keys[i].expression
