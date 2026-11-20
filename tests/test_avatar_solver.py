"""Lanes and the avatar solver (M5-3, M5-4, M5-8): determinism, seek accuracy,
hysteresis and minimum hold, blinks, motion, reactions."""

import itertools
import random

import pytest

from backend.avatar import tuning as T
from backend.avatar.envelope import Envelope
from backend.avatar.lanes import (
    LANES,
    ExpressionKey,
    ExpressionLane,
    Lane,
    LaneKey,
    clamp_lane,
    smoothstep,
)
from backend.avatar.solver import (
    REACTIONS,
    BaseTransform,
    PlacedVoice,
    ReactionCue,
    SolverInput,
    build_solver,
    mouth_states,
)

LOUD, QUIET = -20.0, -60.0


def env(*pattern: tuple[float, int]) -> Envelope:
    """An envelope from (dB, ms) runs, ms a multiple of 10."""
    values: list[float] = []
    for db, ms in pattern:
        values.extend([db] * (ms // 10))
    return Envelope(10, tuple(values))


def busy_input(seed: int = 7) -> SolverInput:
    return SolverInput(
        duration_ms=20_000,
        seed=seed,
        base=BaseTransform(0.8, 0.7, 1.2, 5.0),
        lanes={
            "x": [LaneKey(2000, 0.5, "ease_in_out"), LaneKey(6000, 0.2)],
            "bounce": [LaneKey(0, 2.0)],
            "blink_rate": [LaneKey(10_000, 2.0)],
        },
        expression_keys=[ExpressionKey(3000, "cheeky"), ExpressionKey(9000, "angry")],
        default_expression="smile",
        voices=[
            PlacedVoice(1000, env((QUIET, 100), (LOUD, 800), (QUIET, 300), (LOUD, 500))),
            PlacedVoice(8000, env((LOUD, 2000))),
        ],
        reactions=[ReactionCue(5000, "shake"), ReactionCue(12_000, "hop", 0.5, 800)],
    )


# ---- lanes ------------------------------------------------------------------------


def test_lane_table() -> None:
    ids = [lane.id for lane in LANES]
    assert ids == [
        "expression", "bounce", "float_amp", "float_speed", "blink_rate",
        "mouth_sensitivity", "scale", "x", "y", "rotation",
    ]
    assert clamp_lane("scale", 99) == 5.0
    assert clamp_lane("mouth_sensitivity", 0) == 0.25


def test_lane_hold_smooth_and_ends() -> None:
    lane = Lane([LaneKey(1000, 1.0, "ease_in_out"), LaneKey(2000, 3.0), LaneKey(3000, 0.0)], 9.0)
    assert lane.value_at(0) == 1.0  # before the first key: the first value
    assert lane.value_at(1000) == 1.0
    assert lane.value_at(1500) == pytest.approx(2.0)  # smoothstep midpoint
    assert lane.value_at(1250) == pytest.approx(1.0 + 2.0 * smoothstep(0.25))
    assert lane.value_at(2500) == 3.0  # hold
    assert lane.value_at(99_999) == 0.0
    assert Lane([], 9.0).value_at(5) == 9.0
    assert lane.sample(0, 3001, 1000) == [1.0, 1.0, 3.0, 0.0]


def test_lane_keys_at_the_same_time_last_wins() -> None:
    lane = Lane([LaneKey(1000, 1.0), LaneKey(1000, 2.0)], 0.0)
    assert lane.value_at(1000) == 2.0


def test_expression_lane_manual_beats_virtual() -> None:
    lane = ExpressionLane(
        [ExpressionKey(1000, "cheeky", manual=True), ExpressionKey(1000, "sad", manual=False)]
    )
    assert lane.value_at(999) is None
    assert lane.value_at(1000) == "cheeky"
    lane2 = ExpressionLane([ExpressionKey(0, "a", manual=False), ExpressionKey(500, "b", False)])
    assert lane2.value_at(700) == "b"


# ---- determinism and seek accuracy (M5-8) ---------------------------------------


def test_same_input_same_frames() -> None:
    a, b = build_solver(busy_input()), build_solver(busy_input())
    for t in range(0, 20_000, 37):
        assert a.query(t) == b.query(t)


def test_query_order_does_not_matter() -> None:
    solver = build_solver(busy_input())
    times = [t * 7.5 for t in range(2666)]
    forward = [solver.query(t) for t in times]
    shuffled = times[:]
    random.Random(1).shuffle(shuffled)
    by_time = {t: solver.query(t) for t in shuffled}
    assert [by_time[t] for t in times] == forward
    # A fresh solver asked only for one late time agrees with stepping through.
    assert build_solver(busy_input()).query(15_002.5) == solver.query(15_002.5)


def test_another_seed_moves_the_blinks_only() -> None:
    a, b = build_solver(busy_input(1)), build_solver(busy_input(2))
    assert a.blinks != b.blinks
    assert a.mouth_segments() == b.mouth_segments()


# ---- mouth: hysteresis and minimum hold ------------------------------------------


def test_mouth_follows_the_voice() -> None:
    solver = build_solver(busy_input())
    assert not solver.mouth_open(500)
    assert solver.mouth_open(1150)  # loud from 1100
    assert solver.mouth_open(1850)
    assert not solver.mouth_open(2100)  # quiet 1900..2200
    assert solver.mouth_open(8500)
    assert not solver.mouth_open(10_500)
    assert solver.mouth_segments()[0][0] == 1100


def test_hysteresis_keeps_the_mouth_open_between_the_thresholds() -> None:
    between = (T.MOUTH_OPEN_DB + T.MOUTH_CLOSE_DB) / 2
    level = [QUIET] * 5 + [LOUD] * 10 + [between] * 20 + [QUIET] * 10
    import numpy as np

    states = mouth_states(np.array(level), np.ones(len(level)))
    assert not states[4]
    assert states[5]
    assert all(states[5:35])  # "between" never opens it, but keeps it open
    assert not states[35]
    states2 = mouth_states(np.array([QUIET] * 5 + [between] * 20), np.ones(25))
    assert not any(states2)


def test_minimum_hold_stops_flicker() -> None:
    import numpy as np

    # Loud for 10 ms, quiet for 10 ms, repeated: the mouth may change at most every
    # MOUTH_MIN_HOLD_MS.
    level = np.array([LOUD, QUIET] * 50)
    states = mouth_states(level, np.ones(level.size))
    runs: list[int] = []
    current, length = states[0], 0
    for s in states:
        if s == current:
            length += 1
        else:
            runs.append(length)
            current, length = s, 1
    assert runs  # it does change
    assert all(run * T.SOLVER_STEP_MS >= T.MOUTH_MIN_HOLD_MS for run in runs[1:])


def test_sensitivity_lowers_the_thresholds() -> None:
    import numpy as np

    level = np.array([T.MOUTH_OPEN_DB - 6.0] * 20)
    assert not any(mouth_states(level, np.ones(20)))
    assert all(mouth_states(level, np.full(20, 2.0))[1:])  # +6 dB of sensitivity


def test_overlapping_voices_mix_by_the_loudest() -> None:
    inp = SolverInput(
        duration_ms=3000,
        seed=1,
        voices=[PlacedVoice(0, env((LOUD, 1000))), PlacedVoice(500, env((QUIET, 1500)))],
    )
    solver = build_solver(inp)
    assert solver.mouth_open(900)
    assert not solver.mouth_open(1500)


# ---- blink ------------------------------------------------------------------------


def test_blinks_are_believable_and_follow_the_rate() -> None:
    solver = build_solver(SolverInput(duration_ms=120_000, seed=3))
    blinks = solver.blinks
    gaps = [b[0] - a[1] for a, b in itertools.pairwise(blinks)]
    assert 15 <= len(blinks) <= 60  # one every 2 to 6 s
    assert all(gap >= T.BLINK_GAP_MIN_MS - T.BLINK_CLOSED_MS for gap in gaps)
    start, end = blinks[0]
    assert not solver.eyes_open(start)
    assert not solver.eyes_open(end - 1)
    assert solver.eyes_open(end)
    fast = build_solver(
        SolverInput(duration_ms=120_000, seed=3, lanes={"blink_rate": [LaneKey(0, 3.0)]})
    )
    assert len(fast.blinks) > 2 * len(blinks)
    none = build_solver(
        SolverInput(duration_ms=60_000, seed=3, lanes={"blink_rate": [LaneKey(0, 0.0)]})
    )
    assert none.blinks == []


# ---- expression, transform, motion, reactions --------------------------------------


def test_expression_and_default() -> None:
    solver = build_solver(busy_input())
    assert solver.query(0).expression == "smile"
    assert solver.query(3000).expression == "cheeky"
    assert solver.query(9500).expression == "angry"


def test_transform_lanes_use_the_base_and_keys() -> None:
    quiet = SolverInput(
        duration_ms=10_000,
        seed=1,
        base=BaseTransform(0.8, 0.7, 1.2, 5.0),
        lanes={"float_amp": [LaneKey(0, 0.0)], "x": [LaneKey(2000, 0.5, "ease_in_out"), LaneKey(6000, 0.2)]},
    )
    solver = build_solver(quiet)
    frame = solver.query(1000)
    assert (frame.x, frame.y, frame.scale, frame.rotation_deg) == (0.5, 0.7, 1.2, 5.0)
    assert solver.query(4000).x == pytest.approx(0.35)
    assert solver.query(8000).x == 0.2


def test_bounce_lifts_while_speaking_and_settles() -> None:
    inp = SolverInput(
        duration_ms=6000,
        seed=1,
        lanes={"float_amp": [LaneKey(0, 0.0)]},
        voices=[PlacedVoice(1000, env((LOUD, 1000)))],
    )
    solver = build_solver(inp)
    rest = solver.query(500).y
    assert rest == pytest.approx(0.75)
    assert solver.query(1600).y < rest - 0.01  # lifted (y up is smaller)
    assert solver.query(5500).y == pytest.approx(rest, abs=1e-4)  # settled
    flat = build_solver(
        SolverInput(
            duration_ms=6000,
            seed=1,
            lanes={"float_amp": [LaneKey(0, 0.0)], "bounce": [LaneKey(0, 0.0)]},
            voices=inp.voices,
        )
    )
    assert flat.query(1600).y == pytest.approx(rest)


def test_float_drifts_within_its_amplitude() -> None:
    solver = build_solver(SolverInput(duration_ms=10_000, seed=1))
    ys = [solver.query(t).y for t in range(0, 10_000, 50)]
    assert max(ys) - min(ys) == pytest.approx(2 * T.FLOAT_HEIGHT, rel=0.05)


def test_reactions_play_once_and_end_at_rest() -> None:
    assert set(REACTIONS) == {"shake", "hop", "pop_in", "squish"}
    for kind in REACTIONS:
        inp = SolverInput(
            duration_ms=4000,
            seed=1,
            lanes={"float_amp": [LaneKey(0, 0.0)]},
            reactions=[ReactionCue(1000, kind, 1.0, 600)],
        )
        solver = build_solver(inp)
        before, after = solver.query(999), solver.query(1600)
        during = [solver.query(t) for t in range(1000, 1600, 20)]
        rest = (before.x, before.y, before.scale, before.rotation_deg, before.squash)
        assert (after.x, after.y, after.scale, after.rotation_deg, after.squash) == rest
        assert any(
            (f.x, f.y, f.scale, f.rotation_deg, f.squash) != rest for f in during
        ), kind
    pop = build_solver(SolverInput(duration_ms=2000, seed=1, reactions=[ReactionCue(0, "pop_in")]))
    assert pop.query(0).scale == pytest.approx(0.0)
    assert max(pop.query(t).scale for t in range(0, 500, 10)) > 1.0  # overshoot


def test_unknown_reactions_are_ignored() -> None:
    solver = build_solver(
        SolverInput(duration_ms=2000, seed=1, reactions=[ReactionCue(0, "spin")])
    )
    assert solver.query(100).rotation_deg == 0.0


def test_times_outside_the_timeline_are_safe() -> None:
    solver = build_solver(busy_input())
    assert solver.query(-50).expression == "smile"
    assert solver.query(25_000).mouth_open is False
    empty = build_solver(SolverInput(duration_ms=0, seed=0))
    assert empty.query(0).expression is None


def test_float_direction_and_base_motion_settings() -> None:
    import math

    def drift(angle: float) -> tuple[float, float]:
        solver = build_solver(
            SolverInput(duration_ms=8000, seed=1, base=BaseTransform(float_angle_deg=angle))
        )
        xs = [solver.query(t).x for t in range(0, 8000, 50)]
        ys = [solver.query(t).y for t in range(0, 8000, 50)]
        return max(xs) - min(xs), max(ys) - min(ys)

    up = drift(0.0)
    side = drift(90.0)
    assert up[0] == pytest.approx(0.0, abs=1e-6) and up[1] > 0.015
    assert side[1] == pytest.approx(0.0, abs=1e-6)
    assert side[0] == pytest.approx(up[1] / T.FRAME_ASPECT, rel=0.05)
    still = build_solver(SolverInput(duration_ms=4000, seed=1, base=BaseTransform(float_amp=0.0)))
    assert len({still.query(t).y for t in range(0, 4000, 100)}) == 1
    no_blinks = build_solver(SolverInput(duration_ms=60_000, seed=1, base=BaseTransform(blink_rate=0.0)))
    assert no_blinks.blinks == []
    assert math.isfinite(drift(45.0)[0])
