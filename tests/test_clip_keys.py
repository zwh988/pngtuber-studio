"""Keys on image lane clips: data and commands (keyframes task, step 5, schema v9)."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.project.clip_key_commands import (
    KeyLaneClip,
    MoveClipKey,
    RemoveClipKey,
    SetClipKey,
    clip_key_near,
)
from backend.project.commands import CommandError, CommandStack
from backend.project.edit_ops import EditOp, build_command
from backend.project.line_commands import NoChange
from backend.project.migrations import migrate
from backend.project.schema import SCHEMA_VERSION, ClipKey, LaneClip, Project
from backend.project.timeline import build_timeline
from backend.project.video_lane_commands import (
    AddLaneClip,
    MoveLaneClip,
    SplitLaneClip,
    TrimLaneClip,
)
from tests.test_video_lanes import B_ROLL, C1, C2, IMG, V2, hid, lane_clip, make_project

K1, K2 = hid(60), hid(61)


def with_image() -> tuple[Project, CommandStack]:
    """An image clip C1 on V2 from 1000 to 6000 ms."""
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddLaneClip(V2, 1000, image_id=IMG, clip_id=C1))
    return project, stack


def keys(project: Project, clip_id: str = C1) -> list[tuple[str, int, float]]:
    return [(k.prop, k.t_ms, k.value) for k in lane_clip(project, clip_id).keys]


def test_key_at_the_playhead_is_stored_from_the_clip_start() -> None:
    project, stack = with_image()
    stack.execute(KeyLaneClip(C1, "opacity", 1000, 0.0, key_id=K1))
    stack.execute(KeyLaneClip(C1, "opacity", 2000, 1.0, key_id=K2))
    assert keys(project) == [("opacity", 0, 0.0), ("opacity", 1000, 1.0)]
    assert lane_clip(project, C1).keys[0].interpolation == "linear"  # fades: linear
    stack.execute(KeyLaneClip(C1, "x", 1500, 0.2))
    assert lane_clip(project, C1).keys[0].prop == "x"  # sorted by property, then time
    assert lane_clip(project, C1).keys[0].interpolation == "ease_in_out"
    stack.undo()
    stack.undo()
    assert keys(project) == [("opacity", 0, 0.0)]


def test_a_key_one_frame_away_is_edited_not_added() -> None:
    project, stack = with_image()
    stack.execute(KeyLaneClip(C1, "x", 2000, 0.2, key_id=K1))
    stack.execute(KeyLaneClip(C1, "x", 2020, 0.4))
    assert keys(project) == [("x", 1000, 0.4)]
    assert clip_key_near(lane_clip(project, C1), "x", 1034) is not None
    assert clip_key_near(lane_clip(project, C1), "x", 1035) is None
    with pytest.raises(NoChange):
        stack.execute(KeyLaneClip(C1, "x", 2000, 0.4))


def test_keys_move_with_the_clip() -> None:
    project, stack = with_image()
    stack.execute(KeyLaneClip(C1, "y", 3000, 0.3, key_id=K1))
    stack.execute(MoveLaneClip(C1, 10_000))
    assert keys(project) == [("y", 2000, 0.3)]


def test_start_trim_keeps_keys_on_their_timeline_moment() -> None:
    project, stack = with_image()
    stack.execute(KeyLaneClip(C1, "x", 1500, 0.1, key_id=K1))
    stack.execute(KeyLaneClip(C1, "x", 3000, 0.9, key_id=K2))
    stack.execute(TrimLaneClip(C1, "start", 2000))
    # K1 is now before the clip start: kept (it still shapes the curve).
    assert keys(project) == [("x", -500, 0.1), ("x", 1000, 0.9)]
    stack.execute(TrimLaneClip(C1, "start", 1000))
    assert keys(project) == [("x", 500, 0.1), ("x", 2000, 0.9)]
    stack.execute(TrimLaneClip(C1, "end", 2000))  # an end trim changes nothing
    assert keys(project) == [("x", 500, 0.1), ("x", 2000, 0.9)]


def test_split_shares_the_keys_with_new_ids_the_same_on_redo() -> None:
    project, stack = with_image()
    stack.execute(KeyLaneClip(C1, "scale", 1000, 0.5, key_id=K1))
    stack.execute(KeyLaneClip(C1, "scale", 5000, 1.5, key_id=K2))
    stack.execute(SplitLaneClip(C1, 3000, right_clip_id=C2))
    assert keys(project, C1) == [("scale", 0, 0.5), ("scale", 4000, 1.5)]
    assert keys(project, C2) == [("scale", -2000, 0.5), ("scale", 2000, 1.5)]
    right_ids = [k.id for k in lane_clip(project, C2).keys]
    assert not set(right_ids) & {K1, K2}
    stack.undo()
    stack.redo()
    assert [k.id for k in lane_clip(project, C2).keys] == right_ids


def test_move_set_and_remove_a_key() -> None:
    project, stack = with_image()
    stack.execute(KeyLaneClip(C1, "x", 2000, 0.2, key_id=K1))
    stack.execute(KeyLaneClip(C1, "x", 4000, 0.8, key_id=K2))
    stack.execute(MoveClipKey(C1, K1, 1500))
    assert keys(project)[0] == ("x", 500, 0.2)
    with pytest.raises(CommandError):
        stack.execute(MoveClipKey(C1, K1, 7000))  # off the clip
    stack.execute(SetClipKey(C1, K1, value=0.3, interpolation="ease_out", ease_strength=2.0))
    key = lane_clip(project, C1).keys[0]
    assert (key.value, key.interpolation, key.ease_strength) == (0.3, "ease_out", 2.0)
    stack.execute(RemoveClipKey(C1, K1))
    assert lane_clip(project, C1).x == 0.5  # other x keys remain: value unchanged
    stack.execute(RemoveClipKey(C1, K2))
    assert lane_clip(project, C1).x == 0.8  # last x key: the clip keeps its value
    stack.undo()
    stack.undo()
    assert len(lane_clip(project, C1).keys) == 2 and lane_clip(project, C1).x == 0.5


def test_refusals() -> None:
    _, stack = with_image()
    with pytest.raises(CommandError):
        KeyLaneClip(C1, "rotation", 1000, 0.0)
    with pytest.raises(CommandError):
        KeyLaneClip(C1, "opacity", 1000, 1.5)
    with pytest.raises(CommandError):
        stack.execute(KeyLaneClip(C1, "x", 8000, 0.5))  # past the clip
    stack.execute(AddLaneClip(V2, 10_000, source_id=B_ROLL, clip_id=C2))
    with pytest.raises(CommandError):
        stack.execute(KeyLaneClip(C2, "x", 11_000, 0.5))  # a recording: not yet
    with pytest.raises(CommandError):
        SetClipKey(C1, K1)
    with pytest.raises(CommandError):
        stack.execute(SetClipKey(C1, K1, value=0.5))  # unknown key


def test_schema_checks() -> None:
    with pytest.raises(ValidationError):
        ClipKey(id=K1, prop="scale", t_ms=0, value=9.0)
    key = ClipKey(id=K1, prop="x", t_ms=0, value=0.5)
    with pytest.raises(ValidationError):
        LaneClip(id=C1, lane_id=V2, source_id=B_ROLL, timeline_ms=0, out_ms=1000, keys=[key])
    with pytest.raises(ValidationError):
        LaneClip(id=C1, lane_id=V2, image_id=IMG, timeline_ms=0, out_ms=1000, keys=[key, key])


def test_v8_projects_open_and_keys_reach_the_timeline() -> None:
    assert SCHEMA_VERSION == 9
    clip = {"id": C1, "lane_id": V2, "image_id": IMG, "timeline_ms": 0, "out_ms": 1000}
    result = migrate({"schema_version": 8, "name": "x", "lane_clips": [clip]})
    assert result["schema_version"] == 9 and result["lane_clips"][0]["keys"] == []
    project, stack = with_image()
    stack.execute(KeyLaneClip(C1, "opacity", 1200, 0.5, key_id=K1))
    state = build_timeline(project)
    assert [(k.id, k.t_ms) for k in state.lane_clips[0].keys] == [(K1, 200)]
    again = Project.model_validate_json(project.model_dump_json())
    assert again.lane_clips[0].keys[0].value == 0.5


def test_ops_build_the_commands() -> None:
    adapter = TypeAdapter(EditOp)
    ops = [
        {"op": "key_lane_clip", "clip_id": C1, "prop": "x", "timeline_ms": 0, "value": 0.5},
        {"op": "move_clip_key", "clip_id": C1, "key_id": K1, "timeline_ms": 10},
        {"op": "set_clip_key", "clip_id": C1, "key_id": K1, "ease_strength": 0.5},
        {"op": "remove_clip_key", "clip_id": C1, "key_id": K1},
    ]
    built = [type(build_command(adapter.validate_python(op))) for op in ops]
    assert built == [KeyLaneClip, MoveClipKey, SetClipKey, RemoveClipKey]
