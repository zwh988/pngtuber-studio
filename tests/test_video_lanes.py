"""Schema v6 video lanes, lane clips and images, and their commands (M8-2)."""

import pytest
from pydantic import ValidationError

from backend.project.commands import CommandError, CommandStack, RemoveSource
from backend.project.cut_commands import RippleDelete, SplitClip, TrimClip
from backend.project.edit_ops import EditBatch, build_command
from backend.project.migrations import migrate
from backend.project.schema import (
    SCHEMA_VERSION,
    Clip,
    ImageFile,
    LaneClip,
    Project,
    Source,
    VideoLane,
)
from backend.project.timeline import build_timeline
from backend.project.video_lane_commands import (
    AddImageFile,
    AddLaneClip,
    AddVideoLane,
    MoveLaneClip,
    MoveVideoLane,
    RemoveLaneClip,
    RemoveVideoLane,
    SetLaneClip,
    SetVideoLane,
    TrimLaneClip,
    free_video_lane_from,
    next_video_lane_name,
    video_lane_is_free,
)


def hid(n: int) -> str:
    return f"{n:012x}"


SRC, B_ROLL = hid(1), hid(2)
MAIN_A, MAIN_B = hid(10), hid(11)
V2, V3 = hid(20), hid(21)
IMG = hid(30)
C1, C2 = hid(40), hid(41)


def source(source_id: str, path: str, ms: int) -> Source:
    return Source(
        id=source_id, path=path, duration_ms=ms, fps_num=60, width=1920, height=1080
    )


def make_project() -> Project:
    """Main footage 0 to 20000 ms (two clips); a 30 s B-roll recording; one still."""
    return Project(
        name="test",
        sources=[
            source(SRC, "footage/main.mkv", 60_000),
            source(B_ROLL, "footage/broll.mp4", 30_000),
        ],
        clips=[
            Clip(id=MAIN_A, source_id=SRC, in_ms=0, out_ms=10_000),
            Clip(id=MAIN_B, source_id=SRC, in_ms=20_000, out_ms=30_000),
        ],
        image_files=[
            ImageFile(
                id=IMG,
                path="images/title.png",
                name="title.png",
                size_bytes=10,
                width=800,
                height=200,
            )
        ],
        video_lanes=[
            VideoLane(id=V2, name="Video 2"),
            VideoLane(id=V3, name="Video 3"),
        ],
    )


def lane_clip(project: Project, clip_id: str) -> LaneClip:
    return next(c for c in project.lane_clips if c.id == clip_id)


# ---- schema and migration --------------------------------------------------------


def test_v5_projects_get_empty_video_lanes() -> None:
    assert SCHEMA_VERSION == 6
    data = {"schema_version": 5, "name": "x"}
    result = migrate(data)
    assert result["schema_version"] == 6
    assert "video_lanes" not in data
    project = Project.model_validate(result)
    assert (
        project.video_lanes == []
        and project.lane_clips == []
        and project.image_files == []
    )
    assert len(project.audio_lanes) == 1  # v5 defaults are unchanged


def test_v1_projects_migrate_all_the_way() -> None:
    project = Project.model_validate(migrate({"schema_version": 1, "name": "x"}))
    assert project.schema_version == SCHEMA_VERSION and project.video_lanes == []


def test_lane_clip_checks() -> None:
    base = {"id": C1, "lane_id": V2, "timeline_ms": 0}
    with pytest.raises(ValidationError, match="exactly one"):
        LaneClip(**base, out_ms=10)
    with pytest.raises(ValidationError, match="exactly one"):
        LaneClip(**base, source_id=SRC, image_id=IMG, out_ms=10)
    with pytest.raises(ValidationError, match="in_ms 0"):
        LaneClip(**base, image_id=IMG, in_ms=5, out_ms=10)
    with pytest.raises(ValidationError):
        LaneClip(**base, source_id=SRC, out_ms=10, opacity=1.5)
    with pytest.raises(ValidationError):
        LaneClip(**base, source_id=SRC, out_ms=10, scale=0.01)
    ok = LaneClip(**base, source_id=SRC, in_ms=100, out_ms=600)
    assert (ok.length_ms, ok.end_ms, ok.x, ok.y, ok.scale, ok.opacity) == (
        500,
        500,
        0.5,
        0.5,
        1,
        1,
    )


def test_round_trip_and_timeline_state() -> None:
    project = make_project()
    AddLaneClip(V2, 1000, source_id=B_ROLL, in_ms=0, out_ms=4000, clip_id=C1).apply(
        project
    )
    AddLaneClip(V3, 2000, image_id=IMG, clip_id=C2).apply(project)
    assert Project.model_validate_json(project.model_dump_json()) == project
    state = build_timeline(project, missing_source_ids={B_ROLL})
    assert [lane.name for lane in state.video_lanes] == ["Video 2", "Video 3"]
    assert [(c.name, c.timeline_ms, c.end_ms, c.missing) for c in state.lane_clips] == [
        ("broll.mp4", 1000, 5000, True),
        ("title.png", 2000, 7000, False),
    ]
    assert state.lane_clips[1].source_duration_ms == 0
    assert state.other_track_clips == 0


