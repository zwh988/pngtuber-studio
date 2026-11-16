"""The avatar solver (M5-3, M5-4): what the avatar looks like at any timeline time. Pure.

Rule 5: preview equals export. The browser canvas and the export compositor (M6) only
draw what this module returns, and it is a pure function of its input and the time.
Hysteresis, minimum hold, blinks and the bounce spring depend on the past, so
``build_solver`` precomputes them over the whole timeline once per input (in steps of
``SOLVER_STEP_MS``); ``Solver.query(t)`` is then a lookup, so asking for times in any
order gives exactly what stepping forward gives (seek accuracy, tested).

Input times are **timeline** ms: the caller maps keyframe, reaction and placement
anchors through the clip list and leaves orphans out. Envelopes are of the processed
takes as they play (stretch and trim included), starting at the placement's start.
Positions are fractions of the frame (x of the width, y of the height); see
``backend/avatar/tuning.py`` for every number.
"""

import bisect
import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from backend.avatar import tuning as T
from backend.avatar.envelope import Envelope
from backend.avatar.lanes import (
    LANES_BY_ID,
    ExpressionKey,
    ExpressionLane,
    Lane,
    LaneKey,
)

STEP = T.SOLVER_STEP_MS


@dataclass(frozen=True)
class PlacedVoice:
    start_ms: int  # timeline time the processed take starts playing
    envelope: Envelope


@dataclass(frozen=True)
class ReactionCue:
    t_ms: int
    type: str
    intensity: float = 1.0
    duration_ms: int = 500


@dataclass(frozen=True)
class BaseTransform:
    """``AvatarSettings``: each lane's value where it has no keys, and the float's
    direction (degrees; 0 = up and down, 90 = left and right)."""

    x: float = 0.85
    y: float = 0.75
    scale: float = 1.0
    rotation_deg: float = 0.0
    bounce: float = 1.0
    float_amp: float = 1.0
    float_speed: float = 1.0
    float_angle_deg: float = 0.0
    blink_rate: float = 1.0
    mouth_sensitivity: float = 1.0


@dataclass(frozen=True)
class SolverInput:
    duration_ms: int
    seed: int
    base: BaseTransform = field(default_factory=BaseTransform)
    lanes: Mapping[str, Sequence[LaneKey]] = field(default_factory=dict)
    expression_keys: Sequence[ExpressionKey] = ()
    default_expression: str | None = None
    voices: Sequence[PlacedVoice] = ()
    reactions: Sequence[ReactionCue] = ()


@dataclass(frozen=True)
class Frame:
    t_ms: float
    expression: str | None  # a name; the art lookup (sprite_for) picks the file
    eyes_open: bool
    mouth_open: bool
    x: float
    y: float
    scale: float
    rotation_deg: float
    squash: float  # width times (1 + squash), height times (1 - squash)


# --- reactions: a registry, like clip effects (rule 13) --------------------------------


@dataclass(frozen=True)
class Offset:
    dx: float = 0.0
    dy: float = 0.0
    scale_mul: float = 1.0
    rotation_deg: float = 0.0
    squash: float = 0.0


ReactionFn = Callable[[float, float], Offset]  # (progress 0..1, intensity) -> offset


def _shake(u: float, k: float) -> Offset:
    wave = math.sin(2 * math.pi * T.SHAKE_HZ * u * 0.5) * (1.0 - u)
    return Offset(dx=k * T.SHAKE_X * wave, rotation_deg=k * T.SHAKE_DEG * wave)


def _hop(u: float, k: float) -> Offset:
    return Offset(dy=-k * T.HOP_HEIGHT * math.sin(math.pi * u))


def _pop_in(u: float, k: float) -> Offset:
    c = T.POP_OVERSHOOT
    v = u - 1.0
    back = 1.0 + (c + 1.0) * v**3 + c * v**2  # 0 -> 1 with an overshoot
    return Offset(scale_mul=max(0.0, 1.0 + k * (back - 1.0)))


def _squish(u: float, k: float) -> Offset:
    return Offset(squash=k * T.SQUISH_AMOUNT * math.sin(math.pi * u) * (1.0 - u * 0.5))


REACTIONS: dict[str, ReactionFn] = {
    "shake": _shake,
    "hop": _hop,
    "pop_in": _pop_in,
    "squish": _squish,
}


# --- the solver -------------------------------------------------------------------------


