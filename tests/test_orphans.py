"""Tests for orphan flagging and parking inside the clip commands (M2-5).

Test footage is 60 fps; multiples of 50 ms land exactly on the frame grid.
Layout used in most tests: A is source 0..4000 (timeline 0-4000) and B is
source 0..2000 (timeline 4000-6000).

Parking rule: the item goes to the nearer end of the removed footage, measured
in the old timeline; a tie goes to the earlier edge (the clip before the cut,
at ``out_ms - 1``). The later edge is the start of the clip after the cut.
"""

from collections.abc import Sequence

import pytest

from backend.edl.anchoring import AnchoredItem, check_references, find_orphans
from backend.edl.timemap import to_timeline
from backend.project.clip_commands import RemoveClip, ReorderClip, SetSpeed
from backend.project.commands import CommandError, CommandStack
from backend.project.cut_commands import RippleDelete, SplitClip, TrimClip
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
KINDS = ["placement", "keyframe", "reaction"]


def cid(n: int) -> str:
    return f"{n:012x}"


def make_project(*clips: Clip) -> Project:
    source = Source(
        id=SRC,
        path="footage/a.mkv",
        duration_ms=10_000,
        fps_num=60,
        fps_den=1,
        width=1920,
        height=1080,
    )
    return Project(name="t", sources=[source], clips=list(clips))


def make_clip(n: int, in_ms: int, out_ms: int) -> Clip:
    return Clip(id=cid(n), source_id=SRC, in_ms=in_ms, out_ms=out_ms)


def two_clips() -> Project:
    return make_project(make_clip(1, 0, 4000), make_clip(2, 0, 2000))


def add_item(
    project: Project,
    kind: str,
    clip_n: int,
    source_ms: int,
    n: int,
    *,
    orphaned: bool = False,
) -> None:
    anchor = Anchor(clip_id=cid(clip_n), source_ms=source_ms)
    if kind == "placement":
        project.placements.append(
            Placement(id=cid(n), line_id=cid(60), anchor=anchor, orphaned=orphaned)
        )
    elif kind == "keyframe":
        project.keyframes.append(
            Keyframe(
                id=cid(n),
                lane_id="expression",
                anchor=anchor,
                value="happy",
                orphaned=orphaned,
            )
        )
    else:
        project.reactions.append(
            Reaction(id=cid(n), type="shake", anchor=anchor, orphaned=orphaned)
        )


def items_of(project: Project, kind: str) -> Sequence[AnchoredItem]:
    return {
        "placement": project.placements,
        "keyframe": project.keyframes,
        "reaction": project.reactions,
    }[kind]


def where(item: AnchoredItem) -> tuple[str, int, bool]:
    return (item.anchor.clip_id, item.anchor.source_ms, item.orphaned)


def all_where(project: Project) -> list[tuple[str, int, bool]]:
    items = (*project.placements, *project.keyframes, *project.reactions)
    return [where(i) for i in items]


# --------------------------------------------------------------------------
# RemoveClip
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_remove_last_clip_parks_on_the_previous_clip_end(kind: str) -> None:
    project = two_clips()
    add_item(project, kind, 2, 500, 50)
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RemoveClip(cid(2)))
    item = items_of(project, kind)[0]
    assert where(item) == (cid(1), 3999, True)
    assert to_timeline(project.clips, item.anchor) is not None
    parked = project.model_dump()
    stack.undo()
    assert project.model_dump() == before
    stack.redo()
    assert project.model_dump() == parked


def test_remove_first_clip_parks_on_the_next_clip_start() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 500, 50)
    CommandStack(project).execute(RemoveClip(cid(1)))
    assert all_where(project) == [(cid(2), 0, True)]


def test_remove_middle_clip_parks_each_item_on_the_nearer_side() -> None:
    project = make_project(
        make_clip(1, 0, 4000), make_clip(2, 0, 2000), make_clip(3, 0, 3000)
    )
    add_item(project, "placement", 2, 500, 50)  # near the start: before
    add_item(project, "placement", 2, 1500, 51)  # near the end: after
    add_item(project, "placement", 2, 1000, 52)  # exact middle: tie, earlier edge
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RemoveClip(cid(2)))
    assert all_where(project) == [
        (cid(1), 3999, True),
        (cid(3), 0, True),
        (cid(1), 3999, True),
    ]
    stack.undo()
    assert project.model_dump() == before


