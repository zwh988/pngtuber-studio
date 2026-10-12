"""Tests for backend/project/cut_commands.py (pure, no I/O).

Test footage is 60 fps, so one frame is 16.67 ms. Multiples of 50 ms land
exactly on the frame grid; 1008 snaps to 1000 and 1010 snaps to 1017.
"""

import pytest

from backend.edl.timemap import clip_spans, timeline_duration, to_timeline
from backend.project.commands import CommandError, CommandStack
from backend.project.cut_commands import RippleDelete, SplitClip, TrimClip
from backend.project.schema import (
    Anchor,
    Clip,
    EffectSpec,
    Keyframe,
    Placement,
    Project,
    Reaction,
    Source,
)

SRC = "5" * 12


def cid(n: int) -> str:
    return f"{n:012x}"


def make_source(*, duration_ms: int = 10_000) -> Source:
    return Source(
        id=SRC,
        path="footage/a.mkv",
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
    effects: list[EffectSpec] | None = None,
) -> Clip:
    return Clip(
        id=cid(n),
        source_id=SRC,
        in_ms=in_ms,
        out_ms=out_ms,
        speed=speed,
        track=track,
        effects=effects or [],
    )


def make_project(*clips: Clip, duration_ms: int = 10_000) -> Project:
    return Project(
        name="t",
        sources=[make_source(duration_ms=duration_ms)],
        clips=list(clips),
    )


def two_clips() -> Project:
    """A: source 0..4000 (timeline 0-4000), B: source 0..2000 (timeline 4000-6000)."""
    return make_project(make_clip(1, 0, 4000), make_clip(2, 0, 2000))


def layout(project: Project) -> list[tuple[str, int, int]]:
    return [(c.id, c.in_ms, c.out_ms) for c in project.clips]


def spans(project: Project) -> list[tuple[int, int]]:
    return [(s.start_ms, s.end_ms) for s in clip_spans(project.clips)]


def add_item(project: Project, kind: str, clip_n: int, source_ms: int, n: int) -> None:
    anchor = Anchor(clip_id=cid(clip_n), source_ms=source_ms)
    if kind == "placement":
        project.placements.append(
            Placement(id=cid(n), line_id=cid(60), anchor=anchor)
        )
    elif kind == "keyframe":
        project.keyframes.append(
            Keyframe(id=cid(n), lane_id="expression", anchor=anchor, value="happy")
        )
    else:
        project.reactions.append(Reaction(id=cid(n), type="shake", anchor=anchor))


def anchors_of(project: Project) -> list[tuple[str, int]]:
    items = (*project.placements, *project.keyframes, *project.reactions)
    return [(i.anchor.clip_id, i.anchor.source_ms) for i in items]


# --------------------------------------------------------------------------
# SplitClip
# --------------------------------------------------------------------------


def test_split_makes_two_clips_without_changing_timeline_length() -> None:
    project = make_project(make_clip(1, 0, 4000))
    CommandStack(project).execute(SplitClip(1000, right_clip_id=cid(2)))
    assert layout(project) == [(cid(1), 0, 1000), (cid(2), 1000, 4000)]
    assert spans(project) == [(0, 1000), (1000, 4000)]
    assert timeline_duration(project.clips) == 4000
    left, right = project.clips
    assert (right.source_id, right.speed, right.track, right.overlay) == (
        left.source_id,
        left.speed,
        left.track,
        left.overlay,
    )


def test_split_with_speed_uses_source_time() -> None:
    project = make_project(make_clip(1, 0, 4000, speed=2.0))  # timeline 0-2000
    CommandStack(project).execute(SplitClip(500, right_clip_id=cid(2)))
    assert layout(project) == [(cid(1), 0, 1000), (cid(2), 1000, 4000)]
    assert spans(project) == [(0, 500), (500, 2000)]
    assert [c.speed for c in project.clips] == [2.0, 2.0]


def test_split_snaps_to_source_frame_grid() -> None:
    down = make_project(make_clip(1, 0, 4000))
    CommandStack(down).execute(SplitClip(1008, right_clip_id=cid(2)))
    assert layout(down)[0] == (cid(1), 0, 1000)
    up = make_project(make_clip(1, 0, 4000))
    CommandStack(up).execute(SplitClip(1010, right_clip_id=cid(2)))
    assert layout(up)[0] == (cid(1), 0, 1017)


