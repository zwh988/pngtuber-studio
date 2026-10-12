"""Tests for backend/project/clip_commands.py (pure, no I/O)."""

import pytest

from backend.edl.timemap import clip_spans, timeline_duration, to_timeline
from backend.project.clip_commands import (
    AddClip,
    RemoveClip,
    ReorderClip,
    SetSpeed,
)
from backend.project.commands import CommandError, CommandStack
from backend.project.schema import (
    Anchor,
    Clip,
    Keyframe,
    Placement,
    Project,
    Reaction,
    Source,
)

SRC = "5" * 12
EXT = "6" * 12


def cid(n: int) -> str:
    return f"{n:012x}"


def make_source(
    source_id: str = SRC, *, duration_ms: int = 10_000, external: bool = False
) -> Source:
    path = "C:/templates/outro.mp4" if external else "footage/a.mkv"
    return Source(
        id=source_id,
        external=external,
        path=path,
        duration_ms=duration_ms,
        fps_num=60,
        fps_den=1,
        width=1920,
        height=1080,
    )


def make_clip(
    n: int,
    in_ms: int = 0,
    out_ms: int = 1000,
    *,
    speed: float = 1.0,
    track: int = 0,
    source_id: str = SRC,
    overlay: bool = True,
) -> Clip:
    return Clip(
        id=cid(n),
        source_id=source_id,
        in_ms=in_ms,
        out_ms=out_ms,
        speed=speed,
        track=track,
        overlay=overlay,
    )


def make_project(*clips: Clip, sources: list[Source] | None = None) -> Project:
    return Project(
        name="t",
        sources=sources if sources is not None else [make_source()],
        clips=list(clips),
    )


def ids(project: Project) -> list[str]:
    return [c.id for c in project.clips]


def add_anchored(project: Project, kind: str, clip_n: int) -> None:
    anchor = Anchor(clip_id=cid(clip_n), source_ms=500)
    if kind == "placement":
        project.placements.append(
            Placement(id=cid(50), line_id=cid(60), anchor=anchor)
        )
    elif kind == "keyframe":
        project.keyframes.append(
            Keyframe(id=cid(51), lane_id="expression", anchor=anchor, value="happy")
        )
    else:
        project.reactions.append(Reaction(id=cid(52), type="shake", anchor=anchor))


# --------------------------------------------------------------------------
# AddClip
# --------------------------------------------------------------------------


def test_add_clip_covers_whole_source() -> None:
    project = make_project()
    CommandStack(project).execute(AddClip(SRC, clip_id=cid(1)))
    clip = project.clips[0]
    assert (clip.id, clip.source_id) == (cid(1), SRC)
    assert (clip.in_ms, clip.out_ms, clip.speed) == (0, 10_000, 1.0)
    assert clip.track == 0
    assert clip.overlay is True


def test_add_clip_appends_at_end() -> None:
    project = make_project(make_clip(1))
    CommandStack(project).execute(AddClip(SRC, clip_id=cid(2)))
    assert ids(project) == [cid(1), cid(2)]


def test_add_clip_goes_before_trailing_bookend() -> None:
    outro = make_clip(9, 0, 5000, source_id=EXT, overlay=False)
    project = make_project(
        make_clip(1),
        outro,
        sources=[make_source(), make_source(EXT, duration_ms=5000, external=True)],
    )
    CommandStack(project).execute(AddClip(SRC, clip_id=cid(2)))
    assert ids(project) == [cid(1), cid(2), cid(9)]


def test_add_clip_explicit_position() -> None:
    project = make_project(make_clip(1), make_clip(2))
    CommandStack(project).execute(AddClip(SRC, position=0, clip_id=cid(3)))
    assert ids(project) == [cid(3), cid(1), cid(2)]


def test_add_clip_position_counts_track_zero_only() -> None:
    project = make_project(make_clip(1), make_clip(7, track=1), make_clip(2))
    stack = CommandStack(project)
    stack.execute(AddClip(SRC, position=1, clip_id=cid(3)))
    assert ids(project) == [cid(1), cid(7), cid(3), cid(2)]
    stack.execute(AddClip(SRC, position=3, clip_id=cid(4)))
    assert ids(project) == [cid(1), cid(7), cid(3), cid(2), cid(4)]


