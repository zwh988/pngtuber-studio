"""Schema v5 audio files, lanes and clips, and their commands (M8-1)."""

import pytest
from pydantic import ValidationError

from backend.project.audio_commands import (
    AddAudioClip,
    AddAudioFile,
    AddAudioLane,
    MoveAudioClip,
    MoveAudioLane,
    RemoveAudioClip,
    RemoveAudioLane,
    SetAudioClip,
    SetAudioLane,
    SplitAudioClip,
    TrimAudioClip,
    free_lane_from,
    lane_is_free,
    next_lane_name,
)
from backend.project.commands import CommandError, CommandStack
from backend.project.cut_commands import RippleDelete, SplitClip, TrimClip
from backend.project.edit_ops import EditBatch, build_command
from backend.project.migrations import migrate
from backend.project.schema import (
    SCHEMA_VERSION,
    AudioClip,
    AudioFile,
    AudioLane,
    Clip,
    Project,
    Source,
)


def hid(n: int) -> str:
    return f"{n:012x}"


SRC = hid(1)
CLIP_A = hid(10)
CLIP_B = hid(11)
LANE1 = hid(20)
LANE2 = hid(21)
MUSIC = hid(30)
SFX = hid(31)
C1 = hid(40)
C2 = hid(41)


def make_project() -> Project:
    """Footage 0 to 20000 ms (two clips); a 60 s music file and a 2 s sound effect."""
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
            Clip(id=CLIP_B, source_id=SRC, in_ms=20_000, out_ms=30_000),
        ],
        audio_files=[
            AudioFile(
                id=MUSIC,
                path="audio/music.wav",
                name="music.wav",
                size_bytes=10_000_000,
                duration_ms=60_000,
                sample_rate=48_000,
                channels=2,
            ),
            AudioFile(
                id=SFX,
                path="audio/pop.wav",
                name="pop.wav",
                size_bytes=100_000,
                duration_ms=2_000,
                sample_rate=44_100,
                channels=1,
            ),
        ],
        audio_lanes=[
            AudioLane(id=LANE1, name="Audio 1"),
            AudioLane(id=LANE2, name="Audio 2"),
        ],
    )


def clip(project: Project, clip_id: str) -> AudioClip:
    return next(c for c in project.audio_clips if c.id == clip_id)


# ---- schema and migration --------------------------------------------------------


def test_a_new_project_has_one_empty_audio_lane() -> None:
    project = Project(name="x")
    assert [lane.name for lane in project.audio_lanes] == ["Audio 1"]
    assert project.audio_clips == [] and project.audio_files == []


def test_v4_projects_get_one_audio_lane_and_no_clips() -> None:
    assert SCHEMA_VERSION >= 5
    data = {"schema_version": 4, "name": "x"}
    result = migrate(data, target=5)
    assert result["schema_version"] == 5
    assert "audio_lanes" not in data  # input untouched
    project = Project.model_validate(result)
    assert [lane.name for lane in project.audio_lanes] == ["Audio 1"]
    assert project.audio_clips == [] and project.audio_files == []


def test_v1_projects_migrate_all_the_way() -> None:
    project = Project.model_validate(migrate({"schema_version": 1, "name": "x"}))
    assert project.schema_version == SCHEMA_VERSION
    assert len(project.audio_lanes) == 1


def test_clip_times_and_fades_are_checked() -> None:
    base = {"id": C1, "lane_id": LANE1, "file_id": MUSIC, "timeline_ms": 0}
    with pytest.raises(ValidationError):
        AudioClip(**base, in_ms=500, out_ms=500)
    with pytest.raises(ValidationError):
        AudioClip(**base, out_ms=1000, fade_in_ms=600, fade_out_ms=500)
    with pytest.raises(ValidationError):
        AudioClip(**base, out_ms=1000, gain_db=13)
    ok = AudioClip(**base, in_ms=200, out_ms=1000, fade_in_ms=400, fade_out_ms=400)
    assert (ok.length_ms, ok.end_ms) == (800, 800)


def test_audio_file_paths_must_be_relative() -> None:
    with pytest.raises(ValidationError):
        AudioFile(
            id=MUSIC,
            path="D:/music.wav",
            name="m.wav",
            size_bytes=1,
            duration_ms=1,
            sample_rate=1,
            channels=1,
        )


def test_duplicate_audio_ids_are_refused() -> None:
    lane = AudioLane(id=LANE1)
    with pytest.raises(ValidationError):
        Project(name="x", audio_lanes=[lane, lane])


def test_round_trip_through_json() -> None:
    project = make_project()
    AddAudioClip(MUSIC, LANE1, 1000, clip_id=C1).apply(project)
    again = Project.model_validate_json(project.model_dump_json())
    assert again == project