def test_split_moves_items_at_or_after_the_cut_to_the_right_half() -> None:
    project = make_project(make_clip(1, 0, 4000))
    add_item(project, "placement", 1, 500, 50)  # before the cut: stays
    add_item(project, "keyframe", 1, 1000, 51)  # exactly at the cut: moves
    add_item(project, "reaction", 1, 1500, 52)  # after the cut: moves
    stack = CommandStack(project)
    stack.execute(SplitClip(1000, right_clip_id=cid(2)))
    assert anchors_of(project) == [(cid(1), 500), (cid(2), 1000), (cid(2), 1500)]
    stack.undo()
    assert anchors_of(project) == [(cid(1), 500), (cid(1), 1000), (cid(1), 1500)]
    stack.redo()
    assert anchors_of(project) == [(cid(1), 500), (cid(2), 1000), (cid(2), 1500)]


def test_split_copies_effects_independently() -> None:
    effects = [EffectSpec(type="zoom", params={"k": 1})]
    project = make_project(make_clip(1, 0, 4000, effects=effects))
    CommandStack(project).execute(SplitClip(1000, right_clip_id=cid(2)))
    left, right = project.clips
    assert right.effects == left.effects
    right.effects[0].params["k"] = 2
    assert left.effects[0].params["k"] == 1


def test_split_puts_right_half_directly_after_left() -> None:
    project = make_project(
        make_clip(1, 0, 4000), make_clip(7, 0, 1000, track=1), make_clip(2, 0, 2000)
    )
    CommandStack(project).execute(SplitClip(1000, right_clip_id=cid(3)))
    assert [c.id for c in project.clips] == [cid(1), cid(3), cid(7), cid(2)]


def test_split_later_clips_keep_their_length_and_shift_nothing() -> None:
    project = two_clips()
    CommandStack(project).execute(SplitClip(1000, right_clip_id=cid(3)))
    assert [c.id for c in project.clips] == [cid(1), cid(3), cid(2)]
    assert spans(project) == [(0, 1000), (1000, 4000), (4000, 6000)]


def test_split_undo_redo() -> None:
    project = two_clips()
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(SplitClip(1000, right_clip_id=cid(3)))
    after = layout(project)
    assert stack.undo() == "Split clip"
    assert project.model_dump() == before
    stack.redo()
    assert layout(project) == after


@pytest.mark.parametrize("timeline_ms", [0, 4000, -5, 6000, 5, 3995])
def test_split_refused(timeline_ms: int) -> None:
    # 0 and 4000 are existing cuts, -5 and 6000 are outside the timeline, and
    # 5 and 3995 would leave less than one frame in a half.
    project = two_clips()
    before = project.model_dump()
    stack = CommandStack(project)
    with pytest.raises(CommandError):
        stack.execute(SplitClip(timeline_ms))
    assert project.model_dump() == before
    assert not stack.can_undo


def test_split_duplicate_right_id_refused() -> None:
    project = two_clips()
    with pytest.raises(CommandError):
        CommandStack(project).execute(SplitClip(1000, right_clip_id=cid(1)))
    assert layout(project) == [(cid(1), 0, 4000), (cid(2), 0, 2000)]


def test_split_and_trim_in_a_group_undo_together() -> None:
    project = make_project(make_clip(1, 0, 4000))
    stack = CommandStack(project)
    with stack.group("Split and trim"):
        stack.execute(SplitClip(1000, right_clip_id=cid(2)))
        stack.execute(TrimClip(cid(2), "out", 3000))
    assert layout(project) == [(cid(1), 0, 1000), (cid(2), 1000, 3000)]
    assert stack.undo() == "Split and trim"
    assert layout(project) == [(cid(1), 0, 4000)]
    stack.redo()
    assert layout(project) == [(cid(1), 0, 1000), (cid(2), 1000, 3000)]


# --------------------------------------------------------------------------
# TrimClip
# --------------------------------------------------------------------------


def test_trim_in_ripples_later_clips_and_undoes() -> None:
    project = two_clips()
    stack = CommandStack(project)
    stack.execute(TrimClip(cid(1), "in", 1000))
    assert layout(project)[0] == (cid(1), 1000, 4000)
    assert timeline_duration(project.clips) == 5000
    assert to_timeline(project.clips, Anchor(clip_id=cid(2), source_ms=0)) == 3000
    stack.undo()
    assert layout(project)[0] == (cid(1), 0, 4000)
    stack.redo()
    assert layout(project)[0] == (cid(1), 1000, 4000)


def test_trim_out_and_undo() -> None:
    project = two_clips()
    stack = CommandStack(project)
    stack.execute(TrimClip(cid(1), "out", 3000))
    assert layout(project)[0] == (cid(1), 0, 3000)
    assert timeline_duration(project.clips) == 5000
    stack.undo()
    assert layout(project)[0] == (cid(1), 0, 4000)


