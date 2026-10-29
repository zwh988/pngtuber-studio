"""Placement stretch: schema v2, migration, command, timeline state (M3-9, S8c)."""

import pytest
from pydantic import ValidationError

from backend.project.commands import CommandError, CommandStack
from backend.project.edit_ops import SetPlacementStretchOp, build_command
from backend.project.migrations import migrate
from backend.project.placement_commands import SetPlacementStretch
from backend.project.schema import (
    SCHEMA_VERSION,
    Anchor,
    Clip,
    Line,
    Placement,
    Project,
    Source,
    Take,
)
from backend.project.timeline import build_timeline

CLIP = "c" * 12
SRC = "5" * 12
LINE = "1" * 12
TAKE = "7" * 12
PL = "a" * 12


def make_project(stretch: float = 1.0) -> Project:
    return Project(
        name="t",
        sources=[
            Source(
                id=SRC,
                path="footage/a.mkv",
                duration_ms=10000,
                fps_num=60,
                width=1920,
                height=1080,
            )
        ],
        clips=[Clip(id=CLIP, source_id=SRC, in_ms=0, out_ms=10000)],
        lines=[Line(id=LINE, text="hi", active_take_id=TAKE)],
        takes=[
            Take(
                id=TAKE,
                line_id=LINE,
                seed=1,
                text="hi",
                exaggeration=0.5,
                cfg_weight=0.5,
                voice_profile_id="9" * 12,
                model_version="m",
                raw_key="k",
                raw_file="media/takes_raw/t.wav",
                duration_ms=2000,
            )
        ],
        placements=[
            Placement(
                id=PL,
                line_id=LINE,
                anchor=Anchor(clip_id=CLIP, source_ms=1000),
                stretch=stretch,
            )
        ],
    )


# ---- schema ---------------------------------------------------------------


def test_schema_is_version_two_and_stretch_defaults_to_one() -> None:
    assert SCHEMA_VERSION == 2
    assert make_project().placements[0].stretch == 1.0


def test_stretch_range_is_enforced() -> None:
    for bad in (0.99, 1.26):
        with pytest.raises(ValidationError):
            make_project(bad)
    assert make_project(1.25).placements[0].stretch == 1.25


# ---- migration ------------------------------------------------------------


def v1_data() -> dict:
    return {
        "schema_version": 1,
        "name": "old",
        "placements": [
            {"id": PL, "line_id": LINE, "anchor": {"clip_id": CLIP, "source_ms": 5}}
        ],
    }


def test_migration_adds_stretch_and_bumps_the_version() -> None:
    result = migrate(v1_data())
    assert result["schema_version"] == 2
    assert result["placements"][0]["stretch"] == 1.0
    assert Project.model_validate(result).placements[0].stretch == 1.0


def test_migration_keeps_an_existing_value_and_does_not_mutate_input() -> None:
    data = v1_data()
    data["placements"][0]["stretch"] = 1.1
    assert migrate(data)["placements"][0]["stretch"] == 1.1
    plain = v1_data()
    migrate(plain)
    assert "stretch" not in plain["placements"][0]


def test_migration_works_without_placements() -> None:
    assert migrate({"schema_version": 1, "name": "x"})["schema_version"] == 2


# ---- command --------------------------------------------------------------


def test_set_stretch_apply_revert_redo() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(SetPlacementStretch(PL, 1.08))
    assert project.placements[0].stretch == 1.08
    stack.undo()
    assert project.placements[0].stretch == 1.0
    stack.redo()
    assert project.placements[0].stretch == 1.08


def test_set_stretch_rounds_to_three_decimals() -> None:
    project = make_project()
    CommandStack(project).execute(SetPlacementStretch(PL, 1.08349))
    assert project.placements[0].stretch == 1.083


def test_set_stretch_refusals_leave_the_project_alone() -> None:
    project = make_project()
    for bad in (0.5, 1.26, float("nan")):
        with pytest.raises(CommandError):
            SetPlacementStretch(PL, bad)
    with pytest.raises(CommandError):
        SetPlacementStretch("f" * 12, 1.1).apply(project)  # unknown placement
    with pytest.raises(CommandError):
        SetPlacementStretch(PL, 1.0).apply(project)  # no change
    assert project.placements[0].stretch == 1.0


def test_a_value_that_rounds_into_range_is_accepted() -> None:
    assert SetPlacementStretch(PL, 1.2501).stretch == 1.25


def test_op_builds_the_command() -> None:
    cmd = build_command(SetPlacementStretchOp(placement_id=PL, stretch=1.1))
    assert isinstance(cmd, SetPlacementStretch)


# ---- timeline state ---------------------------------------------------------


def test_timeline_reports_the_playing_length() -> None:
    placed = build_timeline(make_project(1.25)).placements[0]
    assert placed.stretch == 1.25
    assert placed.raw_duration_ms == 2000
    assert placed.duration_ms == 1600
    assert placed.end_ms == 1000 + 1600


def test_timeline_without_stretch_is_unchanged() -> None:
    placed = build_timeline(make_project()).placements[0]
    assert placed.duration_ms == 2000
    assert placed.fit_stretch is None
