"""Avatar keyframe, reaction and settings commands, ops, timeline state, auto-key
(M5-5 backend, S9)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from backend.app import create_app
from backend.avatar.art import parse_art, parse_config
from backend.avatar.autokey import auto_expression_keys
from backend.project.avatar_commands import (
    AddKeyframe,
    AddReaction,
    KeyLane,
    MoveKeyframe,
    MoveReaction,
    RemoveKeyframe,
    RemoveReaction,
    SetAvatarSettings,
    SetKeyframeInterpolation,
    SetKeyframeValue,
    SetReaction,
)
from backend.project.commands import CommandError, CommandStack
from backend.project.cut_commands import TrimClip
from backend.project.edit_ops import EditOp, build_command
from backend.project.line_commands import NoChange
from backend.project.schema import Anchor, Clip, Project, Source
from backend.project.session import Session
from backend.project.timeline import TimelinePlacement, build_timeline

SRC, CLIP_A, CLIP_B = "1" * 12, "2" * 12, "3" * 12
K1, K2, R1 = "a" * 12, "b" * 12, "c" * 12


def make_project() -> Project:
    """Two clips of the same 60 fps source: A is 0..10 s, B is 20..30 s (at 10 s)."""
    return Project(
        name="t",
        sources=[
            Source(
                id=SRC, path="footage/a.mkv", duration_ms=60_000, fps_num=60, width=1920, height=1080
            )
        ],
        clips=[
            Clip(id=CLIP_A, source_id=SRC, in_ms=0, out_ms=10_000),
            Clip(id=CLIP_B, source_id=SRC, in_ms=20_000, out_ms=30_000),
        ],
    )


# ---- keyframes ------------------------------------------------------------------------


def test_add_keyframe_anchors_to_footage_and_undoes() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", 12_000, 0.5, keyframe_id=K1))
    key = project.keyframes[0]
    assert key.anchor == Anchor(clip_id=CLIP_B, source_ms=22_000)
    assert key.interpolation == "smooth"  # transform keys ease by default
    stack.undo()
    assert project.keyframes == []
    stack.redo()
    assert project.keyframes[0].anchor.source_ms == 22_000


def test_keyframe_value_checks() -> None:
    project = make_project()
    with pytest.raises(CommandError):
        AddKeyframe("nope", 0, 1.0)
    with pytest.raises(CommandError):
        AddKeyframe("scale", 0, 99.0)
    with pytest.raises(CommandError):
        AddKeyframe("expression", 0, 1.0)
    with pytest.raises(CommandError):
        AddKeyframe("bounce", 0, "loud")
    with pytest.raises(CommandError):
        AddKeyframe("expression", 0, "smile", "smooth")
    with pytest.raises(CommandError):
        AddKeyframe("x", 25_000, 0.5).apply(project)  # past the footage
    key = AddKeyframe("expression", 0, " cheeky ")
    key.apply(project)
    assert project.keyframes[0].value == "cheeky"
    assert project.keyframes[0].interpolation == "hold"


def test_move_set_value_interpolation_remove() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("bounce", 1000, 1.0, keyframe_id=K1))
    stack.execute(MoveKeyframe(K1, 15_000))
    assert project.keyframes[0].anchor == Anchor(clip_id=CLIP_B, source_ms=25_000)
    stack.execute(SetKeyframeValue(K1, 2.5))
    stack.execute(SetKeyframeInterpolation(K1, "smooth"))
    assert (project.keyframes[0].value, project.keyframes[0].interpolation) == (2.5, "smooth")
    with pytest.raises(NoChange):
        SetKeyframeValue(K1, 2.5).apply(project)
    with pytest.raises(CommandError):
        SetKeyframeValue(K1, 9.0).apply(project)
    stack.execute(RemoveKeyframe(K1))
    assert project.keyframes == []
    for _ in range(4):
        stack.undo()
    key = project.keyframes[0]
    assert (key.value, key.interpolation, key.anchor.source_ms) == (1.0, "hold", 1000)


def test_key_lane_changes_the_key_already_there() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(KeyLane("x", 4000, 0.3, keyframe_id=K1))
    stack.execute(KeyLane("x", 4000, 0.6))
    stack.execute(KeyLane("y", 4000, 0.6, keyframe_id=K2))
    assert [(k.id, k.lane_id, k.value) for k in project.keyframes] == [
        (K1, "x", 0.6),
        (K2, "y", 0.6),
    ]
    stack.undo()
    stack.undo()
    assert [k.value for k in project.keyframes] == [0.3]


# ---- reactions ------------------------------------------------------------------------


def test_reaction_commands() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddReaction("hop", 3000, reaction_id=R1))
    reaction = project.reactions[0]
    assert (reaction.type, reaction.intensity, reaction.duration_ms) == ("hop", 1.0, 500)
    stack.execute(SetReaction(R1, type_="shake", intensity=2.0))
    stack.execute(MoveReaction(R1, 11_000))
    assert project.reactions[0].anchor == Anchor(clip_id=CLIP_B, source_ms=21_000)
    assert project.reactions[0].type == "shake"
    with pytest.raises(CommandError):
        SetReaction(R1, duration_ms=0).apply(project)
    with pytest.raises(CommandError):
        AddReaction("spin", 0)
    with pytest.raises(CommandError):
        AddReaction("hop", 0, intensity=9.0)
    stack.execute(RemoveReaction(R1))
    stack.undo()
    stack.undo()
    stack.undo()
    assert (project.reactions[0].type, project.reactions[0].anchor.source_ms) == ("hop", 3000)


# ---- cuts orphan keys and reactions (rule 4) ------------------------------------------


def test_a_cut_orphans_keys_and_reactions_and_undo_restores_them() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("expression", 2000, "cheeky", keyframe_id=K1))
    stack.execute(AddReaction("hop", 2000, reaction_id=R1))
    stack.execute(TrimClip(CLIP_A, "in", 5000))
    assert project.keyframes[0].orphaned and project.reactions[0].orphaned
    assert len(project.keyframes) == 1 and len(project.reactions) == 1  # never dropped
    state = build_timeline(project)
    assert state.orphan_count == 2
    stack.undo()
    assert not project.keyframes[0].orphaned
    assert project.keyframes[0].anchor.source_ms == 2000
    # Moving an orphan settles it.
    stack.redo()
    stack.execute(MoveKeyframe(K1, 1000))
    assert not project.keyframes[0].orphaned


# ---- settings -------------------------------------------------------------------------


def test_set_avatar_settings() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(SetAvatarSettings(x=0.5, scale=2.0, auto_key_expression=False))
    assert (project.avatar.x, project.avatar.scale) == (0.5, 2.0)
    assert project.avatar.auto_key_expression is False
    stack.undo()
    assert (project.avatar.x, project.avatar.scale) == (0.85, 1.0)
    assert project.avatar.auto_key_expression is True
    with pytest.raises(CommandError):
        SetAvatarSettings(scale=0.0)
    with pytest.raises(CommandError):
        SetAvatarSettings(colour=1.0)
    with pytest.raises(NoChange):
        SetAvatarSettings(x=0.85).apply(project)


# ---- ops and timeline state -----------------------------------------------------------


def test_ops_parse_and_build() -> None:
    adapter = TypeAdapter(EditOp)
    samples: list[dict[str, Any]] = [
        {"op": "add_keyframe", "lane_id": "x", "timeline_ms": 0, "value": 0.5},
        {"op": "key_lane", "lane_id": "expression", "timeline_ms": 0, "value": "smile"},
        {"op": "move_keyframe", "keyframe_id": K1, "timeline_ms": 5},
        {"op": "set_keyframe_value", "keyframe_id": K1, "value": 1.0},
        {"op": "set_keyframe_interpolation", "keyframe_id": K1, "interpolation": "hold"},
        {"op": "remove_keyframe", "keyframe_id": K1},
        {"op": "add_reaction", "type": "hop", "timeline_ms": 0},
        {"op": "move_reaction", "reaction_id": R1, "timeline_ms": 5},
        {"op": "set_reaction", "reaction_id": R1, "intensity": 0.5},
        {"op": "remove_reaction", "reaction_id": R1},
        {"op": "set_avatar_settings", "x": 0.4},
    ]
    for sample in samples:
        build_command(adapter.validate_python(sample))
    with pytest.raises(ValidationError):
        adapter.validate_python({"op": "add_reaction", "type": "hop", "timeline_ms": 0, "x": 1})


def test_timeline_state_lists_keys_and_reactions_by_time() -> None:
    project = make_project()
    AddKeyframe("x", 12_000, 0.5, keyframe_id=K1).apply(project)
    AddKeyframe("expression", 3000, "smile", keyframe_id=K2).apply(project)
    AddReaction("squish", 15_000, reaction_id=R1).apply(project)
    state = build_timeline(project)
    assert [(k.id, k.t_ms) for k in state.keyframes] == [(K2, 3000), (K1, 12_000)]
    assert state.reactions[0].t_ms == 15_000 and state.reactions[0].type == "squish"
    assert state.avatar.x == 0.85


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def test_batch_endpoint_is_one_undo_step(tmp_path: Path) -> None:
    session = Session(probe=fake_probe)
    session.new_project(str(tmp_path), "Rack")
    stack = session._stack
    assert stack is not None
    stack.project.sources.extend(make_project().sources)
    stack.project.clips.extend(make_project().clips)
    client = TestClient(create_app(session=session))
    body = client.post(
        "/api/timeline/batch",
        json={
            "label": "Move avatar",
            "ops": [
                {"op": "key_lane", "lane_id": "x", "timeline_ms": 4000, "value": 0.4},
                {"op": "key_lane", "lane_id": "y", "timeline_ms": 4000, "value": 0.6},
            ],
        },
    ).json()
    assert sorted(k["lane_id"] for k in body["keyframes"]) == ["x", "y"]
    assert body["undo_label"] == "Move avatar"
    undone = client.post("/api/timeline/undo").json()
    assert undone["timeline"]["keyframes"] == []
    bad = client.post(
        "/api/timeline/batch",
        json={"label": "x", "ops": [{"op": "add_keyframe", "lane_id": "scale", "timeline_ms": 0, "value": 50}]},
    )
    assert bad.status_code == 400


# ---- auto-key -------------------------------------------------------------------------


def placed(line_id: str, start: int | None, *, orphaned: bool = False) -> TimelinePlacement:
    return TimelinePlacement(
        id=line_id,
        line_id=line_id,
        line_text="",
        allow_overlap=False,
        take_id="t",
        duration_ms=1000,
        start_ms=start,
        end_ms=None,
        anchor_clip_id=CLIP_A,
        anchor_source_ms=0,
        orphaned=orphaned,
    )


def art(config: dict[str, Any] | None = None):
    files = {
        f"{i:02d}_{n}": [f"{i:02d}a_{n}_oicm.png"]
        for i, n in enumerate(["smile", "cheeky", "sad"], start=1)
    }
    return parse_art(files, parse_config(config))


PRESETS = {"neutral": "neutral", "excited": "excited", "disappointed": "sad"}


def test_auto_key_only_for_real_expressions() -> None:
    lines = {"l1": "neutral", "l2": "excited", "l3": "disappointed", "l4": "disappointed"}
    keys = auto_expression_keys(
        [placed("l3", 5000), placed("l1", 1000), placed("l2", 2000), placed("l4", 9000, orphaned=True)],
        lines,
        PRESETS,
        art(),
    )
    assert [(k.t_ms, k.expression, k.manual) for k in keys] == [(5000, "sad", False)]


def test_auto_key_uses_the_emotion_map_and_can_be_off() -> None:
    lines = {"l1": "excited"}
    with_map = art({"emotion_map": {"excited": "cheeky"}})
    assert [k.expression for k in auto_expression_keys([placed("l1", 0)], lines, PRESETS, with_map)] == [
        "cheeky"
    ]
    assert auto_expression_keys([placed("l1", 0)], lines, PRESETS, with_map, enabled=False) == []
    assert auto_expression_keys([placed("l1", 0)], lines, PRESETS, None) == []


def test_key_lane_by_adds_to_the_lane_value_there() -> None:
    from backend.project.avatar_commands import KeyLaneBy, lane_value_at

    project = make_project()
    stack = CommandStack(project)
    assert lane_value_at(project, "x", 3000) == 0.85  # no keys: the base
    stack.execute(KeyLaneBy("x", 3000, delta=-0.1))
    assert project.keyframes[0].value == pytest.approx(0.75)
    stack.execute(KeyLaneBy("scale", 3000, factor=1.5))
    stack.execute(KeyLaneBy("scale", 3000, factor=2.0))  # same spot: changes that key
    scales = [k.value for k in project.keyframes if k.lane_id == "scale"]
    assert scales == [3.0]
    stack.execute(KeyLaneBy("scale", 3000, factor=100.0))
    assert [k.value for k in project.keyframes if k.lane_id == "scale"] == [5.0]  # clamped
    stack.undo()
    stack.undo()
    assert [k.value for k in project.keyframes if k.lane_id == "scale"] == [1.5]
    with pytest.raises(CommandError):
        KeyLaneBy("expression", 0, delta=1).apply(project)
    with pytest.raises(CommandError):
        KeyLaneBy("x", 0, factor=0)
