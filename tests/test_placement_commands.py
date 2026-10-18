"""Placement commands: anchoring through the clip list, undo and redo, orphaning."""

import pytest

from backend.edl.timemap import to_timeline
from backend.project.commands import CommandError, CommandStack
from backend.project.cut_commands import TrimClip
from backend.project.edit_ops import (
    AddPlacementOp,
    EditBatch,
    MovePlacementOp,
    RemovePlacementOp,
    build_command,
)
from backend.project.placement_commands import (
    AddPlacement,
    MovePlacement,
    RemovePlacement,
)
from backend.project.schema import Anchor, Clip, Line, Placement, Project, Source, Take


def hid(n: int) -> str:
    return f"{n:012x}"


SRC = hid(1)
CLIP_A = hid(10)
CLIP_B = hid(11)
LINE = hid(20)
LINE_NO_TAKE = hid(21)
TAKE = hid(30)
P1 = hid(50)
P2 = hid(51)


def make_project() -> Project:
    """Timeline: clip A 0 to 10000 ms, then clip B 10000 to 12000 ms (2x speed)."""
    return Project(
        name="test",
        sources=[
            Source(
                id=SRC,
                path="footage/a.mkv",
                duration_ms=60_000,
                fps_num=60,
                width=1920,
                height=1080,
            )
        ],
        clips=[
            Clip(id=CLIP_A, source_id=SRC, in_ms=0, out_ms=10_000),
            Clip(id=CLIP_B, source_id=SRC, in_ms=20_000, out_ms=24_000, speed=2.0),
        ],
        lines=[
            Line(id=LINE, text="hello there", active_take_id=TAKE),
            Line(id=LINE_NO_TAKE, text="not generated yet"),
        ],
        takes=[
            Take(
                id=TAKE,
                line_id=LINE,
                seed=1,
                text="hello there",
                exaggeration=0.5,
                cfg_weight=0.5,
                voice_profile_id=hid(40),
                model_version="test",
                raw_key="k" * 64,
                raw_file="media/takes_raw/a.wav",
                duration_ms=1500,
            )
        ],
    )


def placement_ids(project: Project) -> list[str]:
    return [p.id for p in project.placements]


# ---- AddPlacement ----------------------------------------------------------


def test_add_anchors_through_the_clip_list() -> None:
    project = make_project()
    AddPlacement(LINE, 3_000, placement_id=P1).apply(project)
    placement = project.placements[0]
    assert placement.id == P1
    assert placement.line_id == LINE
    assert placement.anchor == Anchor(clip_id=CLIP_A, source_ms=3_000)
    assert placement.orphaned is False
    assert placement.take_override_id is None


def test_add_on_a_sped_up_clip_stores_source_time() -> None:
    project = make_project()
    AddPlacement(LINE, 11_000, placement_id=P1).apply(project)
    # 1000 ms into a 2x clip is 2000 ms into the source.
    assert project.placements[0].anchor == Anchor(clip_id=CLIP_B, source_ms=22_000)
    assert to_timeline(project.clips, project.placements[0].anchor) == 11_000


def test_add_without_an_id_makes_one() -> None:
    project = make_project()
    AddPlacement(LINE, 0).apply(project)
    assert len(project.placements) == 1


def test_add_refuses_an_unknown_line() -> None:
    project = make_project()
    before = project.model_dump()
    with pytest.raises(CommandError, match="unknown line"):
        AddPlacement(hid(99), 1_000).apply(project)
    assert project.model_dump() == before


def test_add_refuses_a_line_with_no_take() -> None:
    project = make_project()
    before = project.model_dump()
    with pytest.raises(CommandError, match="no take"):
        AddPlacement(LINE_NO_TAKE, 1_000).apply(project)
    assert project.model_dump() == before


@pytest.mark.parametrize("timeline_ms", [12_000, 50_000])
def test_add_refuses_a_time_with_no_footage(timeline_ms: int) -> None:
    project = make_project()
    before = project.model_dump()
    with pytest.raises(CommandError, match="no footage"):
        AddPlacement(LINE, timeline_ms).apply(project)
    assert project.model_dump() == before


def test_add_refuses_a_negative_time() -> None:
    with pytest.raises(CommandError, match="negative"):
        AddPlacement(LINE, -1)


def test_add_refuses_a_duplicate_id() -> None:
    project = make_project()
    AddPlacement(LINE, 1_000, placement_id=P1).apply(project)
    before = project.model_dump()
    with pytest.raises(CommandError, match="already exists"):
        AddPlacement(LINE, 2_000, placement_id=P1).apply(project)
    assert project.model_dump() == before


def test_add_with_a_malformed_id_changes_nothing() -> None:
    project = make_project()
    before = project.model_dump()
    with pytest.raises(ValueError, match="pattern"):
        AddPlacement(LINE, 1_000, placement_id="nope").apply(project)
    assert project.model_dump() == before


def test_add_undo_and_redo_keep_the_same_placement() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddPlacement(LINE, 3_000, placement_id=P1))
    anchor = project.placements[0].anchor.model_copy()
    assert stack.undo() == "Place line"
    assert project.placements == []
    assert stack.redo() == "Place line"
    assert placement_ids(project) == [P1]
    assert project.placements[0].anchor == anchor


# ---- RemovePlacement -------------------------------------------------------


