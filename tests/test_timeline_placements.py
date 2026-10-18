"""Placed lines in the timeline state (``build_timeline``)."""

from backend.project.clip_commands import SetSpeed
from backend.project.commands import CommandStack
from backend.project.placement_commands import AddPlacement
from backend.project.schema import Anchor, Clip, Line, Placement, Project, Source, Take
from backend.project.timeline import build_timeline


def hid(n: int) -> str:
    return f"{n:012x}"


SRC = hid(1)
CLIP_A = hid(10)
CLIP_B = hid(11)
LINE = hid(20)
TAKE = hid(30)
TAKE_2 = hid(31)
P1 = hid(50)
P2 = hid(51)


def make_take(take_id: str, duration_ms: int) -> Take:
    return Take(
        id=take_id,
        line_id=LINE,
        seed=1,
        text="hello there",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id=hid(40),
        model_version="test",
        raw_key="k" * 64,
        raw_file=f"media/takes_raw/{take_id}.wav",
        duration_ms=duration_ms,
    )


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
        lines=[Line(id=LINE, text="hello there", active_take_id=TAKE)],
        takes=[make_take(TAKE, 1500)],
    )


def place(project: Project, placement_id: str, clip_id: str, source_ms: int) -> None:
    project.placements.append(
        Placement(
            id=placement_id,
            line_id=LINE,
            anchor=Anchor(clip_id=clip_id, source_ms=source_ms),
        )
    )


def test_no_placements_gives_an_empty_list() -> None:
    assert build_timeline(make_project()).placements == []


def test_a_placement_has_start_end_and_take() -> None:
    project = make_project()
    place(project, P1, CLIP_A, 3_000)
    (shown,) = build_timeline(project).placements
    assert shown.id == P1
    assert shown.line_id == LINE
    assert shown.line_text == "hello there"
    assert shown.take_id == TAKE
    assert shown.duration_ms == 1500
    assert shown.start_ms == 3_000
    assert shown.end_ms == 4_500
    assert shown.anchor_clip_id == CLIP_A
    assert shown.anchor_source_ms == 3_000
    assert shown.orphaned is False
    assert shown.allow_overlap is False


def test_start_follows_the_clip_speed() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddPlacement(LINE, 4_000, placement_id=P1))
    stack.execute(SetSpeed(CLIP_A, 2.0))
    (shown,) = build_timeline(project).placements
    assert shown.start_ms == 2_000


def test_a_placement_on_the_second_clip_uses_its_span() -> None:
    project = make_project()
    place(project, P1, CLIP_B, 22_000)
    (shown,) = build_timeline(project).placements
    assert shown.start_ms == 11_000


def test_the_override_take_wins_over_the_active_take() -> None:
    project = make_project()
    project.takes.append(make_take(TAKE_2, 900))
    place(project, P1, CLIP_A, 1_000)
    project.placements[0].take_override_id = TAKE_2
    (shown,) = build_timeline(project).placements
    assert shown.take_id == TAKE_2
    assert shown.duration_ms == 900
    assert shown.end_ms == 1_900


def test_a_missing_override_falls_back_to_the_active_take() -> None:
    project = make_project()
    place(project, P1, CLIP_A, 1_000)
    project.placements[0].take_override_id = hid(77)
    (shown,) = build_timeline(project).placements
    assert shown.take_id == TAKE


def test_a_line_without_a_take_has_no_audio_but_keeps_its_place() -> None:
    project = make_project()
    place(project, P1, CLIP_A, 1_000)
    project.lines[0].active_take_id = None
    (shown,) = build_timeline(project).placements
    assert shown.take_id is None
    assert shown.duration_ms is None
    assert shown.end_ms is None
    assert shown.start_ms == 1_000


def test_an_anchor_that_cannot_be_mapped_has_no_start() -> None:
    project = make_project()
    place(project, P1, hid(99), 0)
    (shown,) = build_timeline(project).placements
    assert shown.start_ms is None
    assert shown.end_ms is None


def test_placements_are_sorted_by_start_and_unmapped_ones_come_last() -> None:
    project = make_project()
    place(project, P2, CLIP_A, 6_000)
    place(project, hid(52), hid(99), 0)
    place(project, P1, CLIP_A, 2_000)
    shown = build_timeline(project).placements
    assert [p.id for p in shown] == [P1, P2, hid(52)]


def test_the_orphan_flag_is_passed_through() -> None:
    project = make_project()
    place(project, P1, CLIP_A, 0)
    project.placements[0].orphaned = True
    (shown,) = build_timeline(project).placements
    assert shown.orphaned is True


def test_a_placement_of_a_missing_line_shows_empty_text() -> None:
    project = make_project()
    project.placements.append(
        Placement(
            id=P1,
            line_id=hid(88),
            anchor=Anchor(clip_id=CLIP_A, source_ms=1_000),
        )
    )
    (shown,) = build_timeline(project).placements
    assert shown.line_text == ""
    assert shown.take_id is None
    assert shown.start_ms == 1_000