# ---- lanes -----------------------------------------------------------------------


def test_add_move_set_remove_lanes_with_undo() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddVideoLane())
    assert project.video_lanes[-1].name == "Video 4"
    stack.execute(MoveVideoLane(project.video_lanes[-1].id, 0))
    assert project.video_lanes[0].name == "Video 4"
    stack.execute(SetVideoLane(V2, name=" B-roll ", hidden=True, locked=True))
    lane = project.video_lanes[1]
    assert (lane.name, lane.hidden, lane.locked) == ("B-roll", True, True)
    stack.execute(RemoveVideoLane(V3))
    assert [lane.id for lane in project.video_lanes][1:] == [V2]
    for _ in range(4):
        stack.undo()
    assert project.video_lanes == make_project().video_lanes


def test_lane_names_and_removal_rules() -> None:
    assert next_video_lane_name(Project(name="x")) == "Video 2"
    project = make_project()
    project.video_lanes[1].name = "Titles"
    assert next_video_lane_name(project) == "Video 3"
    AddLaneClip(V2, 0, image_id=IMG).apply(project)
    with pytest.raises(CommandError, match="still has clips"):
        RemoveVideoLane(V2).apply(project)
    with pytest.raises(CommandError):
        SetVideoLane(V2)


# ---- clips -----------------------------------------------------------------------


def test_add_recording_and_still() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddLaneClip(V2, 1000, source_id=B_ROLL, clip_id=C1))
    assert (lane_clip(project, C1).in_ms, lane_clip(project, C1).out_ms) == (0, 30_000)
    stack.execute(AddLaneClip(V3, 0, image_id=IMG, length_ms=3000, clip_id=C2))
    assert lane_clip(project, C2).end_ms == 3000
    stack.undo()
    stack.undo()
    assert project.lane_clips == []


def test_add_refusals() -> None:
    project = make_project()
    with pytest.raises(CommandError):
        AddLaneClip(V2, 0)
    with pytest.raises(CommandError):
        AddLaneClip(V2, 0, source_id=B_ROLL, image_id=IMG)
    with pytest.raises(CommandError, match="past the end"):
        AddLaneClip(V2, 0, source_id=B_ROLL, out_ms=30_001).apply(project)
    with pytest.raises(CommandError, match="unknown video lane"):
        AddLaneClip(hid(99), 0, image_id=IMG).apply(project)
    with pytest.raises(CommandError, match="unknown image"):
        AddLaneClip(V2, 0, image_id=hid(99)).apply(project)
    AddLaneClip(V2, 0, image_id=IMG).apply(project)
    with pytest.raises(CommandError, match="already on that lane"):
        AddLaneClip(V2, 4999, image_id=IMG).apply(project)
    assert len(project.lane_clips) == 1


def test_free_lane_goes_up_and_skips_locked() -> None:
    project = make_project()
    AddLaneClip(V2, 0, image_id=IMG, clip_id=C1).apply(project)  # 0 to 5000
    assert not video_lane_is_free(project, V2, 4000, 6000)
    assert free_video_lane_from(project, V2, 1000, 1000) == V3
    SetVideoLane(V3, locked=True).apply(project)
    assert free_video_lane_from(project, V2, 1000, 1000) is None
    assert free_video_lane_from(project, V2, 5000, 1000) == V2


def test_locked_lane_refuses_edits() -> None:
    project = make_project()
    AddLaneClip(V2, 0, image_id=IMG, clip_id=C1).apply(project)
    SetVideoLane(V2, locked=True).apply(project)
    for command in (
        MoveLaneClip(C1, 100),
        TrimLaneClip(C1, "end", 1000),
        SetLaneClip(C1, opacity=0.5),
        RemoveLaneClip(C1),
        AddLaneClip(V2, 9000, image_id=IMG),
    ):
        with pytest.raises(CommandError, match="locked"):
            command.apply(project)
    with pytest.raises(CommandError, match="locked"):
        MoveLaneClip(C1, 100, V2).apply(project)
    AddLaneClip(V3, 0, image_id=IMG, clip_id=C2).apply(project)
    with pytest.raises(CommandError, match="locked"):
        MoveLaneClip(C2, 9000, V2).apply(project)  # into a locked lane


def test_move_between_lanes_and_undo() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddLaneClip(V2, 0, image_id=IMG, clip_id=C1))
    stack.execute(AddLaneClip(V3, 0, image_id=IMG, clip_id=C2))
    with pytest.raises(CommandError):
        stack.execute(MoveLaneClip(C1, 1000, V3))
    stack.execute(MoveLaneClip(C1, 6000, V3))
    assert (lane_clip(project, C1).lane_id, lane_clip(project, C1).timeline_ms) == (
        V3,
        6000,
    )
    stack.undo()
    assert lane_clip(project, C1).lane_id == V2


