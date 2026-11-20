"""Editing keys near the playhead (keyframes task, decision 1)."""

from backend.project.avatar_commands import (
    KEY_NEAR_MS,
    AddKeyframe,
    KeyLane,
    KeyLaneBy,
    key_near,
)
from backend.project.commands import CommandStack
from tests.test_avatar_commands import K1, K2, make_project


def test_key_near_finds_the_closest_key_within_a_frame() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", 1000, 0.5, keyframe_id=K1))
    stack.execute(AddKeyframe("x", 1050, 0.6, keyframe_id=K2))
    assert key_near(project, "x", 1000 - KEY_NEAR_MS).id == K1  # type: ignore[union-attr]
    assert key_near(project, "x", 1030).id == K2  # type: ignore[union-attr]
    assert key_near(project, "x", 1000 - KEY_NEAR_MS - 1) is None
    assert key_near(project, "y", 1000) is None  # other lane


def test_key_lane_edits_a_key_one_frame_away_instead_of_adding() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", 1000, 0.5, keyframe_id=K1))
    stack.execute(KeyLane("x", 1020, 0.7))
    assert [(k.id, k.value) for k in project.keyframes] == [(K1, 0.7)]
    assert project.keyframes[0].anchor.source_ms == 1000  # the key did not move
    stack.undo()
    assert project.keyframes[0].value == 0.5
    stack.execute(KeyLane("x", 1100, 0.7))  # three frames away: a new key
    assert len(project.keyframes) == 2


def test_drag_adds_to_the_keys_own_value() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", 1000, 0.5, keyframe_id=K1))
    stack.execute(AddKeyframe("x", 2000, 0.9, keyframe_id=K2))
    stack.execute(KeyLaneBy("x", 1030, delta=0.1))
    assert len(project.keyframes) == 2
    assert project.keyframes[0].value == 0.6


def test_orphaned_keys_are_never_the_key_there() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddKeyframe("x", 1000, 0.5, keyframe_id=K1))
    project.keyframes[0].orphaned = True
    assert key_near(project, "x", 1000) is None
