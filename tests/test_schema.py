import pytest
from pydantic import ValidationError

from backend.project.schema import (
    SCHEMA_VERSION,
    Anchor,
    Clip,
    Keyframe,
    Line,
    Placement,
    Project,
    Reaction,
    Source,
    Take,
    new_id,
)


def make_source(**overrides) -> Source:
    data = {
        "id": new_id(),
        "path": "footage/rack 01.mkv",
        "duration_ms": 600_000,
        "fps_num": 60,
        "fps_den": 1,
        "width": 2560,
        "height": 1440,
        "audio_tracks": 1,
    }
    data.update(overrides)
    return Source(**data)


def make_clip(source_id: str, **overrides) -> Clip:
    data = {"id": new_id(), "source_id": source_id, "in_ms": 0, "out_ms": 5000}
    data.update(overrides)
    return Clip(**data)


# ---- ids and paths --------------------------------------------------------


def test_new_id_is_valid_and_unique() -> None:
    a, b = new_id(), new_id()
    assert a != b
    assert len(a) == 12
    Line(id=a)  # passes id validation


@pytest.mark.parametrize("bad", ["", "XYZ", "0123456789ab0", "0123456789AB", "g" * 12])
def test_bad_ids_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        Line(id=bad)


def test_path_with_spaces_ok() -> None:
    assert make_source(path="footage/my rack/take 1.mkv").path.endswith("take 1.mkv")


@pytest.mark.parametrize(
    "bad",
    ["", "C:/footage/a.mkv", "/footage/a.mkv", "footage\\a.mkv", "../a.mkv", "a/../b.mkv"],
)
def test_bad_paths_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        make_source(path=bad)


# ---- entities --------------------------------------------------------------


def test_source_fps_property_handles_ntsc() -> None:
    src = make_source(fps_num=60000, fps_den=1001)
    assert src.fps == pytest.approx(59.94, abs=0.01)


def test_clip_defaults_and_bounds() -> None:
    clip = make_clip(new_id())
    assert clip.speed == 1.0
    assert clip.overlay is True
    assert clip.effects == []
    make_clip(new_id(), speed=0.25)
    make_clip(new_id(), speed=8.0)
    for bad_speed in (0.2, 8.5):
        with pytest.raises(ValidationError):
            make_clip(new_id(), speed=bad_speed)


@pytest.mark.parametrize("in_ms,out_ms", [(5000, 5000), (5000, 1000)])
def test_clip_out_must_exceed_in(in_ms: int, out_ms: int) -> None:
    with pytest.raises(ValidationError):
        make_clip(new_id(), in_ms=in_ms, out_ms=out_ms)


def test_times_are_integer_non_negative_ms() -> None:
    with pytest.raises(ValidationError):
        Anchor(clip_id=new_id(), source_ms=-1)
    with pytest.raises(ValidationError):
        Anchor(clip_id=new_id(), source_ms=1.5)  # type: ignore[arg-type]
    assert Anchor(clip_id=new_id(), source_ms=1500).source_ms == 1500


def test_line_slider_ranges() -> None:
    Line(id=new_id(), exaggeration=1.2, cfg_weight=0.3)
    with pytest.raises(ValidationError):
        Line(id=new_id(), exaggeration=3.0)
    with pytest.raises(ValidationError):
        Line(id=new_id(), cfg_weight=1.5)


def test_keyframe_value_float_or_string() -> None:
    anchor = Anchor(clip_id=new_id(), source_ms=0)
    assert Keyframe(id=new_id(), lane_id="scale", anchor=anchor, value=1.5).value == 1.5
    kf = Keyframe(id=new_id(), lane_id="expression", anchor=anchor, value="smug")
    assert kf.value == "smug"
    assert kf.interpolation == "hold"
    assert kf.orphaned is False


def test_reaction_type_and_duration() -> None:
    anchor = Anchor(clip_id=new_id(), source_ms=0)
    Reaction(id=new_id(), type="shake", anchor=anchor)
    with pytest.raises(ValidationError):
        Reaction(id=new_id(), type="explode", anchor=anchor)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Reaction(id=new_id(), type="hop", anchor=anchor, duration_ms=0)


def test_placement_orphan_flag_default() -> None:
    anchor = Anchor(clip_id=new_id(), source_ms=100)
    assert Placement(id=new_id(), line_id=new_id(), anchor=anchor).orphaned is False


def test_take_requires_valid_raw_file_path() -> None:
    base = {
        "id": new_id(),
        "line_id": new_id(),
        "seed": 42,
        "text": "hello",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "voice_profile_id": new_id(),
        "model_version": "chatterbox-0.1.7",
        "raw_key": "abc",
        "duration_ms": 2000,
    }
    take = Take(**base, raw_file="media/takes_raw/abc.wav")
    assert take.starred is False
    assert take.created.tzinfo is not None
    with pytest.raises(ValidationError):
        Take(**base, raw_file="C:/abs/abc.wav")


# ---- project root ----------------------------------------------------------


def test_project_defaults() -> None:
    project = Project(name="MyRack")
    assert project.schema_version == SCHEMA_VERSION == 1
    assert isinstance(project.seed, int)
    assert project.export.height == 1080
    assert project.export.fps == "match"
    assert project.fx_chain.loudness_target_lufs == -16.0
    assert project.game_audio_db == 0.0
    assert project.sources == []


def test_projects_get_different_seeds() -> None:
    assert Project(name="a").seed != Project(name="b").seed


def test_json_round_trip() -> None:
    src = make_source()
    clip = make_clip(src.id, speed=2.0)
    line = Line(id=new_id(), text="Nice break.")
    project = Project(
        name="MyRack",
        sources=[src],
        clips=[clip],
        lines=[line],
        placements=[
            Placement(
                id=new_id(),
                line_id=line.id,
                anchor=Anchor(clip_id=clip.id, source_ms=1234),
            )
        ],
    )
    text = project.model_dump_json(indent=2)
    again = Project.model_validate_json(text)
    assert again == project
    assert again.model_dump_json(indent=2) == text


def test_extra_fields_rejected() -> None:
    with pytest.raises(ValidationError):
        Project(name="x", surprise=1)  # type: ignore[call-arg]


def test_duplicate_ids_rejected() -> None:
    src = make_source()
    with pytest.raises(ValidationError):
        Project(name="x", sources=[src, src])


def test_invalid_project_dict_rejected() -> None:
    with pytest.raises(ValidationError):
        Project.model_validate({"name": "x", "clips": [{"id": "nope"}]})
    with pytest.raises(ValidationError):
        Project.model_validate({"schema_version": 0, "name": "x"})
