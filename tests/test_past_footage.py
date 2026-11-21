"""Keys and reactions past the end of the footage (keyframes task, decision 4)."""

import pytest
from pydantic import ValidationError

from backend.edl.anchoring import anchored_items, item_timeline_ms, set_place
from backend.project.avatar_commands import (
    AddKeyframe,
    AddReaction,
    KeyLane,
    MoveKeyframe,
    MoveReaction,
    key_near,
    lane_value_at,
)
from backend.project.commands import CommandStack
from backend.project.cut_commands import RippleDelete, TrimClip
from backend.project.migrations import migrate
from backend.project.schema import SCHEMA_VERSION, Anchor, Keyframe, Project, Reaction
from backend.project.timeline import build_timeline
from tests.test_avatar_commands import CLIP_A, CLIP_B, K1, K2, R1, make_project

# make_project: footage runs 0..20 s on the timeline.
PAST = 25_000


def test_a_key_past_the_footage_keeps_its_timeline_time() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", PAST, 0.5, keyframe_id=K1))
    key = project.keyframes[0]
    assert (key.anchor, key.timeline_ms) == (None, PAST)
    assert item_timeline_ms(project.clips, key) == PAST
    stack.undo()
    assert project.keyframes == []
    stack.redo()
    assert project.keyframes[0].timeline_ms == PAST


def test_footage_edits_never_move_or_orphan_it() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", PAST, 0.5, keyframe_id=K1))
    stack.execute(AddReaction("hop", PAST + 500, reaction_id=R1))
    stack.execute(RippleDelete(2_000, 8_000))  # footage shrinks by 6 s
    stack.execute(TrimClip(CLIP_B, "out", 45_000))  # and grows over the key
    key, reaction = project.keyframes[0], project.reactions[0]
    assert (key.timeline_ms, key.orphaned) == (PAST, False)
    assert (reaction.timeline_ms, reaction.orphaned) == (PAST + 500, False)
    assert key not in anchored_items(project) and reaction not in anchored_items(project)


def test_a_move_decides_again() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", 1_000, 0.5, keyframe_id=K1))
    key = project.keyframes[0]
    stack.execute(MoveKeyframe(K1, PAST))
    assert (key.anchor, key.timeline_ms) == (None, PAST)
    stack.execute(MoveKeyframe(K1, 12_000))  # back onto footage: anchored
    assert key.anchor == Anchor(clip_id=CLIP_B, source_ms=22_000) and key.timeline_ms is None
    stack.undo()
    assert (key.anchor, key.timeline_ms) == (None, PAST)
    stack.undo()
    assert key.anchor == Anchor(clip_id=CLIP_A, source_ms=1_000)


def test_moving_an_orphan_past_the_footage_settles_it() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddReaction("shake", 1_000, reaction_id=R1))
    project.reactions[0].orphaned = True
    stack.execute(MoveReaction(R1, PAST))
    assert (project.reactions[0].timeline_ms, project.reactions[0].orphaned) == (PAST, False)
    stack.undo()
    assert project.reactions[0].orphaned and project.reactions[0].anchor is not None


def test_editing_and_evaluating_keys_past_the_footage() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", 19_000, 0.2, "linear", keyframe_id=K1))
    stack.execute(AddKeyframe("x", PAST, 0.8, keyframe_id=K2))
    assert lane_value_at(project, "x", 22_000) == pytest.approx(0.5)
    assert key_near(project, "x", PAST + 20).id == K2  # type: ignore[union-attr]
    stack.execute(KeyLane("x", PAST + 20, 0.9))  # edits that key, adds none
    assert [k.value for k in project.keyframes] == [0.2, 0.9]


def test_timeline_marks_them_pinned() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", PAST, 0.5, keyframe_id=K1))
    stack.execute(AddReaction("hop", 1_000, reaction_id=R1))
    state = build_timeline(project)
    key, reaction = state.keyframes[0], state.reactions[0]
    assert (key.t_ms, key.pinned, key.anchor_clip_id) == (PAST, True, None)
    assert (reaction.t_ms, reaction.pinned, reaction.anchor_clip_id) == (1_000, False, CLIP_A)


def test_schema_needs_exactly_one_place() -> None:
    anchor = Anchor(clip_id=CLIP_A, source_ms=0)
    with pytest.raises(ValidationError):
        Keyframe(id=K1, lane_id="x", value=0.5)
    with pytest.raises(ValidationError):
        Reaction(id=R1, type="hop", anchor=anchor, timeline_ms=5)
    key = Keyframe(id=K1, lane_id="x", value=0.5, anchor=anchor)
    set_place(key, PAST)
    assert (key.anchor, key.timeline_ms) == (None, PAST)
    with pytest.raises(ValueError):
        set_place(key, -1)


def test_v7_projects_open_and_pinned_items_round_trip() -> None:
    assert SCHEMA_VERSION >= 8
    key = {"id": K1, "lane_id": "x", "anchor": {"clip_id": CLIP_A, "source_ms": 0}, "value": 0.5}
    result = migrate({"schema_version": 7, "name": "x", "keyframes": [key]}, target=8)
    assert result["schema_version"] == 8
    project = Project.model_validate(migrate(result))
    assert project.keyframes[0].anchor is not None
    stack = CommandStack(project)
    stack.execute(AddReaction("hop", 99_000, reaction_id=R1))
    again = Project.model_validate_json(project.model_dump_json())
    assert again.reactions[0].timeline_ms == 99_000 and again.reactions[0].anchor is None