# ---- lanes -------------------------------------------------------------------------


def test_add_lane_names_and_undo() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioLane())
    assert [lane.name for lane in project.audio_lanes] == [
        "Audio 1",
        "Audio 2",
        "Audio 3",
    ]
    stack.execute(AddAudioLane("Music", position=0))
    assert project.audio_lanes[0].name == "Music"
    stack.undo()
    stack.undo()
    assert [lane.id for lane in project.audio_lanes] == [LANE1, LANE2]


def test_next_lane_name_skips_custom_names() -> None:
    project = make_project()
    project.audio_lanes[1].name = "Music"
    assert next_lane_name(project) == "Audio 2"
    project.audio_lanes[0].name = "Audio 7"
    assert next_lane_name(project) == "Audio 8"


def test_add_lane_refuses_a_bad_position_or_name() -> None:
    with pytest.raises(CommandError):
        AddAudioLane(position=5).apply(make_project())
    with pytest.raises(CommandError):
        AddAudioLane("   ")


def test_remove_lane_only_when_empty_and_never_the_last() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(SFX, LANE2, 0, clip_id=C1))
    with pytest.raises(CommandError, match="still has clips"):
        stack.execute(RemoveAudioLane(LANE2))
    stack.execute(RemoveAudioLane(LANE1))
    assert [lane.id for lane in project.audio_lanes] == [LANE2]
    stack.execute(RemoveAudioClip(C1))
    with pytest.raises(CommandError, match="last audio lane"):
        stack.execute(RemoveAudioLane(LANE2))
    stack.undo()
    stack.undo()
    assert [lane.id for lane in project.audio_lanes] == [LANE1, LANE2]


def test_move_lane_and_undo() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(MoveAudioLane(LANE2, 0))
    assert [lane.id for lane in project.audio_lanes] == [LANE2, LANE1]
    stack.undo()
    assert [lane.id for lane in project.audio_lanes] == [LANE1, LANE2]
    with pytest.raises(CommandError):
        stack.execute(MoveAudioLane(LANE1, 2))


def test_set_lane_name_level_mute_solo() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(SetAudioLane(LANE1, name=" Music ", gain_db=-6, mute=True, solo=True))
    lane = project.audio_lanes[0]
    assert (lane.name, lane.gain_db, lane.mute, lane.solo) == (
        "Music",
        -6.0,
        True,
        True,
    )
    stack.undo()
    assert project.audio_lanes[0] == AudioLane(id=LANE1, name="Audio 1")
    with pytest.raises(CommandError):
        stack.execute(SetAudioLane(LANE1, gain_db=-80))
    with pytest.raises(CommandError):
        SetAudioLane(LANE1)


# ---- files -------------------------------------------------------------------------


def test_add_file_and_undo() -> None:
    project = Project(name="x")
    stack = CommandStack(project)
    audio_file = make_project().audio_files[0]
    stack.execute(AddAudioFile(audio_file))
    assert project.audio_files == [audio_file]
    with pytest.raises(CommandError):
        stack.execute(AddAudioFile(audio_file.model_copy(update={"id": SFX})))
    stack.undo()
    assert project.audio_files == []


# ---- clips -------------------------------------------------------------------------


def test_add_clip_defaults_to_the_whole_file() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(SFX, LANE1, 5000, clip_id=C1))
    added = clip(project, C1)
    assert (added.timeline_ms, added.in_ms, added.out_ms, added.end_ms) == (
        5000,
        0,
        2000,
        7000,
    )
    stack.undo()
    assert project.audio_clips == []


def test_add_clip_refusals() -> None:
    project = make_project()
    with pytest.raises(CommandError):
        AddAudioClip(SFX, LANE1, -1)
    with pytest.raises(CommandError, match="unknown audio file"):
        AddAudioClip(hid(99), LANE1, 0).apply(project)
    with pytest.raises(CommandError, match="unknown audio lane"):
        AddAudioClip(SFX, hid(99), 0).apply(project)
    with pytest.raises(CommandError, match="past the end"):
        AddAudioClip(SFX, LANE1, 0, out_ms=2001).apply(project)
    assert project.audio_clips == []


def test_clips_on_one_lane_never_overlap() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(SFX, LANE1, 1000, clip_id=C1))  # 1000 to 3000
    with pytest.raises(CommandError, match="already on that lane"):
        stack.execute(AddAudioClip(SFX, LANE1, 2999))
    with pytest.raises(CommandError):
        stack.execute(AddAudioClip(SFX, LANE1, 0, out_ms=1001))
    stack.execute(AddAudioClip(SFX, LANE1, 3000, clip_id=C2))  # touching is fine
    stack.execute(AddAudioClip(SFX, LANE2, 2000))  # another lane is fine
    assert len(project.audio_clips) == 3


