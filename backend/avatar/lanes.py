"""Avatar lanes (M5-5 core): fixed lane ids, ranges, defaults, and evaluation. Pure.

A lane is a list of keys in **timeline** time (the caller maps anchors through the clip
list first; orphaned keys are left out). A key's ``interpolation`` describes the segment
from that key to the next one: ``hold`` keeps its value, the others move to the next
value along an easing curve (``ease``) shaped by the key's ``strength`` (schema v7,
keyframes decision 2). Before the first key the first value holds, after the last the last
value holds; a lane without keys gives its base value (``AvatarSettings`` for the
transform lanes, the lane default otherwise).

The expression lane holds expression names and is always ``hold``.
"""

import bisect
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Interpolation = Literal["hold", "linear", "ease_in", "ease_out", "ease_in_out"]
INTERPOLATIONS: tuple[str, ...] = ("hold", "linear", "ease_in", "ease_out", "ease_in_out")

# Ease strength (keyframes decision 2): 0 is linear, 1 normal (quadratic in and out,
# smoothstep in-out: the old ``smooth``), 2 strong (cubic, smootherstep).
EASE_STRENGTH_MIN = 0.0
EASE_STRENGTH_MAX = 2.0
EASE_STRENGTH_DEFAULT = 1.0


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
    strength: float = EASE_STRENGTH_DEFAULT


def clamp_lane(lane_id: str, value: float) -> float:
    spec = LANES_BY_ID[lane_id]
    return min(spec.maximum, max(spec.minimum, value))


def smoothstep(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3.0 - 2.0 * u)


def _curve(kind: str, u: float, power: int) -> float:
    """The full-strength curve of an easing kind: ``power`` 2 normal, 3 strong."""
    if kind == "ease_in":
        return u**power
    if kind == "ease_out":
        return 1.0 - (1.0 - u) ** power
    if power == 2:
        return smoothstep(u)
    return u * u * u * (u * (6.0 * u - 15.0) + 10.0)  # smootherstep


def ease(kind: str, u: float, strength: float = EASE_STRENGTH_DEFAULT) -> float:
    """Progress (0 to 1) along a segment at fraction ``u``. ``hold`` stays at 0 until
    the next key; ``linear`` is ``u``; the ease kinds blend linear (strength 0) into the
    normal curve (1) and that into the strong curve (2). Blends of rising curves rise,
    so every curve is monotonic and never overshoots."""
    u = min(1.0, max(0.0, u))
    if kind == "hold":
        return 0.0
    if kind == "linear":
        return u
    s = min(EASE_STRENGTH_MAX, max(EASE_STRENGTH_MIN, strength))
    normal = _curve(kind, u, 2)
    if s <= 1.0:
        return u + (normal - u) * s
    return normal + (_curve(kind, u, 3) - normal) * (s - 1.0)


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
        progress = ease(key.interpolation, u, key.strength)
        return key.value + (nxt.value - key.value) * progress

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
