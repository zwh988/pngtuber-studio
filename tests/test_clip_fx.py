"""Audio clip FX (M8-4): schema v10, the clip processing spec and key, the command and op."""

import pytest
from pydantic import TypeAdapter

from backend.audio.clipfx import clip_fx_key, clip_fx_key_for, clip_processing_spec
from backend.project.audio_commands import (
    AddAudioClip,
    MoveAudioClip,
    SetAudioClipFx,
    SplitAudioClip,
    TrimAudioClip,
)
from backend.project.commands import CommandError, CommandStack
from backend.project.edit_ops import EditOp, build_command
from backend.project.line_commands import NoChange
from backend.project.migrations import migrate
from backend.project.schema import (
    SCHEMA_VERSION,
    ClipFx,
    CompressorSettings,
    EffectSpec,
    Project,
)
from backend.project.timeline import build_timeline
from tests.test_audio_lanes import C1, C2, LANE1, LANE2, MUSIC, SFX, clip, make_project

BASS = ClipFx(eq_bass_db=4.0)


def with_clip() -> tuple[Project, CommandStack]:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(AddAudioClip(MUSIC, LANE1, 1000, clip_id=C1))
    return project, stack


def test_a_chain_that_does_nothing_has_no_spec() -> None:
    assert clip_processing_spec(None) is None
    assert clip_processing_spec(ClipFx()) is None  # flat EQ, compressor off, no effects
    assert clip_processing_spec(ClipFx(effects=[EffectSpec(type="pitch_shift", params={"semitones": 0})])) is None
    assert clip_processing_spec(ClipFx(loudness_target_lufs=-20)) is None  # levelling off: target ignored
    spec = clip_processing_spec(ClipFx(loudness_enabled=True))
    assert spec is not None and spec["stages"] == [] and spec["loudness"]["target_lufs"] == -16.0


def test_the_key_follows_what_the_chain_does() -> None:
    spec = clip_processing_spec(BASS)
    assert spec is not None and [s["plugin"] for s in spec["stages"]] == ["low_shelf"]
    key = clip_fx_key_for(MUSIC, BASS)
    assert key == clip_fx_key(MUSIC, spec) and len(key) == 16
    assert clip_fx_key_for(SFX, BASS) != key  # another file
    assert clip_fx_key_for(MUSIC, ClipFx(eq_bass_db=4.0, loudness_target_lufs=-20)) == key  # levelling off
    assert clip_fx_key_for(MUSIC, ClipFx(eq_bass_db=5.0)) != key
    comp = ClipFx(compressor=CompressorSettings(enabled=True))
    assert clip_fx_key_for(MUSIC, comp) not in (None, key)
    assert clip_fx_key_for(MUSIC, ClipFx(eq_bass_db=99.0)) is None  # unusable: plays as it is


def test_set_clear_and_undo() -> None:
    project, stack = with_clip()
    stack.execute(SetAudioClipFx(C1, BASS))
    assert clip(project, C1).fx == BASS
    with pytest.raises(NoChange):
        SetAudioClipFx(C1, BASS).apply(project)
    stack.execute(SetAudioClipFx(C1, None))
    assert clip(project, C1).fx is None
    stack.undo()
    assert clip(project, C1).fx == BASS
    stack.undo()
    assert clip(project, C1).fx is None


def test_unusable_chains_are_refused() -> None:
    with pytest.raises(CommandError):
        SetAudioClipFx(C1, ClipFx(eq_mid_db=40.0))
    with pytest.raises(CommandError):
        SetAudioClipFx(C1, ClipFx(loudness_enabled=True, loudness_target_lufs=5.0))


def test_moves_trims_and_splits_keep_the_chain_and_the_key() -> None:
    project, stack = with_clip()
    stack.execute(SetAudioClipFx(C1, BASS))
    key = clip_fx_key_for(MUSIC, BASS)
    stack.execute(MoveAudioClip(C1, 3000))
    stack.execute(TrimAudioClip(C1, "end", 9000))
    stack.execute(SplitAudioClip(C1, 5000, right_clip_id=C2))
    assert clip(project, C1).fx == BASS and clip(project, C2).fx == BASS
    state = build_timeline(project)
    assert {c.id: c.fx_key for c in state.audio_clips} == {C1: key, C2: key}


def test_one_batch_applies_a_chain_to_several_clips() -> None:
    project, stack = with_clip()
    stack.execute(AddAudioClip(SFX, LANE2, 20_000, clip_id=C2))
    adapter = TypeAdapter(EditOp)
    ops = [
        adapter.validate_python({"op": "set_audio_clip_fx", "clip_id": cid, "fx": BASS.model_dump()})
        for cid in (C1, C2)
    ]
    with stack.group("Apply FX to 2 clips"):
        for op in ops:
            stack.execute(build_command(op))
    assert clip(project, C1).fx == BASS and clip(project, C2).fx == BASS
    stack.undo()
    assert clip(project, C1).fx is None and clip(project, C2).fx is None


def test_v9_projects_open() -> None:
    assert SCHEMA_VERSION == 10
    data = {
        "schema_version": 9,
        "name": "x",
        "audio_clips": [{"id": C1, "lane_id": LANE1, "file_id": MUSIC, "timeline_ms": 0, "out_ms": 1000}],
    }
    result = migrate(data)
    assert result["schema_version"] == 10 and result["audio_clips"][0]["fx"] is None
    project, stack = with_clip()
    stack.execute(SetAudioClipFx(C1, BASS))
    again = Project.model_validate_json(project.model_dump_json())
    assert again.audio_clips[0].fx == BASS