@pytest.mark.parametrize("position", [-1, 2])
def test_add_clip_position_out_of_range_refused(position: int) -> None:
    project = make_project(make_clip(1))
    before = project.model_dump()
    with pytest.raises(CommandError):
        CommandStack(project).execute(AddClip(SRC, position=position))
    assert project.model_dump() == before


def test_add_clip_unknown_source_refused() -> None:
    project = make_project()
    with pytest.raises(CommandError):
        CommandStack(project).execute(AddClip("9" * 12))
    assert project.clips == []


def test_add_clip_duplicate_id_refused() -> None:
    project = make_project(make_clip(1))
    with pytest.raises(CommandError):
        CommandStack(project).execute(AddClip(SRC, clip_id=cid(1)))
    assert ids(project) == [cid(1)]


def test_add_clip_shorter_than_one_frame_refused() -> None:
    project = make_project(sources=[make_source(duration_ms=10)])  # frame = 17 ms
    with pytest.raises(CommandError):
        CommandStack(project).execute(AddClip(SRC))
    assert project.clips == []


def test_add_clip_undo_redo_keeps_id() -> None:
    project = make_project(make_clip(1))
    stack = CommandStack(project)
    stack.execute(AddClip(SRC, clip_id=cid(2)))
    assert stack.undo() == "Add clip to timeline"
    assert ids(project) == [cid(1)]
    stack.redo()
    assert ids(project) == [cid(1), cid(2)]


# --------------------------------------------------------------------------
# RemoveClip
# --------------------------------------------------------------------------


def test_remove_clip_and_undo_restores_position() -> None:
    project = make_project(make_clip(1), make_clip(2), make_clip(3))
    stack = CommandStack(project)
    stack.execute(RemoveClip(cid(2)))
    assert ids(project) == [cid(1), cid(3)]
    stack.undo()
    assert ids(project) == [cid(1), cid(2), cid(3)]
    stack.redo()
    assert ids(project) == [cid(1), cid(3)]


def test_remove_clip_ripples_later_clips() -> None:
    project = make_project(make_clip(1, 0, 1000), make_clip(2, 0, 2000))
    CommandStack(project).execute(RemoveClip(cid(1)))
    assert to_timeline(project.clips, Anchor(clip_id=cid(2), source_ms=0)) == 0
    assert timeline_duration(project.clips) == 2000


def test_remove_clip_unknown_and_other_track_refused() -> None:
    project = make_project(make_clip(1), make_clip(7, track=1))
    stack = CommandStack(project)
    with pytest.raises(CommandError):
        stack.execute(RemoveClip(cid(99)))
    with pytest.raises(CommandError):
        stack.execute(RemoveClip(cid(7)))
    assert ids(project) == [cid(1), cid(7)]


# --------------------------------------------------------------------------
# SetSpeed
# --------------------------------------------------------------------------


def test_set_speed_ripples_and_undoes() -> None:
    project = make_project(make_clip(1, 0, 4000), make_clip(2, 0, 4000))
    stack = CommandStack(project)
    stack.execute(SetSpeed(cid(1), 2.0))
    assert project.clips[0].speed == 2.0
    assert [(s.start_ms, s.end_ms) for s in clip_spans(project.clips)] == [
        (0, 2000),
        (2000, 6000),
    ]
    stack.undo()
    assert project.clips[0].speed == 1.0
    assert timeline_duration(project.clips) == 8000
    stack.redo()
    assert project.clips[0].speed == 2.0


def test_set_speed_keeps_anchor_source_time() -> None:
    project = make_project(make_clip(1, 0, 4000), make_clip(2, 0, 4000))
    add_anchored(project, "placement", 2)
    original = project.placements[0].anchor.model_copy()
    CommandStack(project).execute(SetSpeed(cid(1), 2.0))
    assert project.placements[0].anchor == original
    # Clip 2 now starts at 2000, so source 500 is at 2500 on the timeline.
    assert to_timeline(project.clips, original) == 2500


@pytest.mark.parametrize("speed", [0.2, 8.5, -1.0])
def test_set_speed_out_of_range_refused(speed: float) -> None:
    project = make_project(make_clip(1))
    before = project.model_dump()
    with pytest.raises(CommandError):
        CommandStack(project).execute(SetSpeed(cid(1), speed))
    assert project.model_dump() == before


