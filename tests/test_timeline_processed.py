"""Timeline lengths from processed audio, and the voice-chain fields (M4-1, S3b)."""

from backend.audio.trim import TrimBounds
from backend.project.schema import (
    Anchor,
    Clip,
    EffectSpec,
    Line,
    Placement,
    Project,
    Source,
    Take,
)
from backend.project.timeline import TimelinePlacement, TimelineState, build_timeline

SRC, CLIP = "1" * 12, "2" * 12
LINE_A, LINE_B = "3" * 12, "4" * 12
TAKE_A, TAKE_B = "5" * 12, "6" * 12
PLACE_A, PLACE_B = "7" * 12, "8" * 12
VOICE = "9" * 12

# 36000 samples at 24 kHz kept: 1500 ms before any stretch.
BOUNDS = TrimBounds(start=1000, end=37000, total=48000, sample_rate=24000)


def make_take(take_id: str, line_id: str, duration_ms: int) -> Take:
    return Take(
        id=take_id,
        line_id=line_id,
        seed=1,
        text="hello",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id=VOICE,
        model_version="m",
        raw_key="a" * 64,
        raw_file=f"media/takes_raw/{take_id}.wav",
        duration_ms=duration_ms,
    )


def make_project(*, stretch: float = 1.0, second_at_ms: int | None = None) -> Project:
    """One clip of 60 s; line A (take 2000 ms) placed at 1000 ms, and optionally
    line B (take 1000 ms) placed at ``second_at_ms``."""
    lines = [Line(id=LINE_A, text="hello", active_take_id=TAKE_A)]
    takes = [make_take(TAKE_A, LINE_A, 2000)]
    placements = [
        Placement(
            id=PLACE_A,
            line_id=LINE_A,
            anchor=Anchor(clip_id=CLIP, source_ms=1000),
            stretch=stretch,
        )
    ]
    if second_at_ms is not None:
        lines.append(Line(id=LINE_B, text="again", active_take_id=TAKE_B))
        takes.append(make_take(TAKE_B, LINE_B, 1000))
        placements.append(
            Placement(
                id=PLACE_B,
                line_id=LINE_B,
                anchor=Anchor(clip_id=CLIP, source_ms=second_at_ms),
            )
        )
    return Project(
        name="t",
        sources=[
            Source(
                id=SRC,
                path="footage/a.mkv",
                duration_ms=60000,
                fps_num=30,
                width=1920,
                height=1080,
            )
        ],
        clips=[Clip(id=CLIP, source_id=SRC, in_ms=0, out_ms=60000)],
        lines=lines,
        takes=takes,
        placements=placements,
    )


def placement(state: TimelineState, placement_id: str) -> TimelinePlacement:
    return next(p for p in state.placements if p.id == placement_id)


def test_without_trim_bounds_the_recorded_length_is_used() -> None:
    shown = placement(build_timeline(make_project()), PLACE_A)
    assert shown.raw_duration_ms == 2000
    assert shown.duration_ms == 2000
    assert shown.end_ms == 3000


def test_with_trim_bounds_the_trimmed_length_plays() -> None:
    state = build_timeline(make_project(), trim_bounds={TAKE_A: BOUNDS})
    shown = placement(state, PLACE_A)
    assert shown.raw_duration_ms == 1500
    assert shown.duration_ms == 1500
    assert shown.start_ms == 1000
    assert shown.end_ms == 2500


def test_a_stretch_shortens_the_trimmed_take() -> None:
    state = build_timeline(make_project(stretch=1.2), trim_bounds={TAKE_A: BOUNDS})
    shown = placement(state, PLACE_A)
    assert shown.raw_duration_ms == 1500  # before the stretch
    assert shown.duration_ms == 1250  # 36000 samples / 1.2 = 30000 samples
    assert shown.end_ms == 2250


def test_bounds_are_used_per_take() -> None:
    project = make_project(second_at_ms=5000)
    state = build_timeline(project, trim_bounds={TAKE_A: BOUNDS})
    assert placement(state, PLACE_A).duration_ms == 1500
    assert placement(state, PLACE_B).duration_ms == 1000  # no bounds: recorded length


def test_overflow_and_fit_stretch_use_the_processed_lengths() -> None:
    # A runs 1000 to 2500 ms and B starts at 2000 ms: 500 ms of overflow.
    project = make_project(second_at_ms=2000)
    state = build_timeline(project, trim_bounds={TAKE_A: BOUNDS})
    first = placement(state, PLACE_A)
    assert first.overflow_ms == 500
    assert first.fit_stretch == 1.5  # 1500 ms into the 1000 ms before B starts


def test_overflow_shrinks_when_the_line_is_stretched() -> None:
    project = make_project(stretch=1.2, second_at_ms=2000)
    state = build_timeline(project, trim_bounds={TAKE_A: BOUNDS})
    first = placement(state, PLACE_A)
    assert first.overflow_ms == 250
    assert first.fit_stretch == 1.5


def test_fx_version_is_short_and_stable() -> None:
    first = build_timeline(make_project()).fx_version
    assert len(first) == 8
    assert build_timeline(make_project()).fx_version == first


def test_fx_version_changes_with_what_changes_the_audio() -> None:
    base = build_timeline(make_project()).fx_version

    eq = make_project()
    eq.fx_chain.eq_bass_db = 3.0
    assert build_timeline(eq).fx_version != base

    loudness = make_project()
    loudness.fx_chain.loudness_target_lufs = -20.0
    assert build_timeline(loudness).fx_version != base


def test_fx_version_ignores_changes_that_change_nothing() -> None:
    base = build_timeline(make_project()).fx_version

    idle_compressor = make_project()  # disabled: its other settings do nothing
    idle_compressor.fx_chain.compressor.threshold_db = -30.0
    assert build_timeline(idle_compressor).fx_version == base

    idle_effect = make_project()
    idle_effect.fx_chain.effects = [
        EffectSpec(type="pitch_shift", params={"semitones": 0})
    ]
    assert build_timeline(idle_effect).fx_version == base


def test_an_unusable_chain_gives_an_invalid_version() -> None:
    project = make_project()
    project.fx_chain.eq_bass_db = 99.0  # beyond the +-12 dB the chain accepts
    assert build_timeline(project).fx_version == "invalid"


def test_game_audio_level_is_carried() -> None:
    project = make_project()
    project.game_audio_db = -6.0
    assert build_timeline(project).game_audio_db == -6.0