def test_lane_is_free_and_free_lane_from() -> None:
    project = make_project()
    AddAudioClip(SFX, LANE1, 1000, clip_id=C1).apply(project)
    assert not lane_is_free(project, LANE1, 0, 1500)
    assert lane_is_free(project, LANE1, 0, 1500, except_id=C1)
    assert free_lane_from(project, LANE1, 0, 1500) == LANE2
    assert free_lane_from(project, LANE1, 3000, 1500) == LANE1
    AddAudioClip(SFX, LANE2, 0, clip_id=C2).apply(project)
    assert free_lane_from(project, LANE1, 500, 1000) is None
    assert free_lane_from(project, LANE2, 2500, 100) == LANE2


def test_move_clip_in_time_and_between_lanes() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(SFX, LANE1, 1000, clip_id=C1))
    stack.execute(AddAudioClip(SFX, LANE2, 1000, clip_id=C2))
    stack.execute(MoveAudioClip(C1, 8000))
    assert clip(project, C1).timeline_ms == 8000
    with pytest.raises(CommandError):
        stack.execute(MoveAudioClip(C1, 0, LANE2))  # would overlap C2
    stack.execute(MoveAudioClip(C1, 4000, LANE2))
    assert (clip(project, C1).lane_id, clip(project, C1).timeline_ms) == (LANE2, 4000)
    stack.undo()
    stack.undo()
    assert (clip(project, C1).lane_id, clip(project, C1).timeline_ms) == (LANE1, 1000)


def test_moving_onto_itself_is_not_an_overlap() -> None:
    project = make_project()
    AddAudioClip(SFX, LANE1, 1000, clip_id=C1).apply(project)
    MoveAudioClip(C1, 1500).apply(project)
    assert clip(project, C1).timeline_ms == 1500


def test_trim_start_keeps_the_sound_in_place() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(
        AddAudioClip(MUSIC, LANE1, 10_000, in_ms=5000, out_ms=20_000, clip_id=C1)
    )
    stack.execute(TrimAudioClip(C1, "start", 12_000))
    trimmed = clip(project, C1)
    assert (trimmed.timeline_ms, trimmed.in_ms, trimmed.out_ms) == (
        12_000,
        7000,
        20_000,
    )
    stack.execute(TrimAudioClip(C1, "start", 5000))  # back out to the file start
    assert (clip(project, C1).timeline_ms, clip(project, C1).in_ms) == (5000, 0)
    with pytest.raises(CommandError, match="start of its file"):
        stack.execute(TrimAudioClip(C1, "start", 4999))
    stack.undo()
    stack.undo()
    assert clip(project, C1).in_ms == 5000


def test_split_keeps_the_sound_in_place_and_shares_the_fades() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(
        AddAudioClip(MUSIC, LANE1, 10_000, in_ms=5000, out_ms=20_000, clip_id=C1)
    )
    stack.execute(SetAudioClip(C1, fade_in_ms=1000, fade_out_ms=3000))
    stack.execute(SplitAudioClip(C1, 12_000, right_clip_id=C2))  # 2 s into the clip
    left, right = clip(project, C1), clip(project, C2)
    assert (left.timeline_ms, left.in_ms, left.out_ms) == (10_000, 5000, 7000)
    assert (left.fade_in_ms, left.fade_out_ms) == (1000, 0)
    assert (right.timeline_ms, right.in_ms, right.out_ms) == (12_000, 7000, 20_000)
    assert (right.fade_in_ms, right.fade_out_ms, right.lane_id) == (0, 3000, LANE1)
    stack.undo()
    assert [c.id for c in project.audio_clips] == [C1]
    assert clip(project, C1).out_ms == 20_000


def test_split_shrinks_a_fade_and_refuses_outside_the_clip() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(MUSIC, LANE1, 0, in_ms=0, out_ms=10_000, clip_id=C1))
    stack.execute(SetAudioClip(C1, fade_in_ms=4000))
    stack.execute(SplitAudioClip(C1, 1000, right_clip_id=C2))
    assert clip(project, C1).fade_in_ms == 1000
    for at in (0, 5, 10_000, 20_000):
        with pytest.raises(CommandError, match="not inside"):
            stack.execute(SplitAudioClip(C2, at))


def test_trim_end() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(SFX, LANE1, 1000, clip_id=C1))
    stack.execute(TrimAudioClip(C1, "end", 2000))
    assert clip(project, C1).out_ms == 1000
    with pytest.raises(CommandError, match="past the end"):
        stack.execute(TrimAudioClip(C1, "end", 3001))
    with pytest.raises(CommandError, match="too short"):
        stack.execute(TrimAudioClip(C1, "end", 1005))
    with pytest.raises(CommandError, match="too short"):
        stack.execute(TrimAudioClip(C1, "start", 1995))