def test_set_speed_same_value_refused() -> None:
    project = make_project(make_clip(1))
    stack = CommandStack(project)
    with pytest.raises(CommandError):
        stack.execute(SetSpeed(cid(1), 1.0))
    assert not stack.can_undo


def test_set_speed_accepts_limits() -> None:
    project = make_project(make_clip(1), make_clip(2))
    stack = CommandStack(project)
    stack.execute(SetSpeed(cid(1), 0.25))
    stack.execute(SetSpeed(cid(2), 8.0))
    assert [c.speed for c in project.clips] == [0.25, 8.0]


def test_set_speed_unknown_and_other_track_refused() -> None:
    project = make_project(make_clip(1), make_clip(7, track=1))
    stack = CommandStack(project)
    with pytest.raises(CommandError):
        stack.execute(SetSpeed(cid(99), 2.0))
    with pytest.raises(CommandError):
        stack.execute(SetSpeed(cid(7), 2.0))


# --------------------------------------------------------------------------
# ReorderClip
# --------------------------------------------------------------------------


def test_reorder_keeps_anchor_and_moves_timeline_time() -> None:
    project = make_project(make_clip(1, 0, 1000), make_clip(2, 0, 2000))
    add_anchored(project, "placement", 1)
    original = project.placements[0].anchor.model_copy()
    stack = CommandStack(project)
    assert to_timeline(project.clips, original) == 500
    stack.execute(ReorderClip(cid(1), 1))
    assert ids(project) == [cid(2), cid(1)]
    assert project.placements[0].anchor == original
    assert to_timeline(project.clips, original) == 2500
    stack.undo()
    assert ids(project) == [cid(1), cid(2)]
    assert to_timeline(project.clips, original) == 500
    stack.redo()
    assert ids(project) == [cid(2), cid(1)]


def test_reorder_middle_to_front_and_back() -> None:
    project = make_project(make_clip(1), make_clip(2), make_clip(3))
    stack = CommandStack(project)
    stack.execute(ReorderClip(cid(3), 0))
    assert ids(project) == [cid(3), cid(1), cid(2)]
    stack.execute(ReorderClip(cid(3), 1))
    assert ids(project) == [cid(1), cid(3), cid(2)]
    stack.undo()
    stack.undo()
    assert ids(project) == [cid(1), cid(2), cid(3)]


def test_reorder_same_position_refused() -> None:
    project = make_project(make_clip(1), make_clip(2))
    stack = CommandStack(project)
    with pytest.raises(CommandError):
        stack.execute(ReorderClip(cid(2), 1))
    assert not stack.can_undo


@pytest.mark.parametrize("position", [-1, 2])
def test_reorder_out_of_range_refused(position: int) -> None:
    project = make_project(make_clip(1), make_clip(2))
    before = project.model_dump()
    with pytest.raises(CommandError):
        CommandStack(project).execute(ReorderClip(cid(1), position))
    assert project.model_dump() == before


def test_reorder_preserves_other_track_clips() -> None:
    project = make_project(make_clip(1), make_clip(7, track=1), make_clip(2))
    stack = CommandStack(project)
    stack.execute(ReorderClip(cid(2), 0))
    timeline = [c.id for c in project.clips if c.track == 0]
    assert timeline == [cid(2), cid(1)]
    assert cid(7) in ids(project)
    assert next(c for c in project.clips if c.id == cid(7)).track == 1
    stack.undo()
    assert ids(project) == [cid(1), cid(7), cid(2)]


def test_reorder_unknown_and_other_track_refused() -> None:
    project = make_project(make_clip(1), make_clip(7, track=1))
    stack = CommandStack(project)
    with pytest.raises(CommandError):
        stack.execute(ReorderClip(cid(99), 0))
    with pytest.raises(CommandError):
        stack.execute(ReorderClip(cid(7), 0))


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------


def test_group_add_and_speed_undo_as_one_step() -> None:
    project = make_project()
    stack = CommandStack(project)
    with stack.group("Add fast clip"):
        stack.execute(AddClip(SRC, clip_id=cid(1)))
        stack.execute(SetSpeed(cid(1), 2.0))
    assert project.clips[0].speed == 2.0
    assert stack.undo() == "Add fast clip"
    assert project.clips == []
    stack.redo()
    assert [(c.id, c.speed) for c in project.clips] == [(cid(1), 2.0)]