def test_remove_then_undo_restores_the_order() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddPlacement(LINE, 1_000, placement_id=P1))
    stack.execute(AddPlacement(LINE, 5_000, placement_id=P2))
    stack.execute(RemovePlacement(P1))
    assert placement_ids(project) == [P2]
    stack.undo()
    assert placement_ids(project) == [P1, P2]
    assert project.placements[0].anchor.source_ms == 1_000
    stack.redo()
    assert placement_ids(project) == [P2]


def test_remove_keeps_the_line_and_its_takes() -> None:
    project = make_project()
    AddPlacement(LINE, 1_000, placement_id=P1).apply(project)
    RemovePlacement(P1).apply(project)
    assert [line.id for line in project.lines] == [LINE, LINE_NO_TAKE]
    assert [take.id for take in project.takes] == [TAKE]


def test_remove_unknown_placement_is_refused() -> None:
    with pytest.raises(CommandError, match="unknown placement"):
        RemovePlacement(P1).apply(make_project())


# ---- MovePlacement ---------------------------------------------------------


def test_move_changes_the_anchor_and_undo_restores_it() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddPlacement(LINE, 3_000, placement_id=P1))
    stack.execute(MovePlacement(P1, 11_000))
    assert project.placements[0].anchor == Anchor(clip_id=CLIP_B, source_ms=22_000)
    stack.undo()
    assert project.placements[0].anchor == Anchor(clip_id=CLIP_A, source_ms=3_000)
    stack.redo()
    assert project.placements[0].anchor == Anchor(clip_id=CLIP_B, source_ms=22_000)


def test_move_settles_an_orphan_and_undo_brings_it_back() -> None:
    project = make_project()
    project.placements.append(
        Placement(
            id=P1,
            line_id=LINE,
            anchor=Anchor(clip_id=CLIP_A, source_ms=0),
            orphaned=True,
        )
    )
    command = MovePlacement(P1, 4_000)
    command.apply(project)
    assert project.placements[0].orphaned is False
    assert project.placements[0].anchor.source_ms == 4_000
    command.revert(project)
    assert project.placements[0].orphaned is True
    assert project.placements[0].anchor.source_ms == 0


def test_move_to_a_time_with_no_footage_changes_nothing() -> None:
    project = make_project()
    AddPlacement(LINE, 3_000, placement_id=P1).apply(project)
    before = project.model_dump()
    with pytest.raises(CommandError, match="no footage"):
        MovePlacement(P1, 12_000).apply(project)
    assert project.model_dump() == before


def test_move_unknown_placement_is_refused() -> None:
    with pytest.raises(CommandError, match="unknown placement"):
        MovePlacement(P1, 1_000).apply(make_project())


def test_move_refuses_a_negative_time() -> None:
    with pytest.raises(CommandError, match="negative"):
        MovePlacement(P1, -5)


# ---- the anchoring rule ------------------------------------------------------


def test_a_trim_that_cuts_the_anchor_away_orphans_the_placement() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddPlacement(LINE, 1_000, placement_id=P1))
    stack.execute(TrimClip(CLIP_A, "in", 5_000))
    assert project.placements[0].orphaned is True
    stack.undo()
    assert project.placements[0].orphaned is False
    assert project.placements[0].anchor == Anchor(clip_id=CLIP_A, source_ms=1_000)


def test_a_speed_change_keeps_the_placement_on_its_moment() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddPlacement(LINE, 4_000, placement_id=P1))
    anchor = project.placements[0].anchor.model_copy()
    project.clips[0].speed = 2.0
    assert project.placements[0].anchor == anchor
    # The same footage moment now sits at half the timeline time.
    assert to_timeline(project.clips, anchor) == 2_000


# ---- ops -------------------------------------------------------------------


def test_ops_build_the_matching_commands() -> None:
    batch = EditBatch.model_validate(
        {
            "label": "Place and move",
            "ops": [
                {"op": "add_placement", "line_id": LINE, "timeline_ms": 1_000},
                {"op": "move_placement", "placement_id": P1, "timeline_ms": 2_000},
                {"op": "remove_placement", "placement_id": P1},
            ],
        }
    )
    kinds = [type(build_command(op)) for op in batch.ops]
    assert kinds == [AddPlacement, MovePlacement, RemovePlacement]


def test_ops_refuse_unknown_fields_and_missing_ones() -> None:
    with pytest.raises(ValueError, match="Extra inputs"):
        AddPlacementOp.model_validate(
            {"line_id": LINE, "timeline_ms": 1_000, "colour": "red"}
        )
    with pytest.raises(ValueError, match="Field required"):
        MovePlacementOp.model_validate({"placement_id": P1})
    with pytest.raises(ValueError, match="Extra inputs"):
        RemovePlacementOp.model_validate({"placement_id": P1, "extra": 1})


def test_a_batch_of_placement_ops_is_one_undo_step() -> None:
    project = make_project()
    stack = CommandStack(project)
    ops = [
        AddPlacementOp(line_id=LINE, timeline_ms=1_000, placement_id=P1),
        MovePlacementOp(placement_id=P1, timeline_ms=11_000),
    ]
    with stack.group("Place and move"):
        for op in ops:
            stack.execute(build_command(op))
    assert project.placements[0].anchor.clip_id == CLIP_B
    assert stack.undo_label == "Place and move"
    stack.undo()
    assert project.placements == []
    assert stack.can_undo is False