def test_trim_can_extend_a_clip() -> None:
    project = make_project(make_clip(1, 1000, 3000))
    stack = CommandStack(project)
    stack.execute(TrimClip(cid(1), "in", 0))
    stack.execute(TrimClip(cid(1), "out", 5000))
    assert layout(project) == [(cid(1), 0, 5000)]
    stack.undo()
    stack.undo()
    assert layout(project) == [(cid(1), 1000, 3000)]


def test_trim_snaps_to_source_frame_grid() -> None:
    project = make_project(make_clip(1, 0, 4000))
    CommandStack(project).execute(TrimClip(cid(1), "out", 3008))
    assert layout(project) == [(cid(1), 0, 3000)]


def test_trim_does_not_snap_the_source_end() -> None:
    # 10_001 ms is off the frame grid but is the source's own end.
    exact = make_project(make_clip(1, 0, 4000), duration_ms=10_001)
    CommandStack(exact).execute(TrimClip(cid(1), "out", 10_001))
    assert layout(exact) == [(cid(1), 0, 10_001)]
    past = make_project(make_clip(1, 0, 4000), duration_ms=10_001)
    CommandStack(past).execute(TrimClip(cid(1), "out", 20_000))
    assert layout(past) == [(cid(1), 0, 10_001)]


@pytest.mark.parametrize(
    ("edge", "source_ms"),
    [("in", 3995), ("out", 5), ("in", 4000), ("out", 0)],
)
def test_trim_leaving_less_than_a_frame_refused(edge: str, source_ms: int) -> None:
    project = make_project(make_clip(1, 0, 4000))
    before = project.model_dump()
    with pytest.raises(CommandError, match="less than one frame"):
        CommandStack(project).execute(TrimClip(cid(1), edge, source_ms))
    assert project.model_dump() == before


@pytest.mark.parametrize(("edge", "source_ms"), [("in", 0), ("out", 4000)])
def test_trim_to_current_edge_refused(edge: str, source_ms: int) -> None:
    project = make_project(make_clip(1, 0, 4000))
    stack = CommandStack(project)
    with pytest.raises(CommandError):
        stack.execute(TrimClip(cid(1), edge, source_ms))
    assert not stack.can_undo


def test_trim_ignores_items_anchored_to_other_clips() -> None:
    project = two_clips()
    add_item(project, "placement", 2, 500, 50)
    CommandStack(project).execute(TrimClip(cid(1), "in", 1000))
    assert layout(project)[0] == (cid(1), 1000, 4000)


def test_trim_invalid_edge_refused() -> None:
    project = two_clips()
    with pytest.raises(CommandError):
        CommandStack(project).execute(TrimClip(cid(1), "middle", 100))


def test_trim_unknown_and_other_track_refused() -> None:
    project = make_project(make_clip(1, 0, 4000), make_clip(7, 0, 4000, track=1))
    stack = CommandStack(project)
    with pytest.raises(CommandError):
        stack.execute(TrimClip(cid(99), "in", 1000))
    with pytest.raises(CommandError):
        stack.execute(TrimClip(cid(7), "in", 1000))


# --------------------------------------------------------------------------
# RippleDelete
# --------------------------------------------------------------------------


def test_ripple_inside_one_clip_splits_it() -> None:
    project = two_clips()
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RippleDelete(1000, 2000, right_clip_id=cid(3)))
    expected = [(cid(1), 0, 1000), (cid(3), 2000, 4000), (cid(2), 0, 2000)]
    assert layout(project) == expected
    assert timeline_duration(project.clips) == 5000
    assert stack.undo() == "Ripple delete"
    assert project.model_dump() == before
    stack.redo()
    assert layout(project) == expected


def test_ripple_covering_the_start_of_a_clip_trims_its_in() -> None:
    project = two_clips()
    CommandStack(project).execute(RippleDelete(0, 1000))
    assert layout(project) == [(cid(1), 1000, 4000), (cid(2), 0, 2000)]
    assert timeline_duration(project.clips) == 5000


def test_ripple_covering_the_end_of_a_clip_trims_its_out() -> None:
    project = two_clips()
    CommandStack(project).execute(RippleDelete(3000, 4000))
    assert layout(project) == [(cid(1), 0, 3000), (cid(2), 0, 2000)]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (4000, 6000, [(1, 0, 4000)]),
        (0, 4000, [(2, 0, 2000)]),
        (3000, 5000, [(1, 0, 3000), (2, 1000, 2000)]),
        (0, 5000, [(2, 1000, 2000)]),
        (0, 6000, []),
    ],
)
def test_ripple_across_clips(
    start: int, end: int, expected: list[tuple[int, int, int]]
) -> None:
    project = two_clips()
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RippleDelete(start, end))
    assert layout(project) == [(cid(n), a, b) for n, a, b in expected]
    assert timeline_duration(project.clips) == 6000 - (end - start)
    stack.undo()
    assert project.model_dump() == before
    stack.redo()
    assert layout(project) == [(cid(n), a, b) for n, a, b in expected]


