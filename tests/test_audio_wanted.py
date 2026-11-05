"""Which (take, stretch) pairs the placed lines play (M4-1, S3c)."""

from backend.audio.wanted import PlayedTake, played_takes
from backend.project.schema import Anchor, Line, Placement, Project, Take

CLIP = "2" * 12
LINE_A, LINE_B = "3" * 12, "4" * 12
TAKE_A, TAKE_A2, TAKE_B = "5" * 12, "a" * 12, "6" * 12
PLACE_1, PLACE_2, PLACE_3 = "7" * 12, "8" * 12, "b" * 12
VOICE = "9" * 12


def make_take(take_id: str, line_id: str, raw_key: str) -> Take:
    return Take(
        id=take_id,
        line_id=line_id,
        seed=1,
        text="hello",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id=VOICE,
        model_version="m",
        raw_key=raw_key,
        raw_file=f"media/takes_raw/{take_id}.wav",
        duration_ms=1000,
    )


def place(
    place_id: str,
    line_id: str,
    *,
    stretch: float = 1.0,
    override: str | None = None,
    orphaned: bool = False,
) -> Placement:
    return Placement(
        id=place_id,
        line_id=line_id,
        anchor=Anchor(clip_id=CLIP, source_ms=1000),
        take_override_id=override,
        orphaned=orphaned,
        stretch=stretch,
    )


def make_project(
    placements: list[Placement], *, active_a: str | None = TAKE_A
) -> Project:
    return Project(
        name="t",
        lines=[
            Line(id=LINE_A, text="a", active_take_id=active_a),
            Line(id=LINE_B, text="b", active_take_id=TAKE_B),
        ],
        takes=[
            make_take(TAKE_A, LINE_A, "k" * 64),
            make_take(TAKE_A2, LINE_A, "m" * 64),
            make_take(TAKE_B, LINE_B, "n" * 64),
        ],
        placements=placements,
    )


def test_a_placed_line_plays_its_active_take() -> None:
    found = played_takes(make_project([place(PLACE_1, LINE_A, stretch=1.1)]))
    assert found == [
        PlayedTake(TAKE_A, f"media/takes_raw/{TAKE_A}.wav", "k" * 64, 1.1)
    ]


def test_the_placement_override_beats_the_active_take() -> None:
    found = played_takes(make_project([place(PLACE_1, LINE_A, override=TAKE_A2)]))
    assert [p.take_id for p in found] == [TAKE_A2]


def test_an_override_that_does_not_exist_falls_back_to_the_active_take() -> None:
    found = played_takes(make_project([place(PLACE_1, LINE_A, override="f" * 12)]))
    assert [p.take_id for p in found] == [TAKE_A]


def test_orphaned_placements_make_no_sound() -> None:
    assert played_takes(make_project([place(PLACE_1, LINE_A, orphaned=True)])) == []


def test_a_line_without_a_take_is_left_out() -> None:
    project = make_project([place(PLACE_1, LINE_A)], active_a=None)
    assert played_takes(project) == []


def test_one_take_at_one_stretch_is_listed_once() -> None:
    project = make_project([place(PLACE_1, LINE_A), place(PLACE_2, LINE_A)])
    assert len(played_takes(project)) == 1


def test_one_take_at_two_stretches_is_listed_twice() -> None:
    project = make_project(
        [place(PLACE_1, LINE_A), place(PLACE_2, LINE_A, stretch=1.08)]
    )
    assert [p.stretch for p in played_takes(project)] == [1.0, 1.08]


def test_the_order_follows_the_placements() -> None:
    project = make_project(
        [place(PLACE_1, LINE_B), place(PLACE_2, LINE_A), place(PLACE_3, LINE_B)]
    )
    assert [p.take_id for p in played_takes(project)] == [TAKE_B, TAKE_A]
