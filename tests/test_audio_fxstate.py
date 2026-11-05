"""The Voice FX tab's state (M4-2, S3c)."""

from backend.audio.chainspec import COMPRESSOR_RANGES, EQ_GAIN_LIMIT_DB
from backend.audio.fxstate import FxProcessing, FxState, build_fx_state
from backend.audio.gamemix import GAME_AUDIO_MAX_DB, GAME_AUDIO_MIN_DB
from backend.audio.loudness import TARGET_MAX_LUFS, TARGET_MIN_LUFS
from backend.project.schema import FxChain, Project
from backend.project.timeline import build_timeline

PRESETS = {"Clean": FxChain(), "Bright": FxChain(eq_treble_db=3.0)}


def state_for(project: Project) -> FxState:
    return build_fx_state(project, PRESETS, processing=FxProcessing())


def test_the_state_mirrors_the_project() -> None:
    project = Project(name="t", fx_chain=FxChain(eq_bass_db=2.0), game_audio_db=-6.0)
    state = state_for(project)
    assert state.chain == project.fx_chain
    assert state.game_audio_db == -6.0
    assert len(state.fx_version) == 8
    assert state.problem is None


def test_presets_keep_their_order() -> None:
    state = state_for(Project(name="t"))
    assert [item.name for item in state.presets] == ["Clean", "Bright"]
    assert state.presets[1].chain.eq_treble_db == 3.0


def test_the_effects_are_described_for_the_ui() -> None:
    state = state_for(Project(name="t"))
    by_type = {effect.type: effect for effect in state.effects}
    assert {"pitch_shift", "chorus"} <= set(by_type)
    semitones = by_type["pitch_shift"].params[0]
    assert semitones.name == "semitones"
    assert semitones.minimum < 0 < semitones.maximum


def test_the_limits_are_the_ones_the_backend_enforces() -> None:
    limits = state_for(Project(name="t")).limits
    assert limits.eq_gain_limit_db == EQ_GAIN_LIMIT_DB
    assert limits.loudness_min_lufs == TARGET_MIN_LUFS
    assert limits.loudness_max_lufs == TARGET_MAX_LUFS
    assert limits.game_audio_min_db == GAME_AUDIO_MIN_DB
    assert limits.game_audio_max_db == GAME_AUDIO_MAX_DB
    assert set(limits.compressor) == set(COMPRESSOR_RANGES)
    for name, (low, high) in COMPRESSOR_RANGES.items():
        assert limits.compressor[name] == [low, high]


def test_an_unusable_chain_is_reported_not_raised() -> None:
    project = Project(name="t")
    project.fx_chain.eq_bass_db = 99.0
    state = state_for(project)
    assert state.fx_version == "invalid"
    assert state.problem is not None
    assert "eq_bass_db" in state.problem


def test_the_version_matches_the_timeline_state() -> None:
    project = Project(name="t", fx_chain=FxChain(eq_mid_db=-2.0))
    assert state_for(project).fx_version == build_timeline(project).fx_version


def test_processing_and_undo_information_are_passed_through() -> None:
    state = build_fx_state(
        Project(name="t"),
        PRESETS,
        processing=FxProcessing(total=5, ready=3),
        can_undo=True,
        undo_label="Set voice chain",
    )
    assert (state.processing.total, state.processing.ready) == (5, 3)
    assert state.can_undo and not state.can_redo
    assert state.undo_label == "Set voice chain"


def test_the_state_survives_a_json_round_trip() -> None:
    state = state_for(Project(name="t"))
    assert FxState.model_validate_json(state.model_dump_json()) == state