def _lane(inp: SolverInput, lane_id: str) -> Lane:
    field_name = "rotation_deg" if lane_id == "rotation" else lane_id
    base = getattr(inp.base, field_name, LANES_BY_ID[lane_id].default)
    return Lane(inp.lanes.get(lane_id, ()), float(base))


def _track(lane: Lane, frames: int) -> np.ndarray:
    if not lane.keys:
        return np.full(frames, lane.base, dtype=np.float64)
    return np.array([lane.value_at(k * STEP) for k in range(frames)], dtype=np.float64)


def voice_level(voices: Sequence[PlacedVoice], frames: int) -> np.ndarray:
    """dBFS of the loudest line at each step (overlapping lines are mixed: the max)."""
    level = np.full(frames, T.ENVELOPE_FLOOR_DB, dtype=np.float64)
    for voice in voices:
        env = voice.envelope
        if not env.values:
            continue
        # Value j of the envelope covers [start + j * hop, start + (j + 1) * hop).
        times = np.arange(frames) * STEP - voice.start_ms
        idx = np.floor_divide(times, env.hop_ms)
        inside = (times >= 0) & (idx < len(env.values))
        values = np.asarray(env.values, dtype=np.float64)
        level[inside] = np.maximum(level[inside], values[idx[inside]])
    return level


def mouth_states(level: np.ndarray, sensitivity: np.ndarray) -> np.ndarray:
    """Open (True) or closed per step: opens at ``MOUTH_OPEN_DB``, closes below
    ``MOUTH_CLOSE_DB`` (hysteresis), and no state lasts under ``MOUTH_MIN_HOLD_MS``.
    Sensitivity s lowers both thresholds by 20 * log10(s) dB."""
    shift = 20.0 * np.log10(np.maximum(sensitivity, 1e-6))
    open_th = T.MOUTH_OPEN_DB - shift
    close_th = T.MOUTH_CLOSE_DB - shift
    out = np.zeros(level.size, dtype=bool)
    is_open = False
    held = math.inf
    for k in range(level.size):
        want = level[k] >= close_th[k] if is_open else level[k] >= open_th[k]
        if want != is_open and held >= T.MOUTH_MIN_HOLD_MS:
            is_open = want
            held = 0
        out[k] = is_open
        held += STEP
    return out


def blink_times(seed: int, rate: Lane, duration_ms: int) -> list[tuple[int, int]]:
    """Seeded blinks ``[start, end)``: a gap drawn between ``BLINK_GAP_MIN_MS`` and
    ``BLINK_GAP_MAX_MS`` divided by the blink rate where the gap starts."""
    rng = random.Random(f"{seed}:blink")
    out: list[tuple[int, int]] = []
    t = 0.0
    while t < duration_ms:
        r = rate.value_at(t)
        if r <= 0:
            t += T.BLINK_IDLE_STEP_MS
            continue
        t += rng.uniform(T.BLINK_GAP_MIN_MS, T.BLINK_GAP_MAX_MS) / r
        if t < duration_ms:
            start = int(t)
            out.append((start, start + T.BLINK_CLOSED_MS))
            t += T.BLINK_CLOSED_MS
    return out


def bounce_track(level: np.ndarray, bounce: np.ndarray) -> np.ndarray:
    """Upward lift (0 = rest, ~1 = full) of a damped spring chasing the voice level."""
    span = T.BOUNCE_LEVEL_CEIL_DB - T.BOUNCE_LEVEL_FLOOR_DB
    target = np.clip((level - T.BOUNCE_LEVEL_FLOOR_DB) / span, 0.0, 1.0) * bounce
    dt = STEP / 1000.0
    pos = vel = 0.0
    out = np.zeros(level.size, dtype=np.float64)
    for k in range(level.size):
        vel += (T.BOUNCE_STIFFNESS * (target[k] - pos) - T.BOUNCE_DAMPING * vel) * dt
        pos += vel * dt
        out[k] = pos
    return out


def float_phase(speed: np.ndarray) -> np.ndarray:
    """Cycles done at each step (the speed may change along the timeline)."""
    per_step = speed * T.FLOAT_BASE_HZ * STEP / 1000.0
    return np.concatenate([[0.0], np.cumsum(per_step)[:-1]])


