"""Tests for backend/edl/anchoring.py (pure, no I/O)."""

import pytest

from backend.edl.anchoring import (
    anchored_items,
    check_references,
    edge_anchors,
    find_orphans,
    item_kind,
    items_in_source_range,
    park_anchor,
)
from backend.edl.timemap import clip_spans
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


def cid(n: int) -> str:
    return f"{n:012x}"


def make_clip(n: int, in_ms: int, out_ms: int, *, track: int = 0) -> Clip:
    return Clip(id=cid(n), source_id=SRC, in_ms=in_ms, out_ms=out_ms, track=track)


def make_source() -> Source:
    return Source(
        id=SRC,
        path="footage/a.mkv",
        duration_ms=10_000,
        fps_num=60,
        fps_den=1,
        width=1920,
        height=1080,
    )


def placement(
    n: int, clip_n: int, source_ms: int, *, orphaned: bool = False
) -> Placement:
    return Placement(
        id=cid(n),
        line_id=cid(60),
        anchor=Anchor(clip_id=cid(clip_n), source_ms=source_ms),
        orphaned=orphaned,
    )


def keyframe(n: int, clip_n: int, source_ms: int) -> Keyframe:
    return Keyframe(
        id=cid(n),
        lane_id="expression",
        anchor=Anchor(clip_id=cid(clip_n), source_ms=source_ms),
        value="happy",
    )


def reaction(n: int, clip_n: int, source_ms: int) -> Reaction:
    return Reaction(
        id=cid(n),
        type="shake",
        anchor=Anchor(clip_id=cid(clip_n), source_ms=source_ms),
    )


# A: source 0..4000 (timeline 0-4000), B: source 1000..3000 (timeline 4000-6000)
def two_clips() -> list[Clip]:
    return [make_clip(1, 0, 4000), make_clip(2, 1000, 3000)]


# --------------------------------------------------------------------------
# Finding items
# --------------------------------------------------------------------------


def test_anchored_items_lists_all_kinds_in_order() -> None:
    project = Project(
        name="t",
        sources=[make_source()],
        clips=two_clips(),
        placements=[placement(50, 1, 100)],
        keyframes=[keyframe(51, 2, 1500)],
        reactions=[reaction(52, 1, 200)],
    )
    assert [i.id for i in anchored_items(project)] == [cid(50), cid(51), cid(52)]
    assert [i.id for i in anchored_items(project, cid(1))] == [cid(50), cid(52)]
    assert anchored_items(project, cid(99)) == []


def test_items_in_source_range_is_low_inclusive_high_exclusive() -> None:
    project = Project(
        name="t",
        sources=[make_source()],
        clips=two_clips(),
        placements=[
            placement(50, 1, 999),
            placement(51, 1, 1000),
            placement(52, 1, 1999),
            placement(53, 1, 2000),
            placement(54, 2, 1500),
        ],
    )
    found = items_in_source_range(project, cid(1), 1000, 2000)
    assert [i.id for i in found] == [cid(51), cid(52)]
    unbounded = items_in_source_range(project, cid(1), 1000, None)
    assert [i.id for i in unbounded] == [cid(51), cid(52), cid(53)]


def test_item_kind_names() -> None:
    assert item_kind(placement(50, 1, 0)) == "placement"
    assert item_kind(keyframe(51, 1, 0)) == "keyframe"
    assert item_kind(reaction(52, 1, 0)) == "reaction"


def test_find_orphans_returns_only_flagged_items() -> None:
    project = Project(
        name="t",
        sources=[make_source()],
        clips=two_clips(),
        placements=[placement(50, 1, 100, orphaned=True), placement(51, 1, 200)],
        keyframes=[keyframe(52, 2, 1500)],
    )
    assert [i.id for i in find_orphans(project)] == [cid(50)]
    project.keyframes[0].orphaned = True
    assert [i.id for i in find_orphans(project)] == [cid(50), cid(52)]


# --------------------------------------------------------------------------
# edge_anchors
# --------------------------------------------------------------------------


def test_edge_anchors_between_two_clips() -> None:
    before, after = edge_anchors(two_clips(), 4000)
    assert before == Anchor(clip_id=cid(1), source_ms=3999)
    assert after == Anchor(clip_id=cid(2), source_ms=1000)