def test_trim_recording_keeps_the_picture_in_place() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(
        AddLaneClip(V2, 10_000, source_id=B_ROLL, in_ms=5000, out_ms=15_000, clip_id=C1)
    )
    stack.execute(TrimLaneClip(C1, "start", 12_000))
    c = lane_clip(project, C1)
    assert (c.timeline_ms, c.in_ms, c.out_ms) == (12_000, 7000, 15_000)
    with pytest.raises(CommandError, match="start of its recording"):
        stack.execute(TrimLaneClip(C1, "start", 4000))
    with pytest.raises(CommandError, match="past the end"):
        stack.execute(TrimLaneClip(C1, "end", 40_000))
    with pytest.raises(CommandError, match="too short"):
        stack.execute(TrimLaneClip(C1, "end", 12_010))


def test_trim_still_changes_its_length_only() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddLaneClip(V2, 1000, image_id=IMG, clip_id=C1))  # 1000 to 6000
    stack.execute(TrimLaneClip(C1, "start", 500))
    c = lane_clip(project, C1)
    assert (c.timeline_ms, c.in_ms, c.out_ms) == (500, 0, 5500)
    stack.execute(TrimLaneClip(C1, "end", 20_000))  # a still can be any length
    assert lane_clip(project, C1).end_ms == 20_000


def test_set_placement_opacity_and_sound() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddLaneClip(V2, 0, source_id=B_ROLL, clip_id=C1))
    stack.execute(SetLaneClip(C1, x=0.8, y=0.2, scale=0.3))
    assert stack.undo_label == "Place clip on a video lane"
    stack.execute(SetLaneClip(C1, opacity=0.5, gain_db=-12, mute=True))
    c = lane_clip(project, C1)
    assert (c.x, c.y, c.scale, c.opacity, c.gain_db, c.mute) == (
        0.8,
        0.2,
        0.3,
        0.5,
        -12,
        True,
    )
    with pytest.raises(CommandError):
        stack.execute(SetLaneClip(C1, scale=10))
    stack.undo()
    stack.undo()
    assert lane_clip(project, C1).scale == 1.0


def test_add_image_and_remove_source_in_use() -> None:
    project = Project(name="x", sources=[source(B_ROLL, "footage/broll.mp4", 30_000)])
    stack = CommandStack(project)
    image = make_project().image_files[0]
    stack.execute(AddImageFile(image))
    with pytest.raises(CommandError):
        stack.execute(AddImageFile(image.model_copy(update={"id": hid(31)})))
    stack.execute(AddVideoLane(lane_id=V2))
    stack.execute(AddLaneClip(V2, 0, source_id=B_ROLL))
    with pytest.raises(CommandError, match="still use it"):
        stack.execute(RemoveSource(B_ROLL))


# ---- decision 4: edits of the main footage never move lane clips ------------------


@pytest.mark.parametrize(
    "command",
    [
        lambda: RippleDelete(2000, 6000),
        lambda: SplitClip(5000),
        lambda: TrimClip(MAIN_A, "in", 3000),
    ],
)
def test_main_footage_edits_leave_lane_clips_alone(command) -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddLaneClip(V2, 1000, source_id=B_ROLL, out_ms=4000, clip_id=C1))
    stack.execute(AddLaneClip(V3, 12_000, image_id=IMG, clip_id=C2))
    before = [c.model_copy() for c in project.lane_clips]
    stack.execute(command())
    assert project.lane_clips == before
    stack.undo()
    assert project.lane_clips == before


# ---- edit ops --------------------------------------------------------------------


def test_edit_ops_build_the_video_lane_commands() -> None:
    project = make_project()
    stack = CommandStack(project)
    ops = [
        {"op": "add_video_lane", "lane_id": hid(22)},
        {
            "op": "add_lane_clip",
            "lane_id": hid(22),
            "timeline_ms": 0,
            "image_id": IMG,
            "clip_id": C1,
        },
        {"op": "move_lane_clip", "clip_id": C1, "timeline_ms": 500},
        {"op": "trim_lane_clip", "clip_id": C1, "edge": "end", "timeline_ms": 2000},
        {"op": "set_lane_clip", "clip_id": C1, "scale": 0.5, "opacity": 0.75},
        {"op": "set_video_lane", "lane_id": hid(22), "hidden": True},
        {"op": "move_video_lane", "lane_id": hid(22), "new_position": 0},
    ]
    batch = EditBatch.model_validate({"label": "Drop", "ops": ops})
    with stack.group(batch.label):
        for op in batch.ops:
            stack.execute(build_command(op))
    assert project.video_lanes[0].id == hid(22) and project.video_lanes[0].hidden
    c = lane_clip(project, C1)
    assert (c.end_ms, c.scale, c.opacity) == (2000, 0.5, 0.75)
    stack.undo()
    assert project.lane_clips == [] and len(project.video_lanes) == 2
    for op in EditBatch.model_validate(
        {
            "label": "x",
            "ops": [
                {
                    "op": "add_lane_clip",
                    "lane_id": V2,
                    "timeline_ms": 0,
                    "source_id": B_ROLL,
                    "clip_id": C1,
                },
                {"op": "remove_lane_clip", "clip_id": C1},
                {"op": "remove_video_lane", "lane_id": V3},
            ],
        }
    ).ops:
        stack.execute(build_command(op))
    assert project.lane_clips == [] and [lane.id for lane in project.video_lanes] == [
        V2
    ]
