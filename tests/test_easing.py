"""Key easing (keyframes task, decision 2): presets plus strength, schema v7."""

from itertools import pairwise

import pytest
from pydantic import TypeAdapter

from backend.avatar.lanes import INTERPOLATIONS, Lane, LaneKey, ease, smoothstep
from backend.project.avatar_commands import AddKeyframe, SetKeyframeInterpolation
from backend.project.commands import CommandError, CommandStack
from backend.project.edit_ops import EditOp, build_command
from backend.project.line_commands import NoChange
from backend.project.migrations import migrate
from backend.project.schema import SCHEMA_VERSION, Project
from tests.test_avatar_commands import K1, make_project

STEPS = [i / 20 for i in range(21)]
EASED = ("ease_in", "ease_out", "ease_in_out")


@pytest.mark.parametrize("kind", INTERPOLATIONS)
@pytest.mark.parametrize("strength", [0.0, 0.5, 1.0, 1.5, 2.0])
def test_every_curve_runs_from_0_to_1_and_never_falls(kind: str, strength: float) -> None:
    values = [ease(kind, u, strength) for u in STEPS]
    if kind == "hold":
        assert values == [0.0] * len(STEPS)
        return
    assert values[0] == pytest.approx(0.0) and values[-1] == pytest.approx(1.0)
    assert all(b >= a - 1e-12 for a, b in pairwise(values))
    assert all(0.0 <= v <= 1.0 for v in values)


def test_strength_1_is_the_normal_curve() -> None:
    for u in STEPS:
        assert ease("ease_in_out", u) == pytest.approx(smoothstep(u))  # the old smooth
        assert ease("ease_in", u) == pytest.approx(u * u)
        assert ease("ease_out", u) == pytest.approx(1 - (1 - u) ** 2)


def test_strength_0_is_linear_and_2_is_strong() -> None:
    for kind in EASED:
        assert ease(kind, 0.3, 0.0) == pytest.approx(0.3)
    assert ease("ease_in", 0.5, 2.0) == pytest.approx(0.125)
    assert ease("ease_out", 0.5, 2.0) == pytest.approx(0.875)
    assert ease("ease_in_out", 0.25, 2.0) == pytest.approx(0.103515625)  # smootherstep
    # Half way between normal and strong.
    assert ease("ease_in", 0.5, 1.5) == pytest.approx((0.25 + 0.125) / 2)


def test_strength_and_u_are_clamped() -> None:
    assert ease("ease_in", 0.5, 9.0) == ease("ease_in", 0.5, 2.0)
    assert ease("ease_in", 0.5, -1.0) == pytest.approx(0.5)
    assert ease("linear", -0.5) == 0.0 and ease("linear", 1.5) == 1.0


def test_lane_uses_the_keys_easing_and_strength() -> None:
    lane = Lane([LaneKey(0, 0.0, "ease_in", 2.0), LaneKey(1000, 10.0)], 0.0)
    assert lane.value_at(500) == pytest.approx(1.25)
    lane = Lane([LaneKey(0, 0.0, "linear"), LaneKey(1000, 10.0)], 0.0)
    assert lane.value_at(250) == pytest.approx(2.5)


def test_v6_smooth_keys_become_ease_in_out() -> None:
    assert SCHEMA_VERSION >= 7
    key = {"id": "a" * 12, "lane_id": "x", "anchor": {"clip_id": "b" * 12, "source_ms": 0}}
    data = {
        "schema_version": 6,
        "name": "x",
        "keyframes": [
            {**key, "value": 0.5, "interpolation": "smooth"},
            {**key, "id": "c" * 12, "value": 0.5, "interpolation": "hold"},
        ],
    }
    result = migrate(data, target=7)
    assert result["schema_version"] == 7
    assert data["keyframes"][0]["interpolation"] == "smooth"  # input untouched
    project = Project.model_validate(result)
    assert [(k.interpolation, k.ease_strength) for k in project.keyframes] == [
        ("ease_in_out", 1.0),
        ("hold", 1.0),
    ]


def test_set_easing_and_strength_undo() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", 12_000, 0.5, keyframe_id=K1))
    key = project.keyframes[0]
    stack.execute(SetKeyframeInterpolation(K1, "ease_out"))
    stack.execute(SetKeyframeInterpolation(K1, strength=1.6))
    assert (key.interpolation, key.ease_strength) == ("ease_out", 1.6)
    with pytest.raises(NoChange):
        SetKeyframeInterpolation(K1, "ease_out", 1.6).apply(project)
    stack.undo()
    assert (key.interpolation, key.ease_strength) == ("ease_out", 1.0)
    stack.undo()
    assert (key.interpolation, key.ease_strength) == ("ease_in_out", 1.0)


def test_bad_easing_is_refused() -> None:
    project = make_project()
    CommandStack(project).execute(AddKeyframe("x", 12_000, 0.5, keyframe_id=K1))
    with pytest.raises(CommandError):
        SetKeyframeInterpolation(K1)
    with pytest.raises(CommandError):
        SetKeyframeInterpolation(K1, strength=2.5)
    with pytest.raises(CommandError):
        SetKeyframeInterpolation(K1, "smooth").apply(project)  # type: ignore[arg-type]


def test_easing_op_parses() -> None:
    adapter = TypeAdapter(EditOp)
    op = adapter.validate_python(
        {"op": "set_keyframe_interpolation", "keyframe_id": K1, "ease_strength": 0.5}
    )
    command = build_command(op)
    assert isinstance(command, SetKeyframeInterpolation) and command.strength == 0.5