def test_remove_only_clip_flags_but_keeps_the_anchor() -> None:
    project = make_project(make_clip(1, 0, 4000))
    add_item(project, "placement", 1, 500, 50)
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RemoveClip(cid(1)))
    assert all_where(project) == [(cid(1), 500, True)]
    problems = check_references(project)
    assert [(p.kind, p.owner_id) for p in problems] == [
        ("item_missing_clip", cid(50))
    ]
    stack.undo()
    assert project.model_dump() == before


def test_remove_clip_leaves_other_clips_items_alone() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 500, 50)
    add_item(project, "placement", 2, 500, 51)
    CommandStack(project).execute(RemoveClip(cid(2)))
    assert all_where(project) == [(cid(1), 500, False), (cid(1), 3999, True)]


def test_remove_clip_reparks_an_already_orphaned_item_and_undoes_exactly() -> None:
    project = two_clips()
    add_item(project, "placement", 2, 500, 50, orphaned=True)
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RemoveClip(cid(2)))
    assert all_where(project) == [(cid(1), 3999, True)]
    stack.undo()
    assert all_where(project) == [(cid(2), 500, True)]
    assert project.model_dump() == before


def test_an_item_can_be_parked_twice_and_undone_step_by_step() -> None:
    project = make_project(
        make_clip(1, 0, 4000), make_clip(2, 0, 2000), make_clip(3, 0, 3000)
    )
    add_item(project, "placement", 2, 500, 50)
    start = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RemoveClip(cid(2)))
    assert all_where(project) == [(cid(1), 3999, True)]
    first = project.model_dump()
    stack.execute(RemoveClip(cid(1)))
    assert all_where(project) == [(cid(3), 0, True)]
    stack.undo()
    assert project.model_dump() == first
    stack.undo()
    assert project.model_dump() == start


# --------------------------------------------------------------------------
# TrimClip
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source_ms", "expected"),
    [
        (3000, (1, 2999)),  # at the cut: closest to the earlier edge
        (3100, (1, 2999)),
        (3500, (1, 2999)),  # exact middle of [3000, 4000): tie, earlier edge
        (3501, (2, 0)),
        (3900, (2, 0)),
        (3999, (2, 0)),
    ],
)
def test_trim_out_parks_on_the_nearer_edge(
    source_ms: int, expected: tuple[int, int]
) -> None:
    project = two_clips()
    add_item(project, "placement", 1, source_ms, 50)
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(TrimClip(cid(1), "out", 3000))
    assert where(project.placements[0]) == (cid(expected[0]), expected[1], True)
    parked = project.model_dump()
    stack.undo()
    assert project.model_dump() == before
    stack.redo()
    assert project.model_dump() == parked


def test_trim_out_keeps_items_before_the_new_edge() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 2999, 50)
    add_item(project, "placement", 1, 3000, 51)
    CommandStack(project).execute(TrimClip(cid(1), "out", 3000))
    assert all_where(project) == [(cid(1), 2999, False), (cid(1), 2999, True)]


def test_trim_in_of_the_first_clip_parks_on_the_new_start() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 500, 50)
    add_item(project, "placement", 1, 1000, 51)
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(TrimClip(cid(1), "in", 1000))
    # Nothing precedes the first clip, so the item parks on its new start. The
    # item exactly at the new start survives.
    assert all_where(project) == [(cid(1), 1000, True), (cid(1), 1000, False)]
    stack.undo()
    assert project.model_dump() == before


@pytest.mark.parametrize(
    ("source_ms", "expected"),
    [
        (200, (1, 3999)),
        (500, (1, 3999)),  # tie, earlier edge
        (800, (2, 1000)),
    ],
)
def test_trim_in_of_a_later_clip_parks_on_the_nearer_edge(
    source_ms: int, expected: tuple[int, int]
) -> None:
    project = two_clips()
    add_item(project, "placement", 2, source_ms, 50)
    add_item(project, "placement", 2, 1000, 51)  # exactly at the new in: kept
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(TrimClip(cid(2), "in", 1000))
    assert where(project.placements[0]) == (cid(expected[0]), expected[1], True)
    assert where(project.placements[1]) == (cid(2), 1000, False)
    stack.undo()
    assert project.model_dump() == before