def test_trim_into_the_next_clip_is_refused() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(SFX, LANE1, 0, out_ms=1000, clip_id=C1))
    stack.execute(AddAudioClip(SFX, LANE1, 1500, clip_id=C2))
    with pytest.raises(CommandError, match="already on that lane"):
        stack.execute(TrimAudioClip(C1, "end", 1600))


def test_trim_shrinks_fades_that_no_longer_fit() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(SFX, LANE1, 0, clip_id=C1))
    stack.execute(SetAudioClip(C1, fade_in_ms=600, fade_out_ms=1200))
    stack.execute(TrimAudioClip(C1, "end", 900))
    trimmed = clip(project, C1)
    assert trimmed.fade_in_ms + trimmed.fade_out_ms <= 900
    assert (trimmed.fade_in_ms, trimmed.fade_out_ms) == (300, 600)
    stack.undo()
    assert (clip(project, C1).fade_in_ms, clip(project, C1).fade_out_ms) == (600, 1200)


def test_set_level_and_fades() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(SFX, LANE1, 0, clip_id=C1))
    stack.execute(SetAudioClip(C1, gain_db=-12, fade_in_ms=100))
    assert (clip(project, C1).gain_db, clip(project, C1).fade_in_ms) == (-12.0, 100)
    with pytest.raises(CommandError, match="fades must fit"):
        stack.execute(SetAudioClip(C1, fade_out_ms=1950))
    with pytest.raises(CommandError):
        stack.execute(SetAudioClip(C1, gain_db=20))
    stack.undo()
    assert clip(project, C1).gain_db == 0.0


# ---- decision 2: video edits never move audio clips -------------------------------


@pytest.mark.parametrize(
    "command",
    [
        lambda: RippleDelete(2000, 6000),
        lambda: SplitClip(5000),
        lambda: TrimClip(CLIP_A, "in", 3000),
    ],
)
def test_video_edits_leave_audio_clips_alone(command) -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(MUSIC, LANE1, 0, clip_id=C1))
    stack.execute(AddAudioClip(SFX, LANE2, 12_000, clip_id=C2))
    before = [c.model_copy() for c in project.audio_clips]
    stack.execute(command())
    assert project.audio_clips == before
    stack.undo()
    assert project.audio_clips == before


# ---- edit ops ----------------------------------------------------------------------


def test_split_audio_op() -> None:
    command = build_command(
        EditBatch.model_validate(
            {
                "label": "x",
                "ops": [{"op": "split_audio_clip", "clip_id": C1, "timeline_ms": 5}],
            }
        ).ops[0]
    )
    assert isinstance(command, SplitAudioClip)


def test_edit_ops_build_the_audio_commands() -> None:
    project = make_project()
    stack = CommandStack(project)
    batch = EditBatch.model_validate(
        {
            "label": "Drop",
            "ops": [
                {"op": "add_audio_lane", "lane_id": hid(22)},
                {
                    "op": "add_audio_clip",
                    "file_id": SFX,
                    "lane_id": hid(22),
                    "timeline_ms": 0,
                    "clip_id": C1,
                },
                {"op": "move_audio_clip", "clip_id": C1, "timeline_ms": 500},
                {
                    "op": "trim_audio_clip",
                    "clip_id": C1,
                    "edge": "end",
                    "timeline_ms": 2000,
                },
                {"op": "set_audio_clip", "clip_id": C1, "gain_db": -3},
                {"op": "set_audio_lane", "lane_id": hid(22), "mute": True},
                {"op": "move_audio_lane", "lane_id": hid(22), "new_position": 0},
            ],
        }
    )
    with stack.group(batch.label):
        for op in batch.ops:
            stack.execute(build_command(op))
    assert project.audio_lanes[0].id == hid(22) and project.audio_lanes[0].mute
    assert clip(project, C1).end_ms == 2000 and clip(project, C1).gain_db == -3
    stack.undo()
    assert project == make_project().model_copy(update={"seed": project.seed})
    batch = EditBatch.model_validate(
        {
            "label": "x",
            "ops": [
                {
                    "op": "add_audio_clip",
                    "file_id": SFX,
                    "lane_id": LANE1,
                    "timeline_ms": 0,
                    "clip_id": C1,
                },
                {"op": "remove_audio_clip", "clip_id": C1},
                {"op": "remove_audio_lane", "lane_id": LANE2},
            ],
        }
    )
    for op in batch.ops:
        stack.execute(build_command(op))
    assert project.audio_clips == [] and len(project.audio_lanes) == 1