class Solver:
    """Precomputed avatar state for one input; ``query(t)`` for any timeline time."""

    def __init__(self, inp: SolverInput) -> None:
        self.input = inp
        frames = max(1, -(-max(inp.duration_ms, 0) // STEP) + 1)
        self.frames = frames
        self._lanes = {lane_id: _lane(inp, lane_id) for lane_id in LANES_BY_ID if lane_id != "expression"}
        self._expr = ExpressionLane(inp.expression_keys)
        level = voice_level(inp.voices, frames)
        self._mouth = mouth_states(level, _track(self._lanes["mouth_sensitivity"], frames))
        self._blinks = blink_times(inp.seed, self._lanes["blink_rate"], inp.duration_ms)
        self._blink_starts = [b[0] for b in self._blinks]
        self._bounce = bounce_track(level, _track(self._lanes["bounce"], frames))
        self._amp = _track(self._lanes["float_amp"], frames)
        self._phase = float_phase(_track(self._lanes["float_speed"], frames))
        self._reactions = sorted(
            (r for r in inp.reactions if r.type in REACTIONS and r.duration_ms > 0),
            key=lambda r: (r.t_ms, r.type),
        )
        self._reaction_starts = [r.t_ms for r in self._reactions]
        self._longest = max((r.duration_ms for r in self._reactions), default=0)

    # -- pieces, each a lookup ------------------------------------------------------

    def _index(self, t: float) -> tuple[int, float]:
        pos = min(max(t, 0.0), (self.frames - 1) * STEP) / STEP
        k = min(int(pos), self.frames - 1)
        return k, pos - k

    def _interp(self, track: np.ndarray, t: float) -> float:
        k, frac = self._index(t)
        if k + 1 >= self.frames:
            return float(track[k])
        return float(track[k] + (track[k + 1] - track[k]) * frac)

    def mouth_open(self, t: float) -> bool:
        k, _ = self._index(t)
        return bool(self._mouth[k])

    def eyes_open(self, t: float) -> bool:
        i = bisect.bisect_right(self._blink_starts, t) - 1
        return not (i >= 0 and t < self._blinks[i][1])

    def expression(self, t: float) -> str | None:
        found = self._expr.value_at(t)
        return self.input.default_expression if found is None else found

    def reaction_offset(self, t: float) -> Offset:
        hi = bisect.bisect_right(self._reaction_starts, t)
        lo = bisect.bisect_left(self._reaction_starts, t - self._longest)
        dx = dy = rot = squash = 0.0
        scale = 1.0
        for cue in self._reactions[lo:hi]:
            u = (t - cue.t_ms) / cue.duration_ms
            if not 0.0 <= u < 1.0:
                continue
            off = REACTIONS[cue.type](u, cue.intensity)
            dx += off.dx
            dy += off.dy
            scale *= off.scale_mul
            rot += off.rotation_deg
            squash += off.squash
        return Offset(dx, dy, scale, rot, squash)

    def query(self, t: float) -> Frame:
        lanes = self._lanes
        k, _ = self._index(t)
        bounce = self._interp(self._bounce, t)
        phase = self._interp(self._phase, t)
        drift = float(self._amp[k]) * T.FLOAT_HEIGHT * math.sin(2 * math.pi * phase)
        angle = math.radians(self.input.base.float_angle_deg)
        # Drift along the float direction, the same distance in pixels either way.
        drift_x = drift * math.sin(angle) / T.FRAME_ASPECT
        drift_y = drift * math.cos(angle)
        react = self.reaction_offset(t)
        return Frame(
            t_ms=t,
            expression=self.expression(t),
            eyes_open=self.eyes_open(t),
            mouth_open=self.mouth_open(t),
            x=lanes["x"].value_at(t) + drift_x + react.dx,
            y=lanes["y"].value_at(t) - bounce * T.BOUNCE_HEIGHT + drift_y + react.dy,
            scale=max(0.0, lanes["scale"].value_at(t) * react.scale_mul),
            rotation_deg=lanes["rotation"].value_at(t) + react.rotation_deg,
            squash=react.squash,
        )

    @property
    def blinks(self) -> list[tuple[int, int]]:
        return list(self._blinks)

    def mouth_segments(self) -> list[tuple[int, int]]:
        """Open intervals ``[start, end)`` in ms (for tests and the lane UI)."""
        out: list[tuple[int, int]] = []
        start: int | None = None
        for k, is_open in enumerate(self._mouth):
            if is_open and start is None:
                start = k * STEP
            elif not is_open and start is not None:
                out.append((start, k * STEP))
                start = None
        if start is not None:
            out.append((start, self.frames * STEP))
        return out


def build_solver(inp: SolverInput) -> Solver:
    return Solver(inp)