@pytest.mark.parametrize("kind", KINDS)
def test_trim_orphans_every_kind_of_item(kind: str) -> None:
    project = two_clips()
    add_item(project, kind, 1, 3500, 50)
    CommandStack(project).execute(TrimClip(cid(1), "out", 3000))
    assert where(items_of(project, kind)[0]) == (cid(1), 2999, True)
    assert [i.id for i in find_orphans(project)] == [cid(50)]


def test_trim_that_extends_orphans_nothing() -> None:
    project = make_project(make_clip(1, 1000, 3000))
    add_item(project, "placement", 1, 1500, 50)
    stack = CommandStack(project)
    stack.execute(TrimClip(cid(1), "in", 0))
    stack.execute(TrimClip(cid(1), "out", 5000))
    assert all_where(project) == [(cid(1), 1500, False)]


# --------------------------------------------------------------------------
# RippleDelete
# --------------------------------------------------------------------------


def test_ripple_inside_a_clip_orphans_the_cut_and_moves_what_follows() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 500, 50)  # before the range: untouched
    add_item(project, "placement", 1, 1200, 51)  # near the start of the cut
    add_item(project, "placement", 1, 1900, 52)  # near the end of the cut
    add_item(project, "keyframe", 1, 3000, 53)  # after the range: right half
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RippleDelete(1000, 2000, right_clip_id=cid(3)))
    assert all_where(project) == [
        (cid(1), 500, False),
        (cid(1), 999, True),
        (cid(3), 2000, True),
        (cid(3), 3000, False),
    ]
    done = project.model_dump()
    stack.undo()
    assert project.model_dump() == before
    stack.redo()
    assert project.model_dump() == done


def test_ripple_across_two_clips_parks_around_the_whole_range() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 2000, 50)  # survives
    add_item(project, "placement", 1, 3500, 51)  # cut: nearer the start
    add_item(project, "placement", 2, 500, 52)  # cut: nearer the end
    add_item(project, "placement", 2, 1500, 53)  # survives
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RippleDelete(3000, 5000))
    assert all_where(project) == [
        (cid(1), 2000, False),
        (cid(1), 2999, True),
        (cid(2), 1000, True),
        (cid(2), 1500, False),
    ]
    stack.undo()
    assert project.model_dump() == before


def test_ripple_removing_the_first_clip_parks_on_the_next_clip() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 500, 50)
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RippleDelete(0, 4000))
    assert all_where(project) == [(cid(2), 0, True)]
    stack.undo()
    assert project.model_dump() == before


def test_ripple_removing_everything_flags_and_keeps_anchors() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 500, 50)
    add_item(project, "reaction", 2, 500, 51)
    before = project.model_dump()
    stack = CommandStack(project)
    stack.execute(RippleDelete(0, 6000))
    assert project.clips == []
    assert all_where(project) == [(cid(1), 500, True), (cid(2), 500, True)]
    assert len(check_references(project)) == 2
    stack.undo()
    assert project.model_dump() == before


def test_ripple_outside_the_cut_orphans_nothing() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 3500, 50)
    CommandStack(project).execute(RippleDelete(0, 1000))
    assert all_where(project) == [(cid(1), 3500, False)]
    assert find_orphans(project) == []


def test_ripple_in_a_group_rolls_back_orphans_when_a_later_command_fails() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 1500, 50)
    before = project.model_dump()
    stack = CommandStack(project)
    with pytest.raises(CommandError), stack.group("Cut and fail"):
        stack.execute(RippleDelete(1000, 2000, right_clip_id=cid(3)))
        stack.execute(TrimClip(cid(99), "in", 0))
    assert project.model_dump() == before
    assert not stack.can_undo


# --------------------------------------------------------------------------
# Edits that must not orphan
# --------------------------------------------------------------------------


def test_reorder_speed_and_split_orphan_nothing() -> None:
    project = two_clips()
    add_item(project, "placement", 1, 500, 50)
    add_item(project, "keyframe", 2, 500, 51)
    stack = CommandStack(project)
    stack.execute(ReorderClip(cid(1), 1))
    stack.execute(SetSpeed(cid(2), 2.0))
    stack.execute(SplitClip(2000, right_clip_id=cid(3)))
    assert all_where(project) == [(cid(1), 500, False), (cid(2), 500, False)]
    assert find_orphans(project) == []
    assert check_references(project) == []