def test_ripple_with_speed_uses_source_time() -> None:
    project = make_project(make_clip(1, 0, 4000, speed=2.0), make_clip(2, 0, 2000))
    assert spans(project) == [(0, 2000), (2000, 4000)]
    CommandStack(project).execute(RippleDelete(500, 1000, right_clip_id=cid(3)))
    assert layout(project)[:2] == [(cid(1), 0, 1000), (cid(3), 2000, 4000)]
    assert spans(project) == [(0, 500), (500, 1500), (1500, 3500)]


def test_ripple_moves_items_after_the_cut_to_the_right_half() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 500, 50)
    add_item(project, "keyframe", 1, 3000, 51)
    add_item(project, "reaction", 2, 500, 52)
    stack = CommandStack(project)
    stack.execute(RippleDelete(1000, 2000, right_clip_id=cid(3)))
    assert anchors_of(project) == [(cid(1), 500), (cid(3), 3000), (cid(2), 500)]
    stack.undo()
    assert anchors_of(project) == [(cid(1), 500), (cid(1), 3000), (cid(2), 500)]


def test_ripple_keeps_items_outside_the_cut_at_the_right_time() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 3500, 50)
    original = project.placements[0].anchor.model_copy()
    assert to_timeline(project.clips, original) == 3500
    CommandStack(project).execute(RippleDelete(0, 1000))
    assert project.placements[0].anchor == original
    assert to_timeline(project.clips, original) == 2500


@pytest.mark.parametrize("start_end", [(-1, 100), (100, 100), (500, 100), (0, 7000)])
def test_ripple_invalid_range_refused(start_end: tuple[int, int]) -> None:
    project = two_clips()
    before = project.model_dump()
    with pytest.raises(CommandError):
        CommandStack(project).execute(RippleDelete(*start_end))
    assert project.model_dump() == before


def test_ripple_that_would_leave_a_sliver_refused() -> None:
    project = two_clips()
    before = project.model_dump()
    with pytest.raises(CommandError, match="less than one frame"):
        CommandStack(project).execute(RippleDelete(0, 3995))
    assert project.model_dump() == before


def test_ripple_shorter_than_one_frame_refused() -> None:
    project = two_clips()
    before = project.model_dump()
    with pytest.raises(CommandError, match="shorter than one frame"):
        CommandStack(project).execute(RippleDelete(1000, 1004))
    assert project.model_dump() == before


def test_ripple_duplicate_right_id_refused() -> None:
    project = two_clips()
    with pytest.raises(CommandError):
        CommandStack(project).execute(RippleDelete(1000, 2000, right_clip_id=cid(1)))
    assert layout(project) == [(cid(1), 0, 4000), (cid(2), 0, 2000)]


def test_ripple_leaves_other_track_clips_alone() -> None:
    project = make_project(
        make_clip(1, 0, 4000), make_clip(7, 0, 1000, track=1), make_clip(2, 0, 2000)
    )
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RippleDelete(1000, 2000, right_clip_id=cid(3)))
    assert [c.id for c in project.clips] == [cid(1), cid(3), cid(7), cid(2)]
    other = next(c for c in project.clips if c.id == cid(7))
    assert (other.track, other.in_ms, other.out_ms) == (1, 0, 1000)
    stack.undo()
    assert project.model_dump() == before


def test_ripple_removing_clips_around_other_track_clips_undoes_exactly() -> None:
    project = make_project(
        make_clip(1, 0, 4000), make_clip(7, 0, 1000, track=1), make_clip(2, 0, 2000)
    )
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RippleDelete(0, 6000))
    assert [c.id for c in project.clips] == [cid(7)]
    stack.undo()
    assert project.model_dump() == before


def test_ripple_and_trim_in_a_group_undo_together() -> None:
    project = two_clips()
    before = project.model_dump()
    stack = CommandStack(project)
    with stack.group("Cut and trim"):
        stack.execute(RippleDelete(0, 1000))
        stack.execute(TrimClip(cid(2), "out", 1000))
    assert layout(project) == [(cid(1), 1000, 4000), (cid(2), 0, 1000)]
    assert stack.undo() == "Cut and trim"
    assert project.model_dump() == before