def test_edge_anchors_at_the_start_has_no_before() -> None:
    before, after = edge_anchors(two_clips(), 0)
    assert before is None
    assert after == Anchor(clip_id=cid(1), source_ms=0)


def test_edge_anchors_at_the_end_has_no_after() -> None:
    before, after = edge_anchors(two_clips(), 6000)
    assert before == Anchor(clip_id=cid(2), source_ms=2999)
    assert after is None


def test_edge_anchors_with_no_clips() -> None:
    assert edge_anchors([], 0) == (None, None)


def test_edge_anchors_ignores_other_tracks() -> None:
    clips = [make_clip(1, 0, 4000), make_clip(7, 0, 1000, track=1)]
    before, after = edge_anchors(clips, 4000)
    assert before == Anchor(clip_id=cid(1), source_ms=3999)
    assert after is None


def test_edge_anchors_accepts_precomputed_spans() -> None:
    clips = two_clips()
    assert edge_anchors(clips, 4000, spans=clip_spans(clips)) == edge_anchors(
        clips, 4000
    )


# --------------------------------------------------------------------------
# park_anchor
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offset_ms", "expect_before"),
    [
        (0, True),
        (499, True),
        (500, True),  # tie goes to the earlier edge
        (501, False),
        (1000, False),
        (-50, True),  # clamped to the region
        (5000, False),
    ],
)
def test_park_anchor_picks_the_nearer_edge(
    offset_ms: int, expect_before: bool
) -> None:
    parked = park_anchor(two_clips(), 4000, offset_ms, 1000)
    expected = (
        Anchor(clip_id=cid(1), source_ms=3999)
        if expect_before
        else Anchor(clip_id=cid(2), source_ms=1000)
    )
    assert parked == expected


def test_park_anchor_uses_the_only_side_that_exists() -> None:
    assert park_anchor(two_clips(), 0, 900, 1000) == Anchor(
        clip_id=cid(1), source_ms=0
    )
    assert park_anchor(two_clips(), 6000, 0, 1000) == Anchor(
        clip_id=cid(2), source_ms=2999
    )


def test_park_anchor_returns_none_when_no_clip_survives() -> None:
    assert park_anchor([], 0, 0, 1000) is None


def test_park_anchor_zero_length_region_goes_to_the_earlier_edge() -> None:
    assert park_anchor(two_clips(), 4000, 0, 0) == Anchor(
        clip_id=cid(1), source_ms=3999
    )


# --------------------------------------------------------------------------
# check_references
# --------------------------------------------------------------------------


def test_check_references_clean_project() -> None:
    project = Project(
        name="t",
        sources=[make_source()],
        clips=two_clips(),
        placements=[placement(50, 1, 100)],
        keyframes=[keyframe(51, 2, 1500)],
        reactions=[reaction(52, 2, 1200)],
    )
    assert check_references(project) == []


def test_check_references_clip_missing_source() -> None:
    project = Project(name="t", sources=[], clips=[make_clip(1, 0, 4000)])
    problems = check_references(project)
    assert [(p.kind, p.owner_id, p.missing_id) for p in problems] == [
        ("clip_missing_source", cid(1), SRC)
    ]
    assert cid(1) in problems[0].message
    assert SRC in problems[0].message


def test_check_references_item_missing_clip() -> None:
    project = Project(
        name="t",
        sources=[make_source()],
        clips=[make_clip(1, 0, 4000)],
        placements=[placement(50, 9, 100)],
        keyframes=[keyframe(51, 1, 100)],
        reactions=[reaction(52, 8, 100)],
    )
    problems = check_references(project)
    assert [(p.kind, p.owner_id, p.missing_id) for p in problems] == [
        ("item_missing_clip", cid(50), cid(9)),
        ("item_missing_clip", cid(52), cid(8)),
    ]
    assert "placement" in problems[0].message
    assert "reaction" in problems[1].message


def test_check_references_does_not_change_the_project() -> None:
    project = Project(
        name="t",
        sources=[],
        clips=[make_clip(1, 0, 4000)],
        placements=[placement(50, 9, 100)],
    )
    before = project.model_dump()
    check_references(project)
    assert project.model_dump() == before
