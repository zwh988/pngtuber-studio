"""Rendering an audio clip's FX (M8-4, step 3): the renderer and the session's cache."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from pydantic import TypeAdapter

from backend.audio.clipfx import clip_processing_spec
from backend.audio.clipfx_render import AUDIO_FX_DIR, render_clip_fx
from backend.export.audioclips import AUDIO_CLIPS_NAME, write_audio_clip_track
from backend.export.errors import ExportError
from backend.export.preflight import preflight
from backend.project.edit_ops import EditOp
from backend.project.schema import ClipFx, CompressorSettings, EffectSpec
from backend.project.session import Session
from backend.project.timeline import build_timeline
from tests.test_audio_import import fake_decode, fake_probe, write_wav

RATE = 48_000


def tone(path: Path, seconds: float = 2.0, channels: int = 2) -> Path:
    t = np.arange(int(seconds * RATE)) / RATE
    left = 0.2 * np.sin(2 * np.pi * 80 * t) + 0.05 * np.sin(2 * np.pi * 5000 * t)
    data = np.stack([left, 0.5 * left][:channels], axis=1).astype(np.float32)
    sf.write(str(path), data, RATE, subtype="FLOAT")
    return path


def test_render_keeps_rate_channels_and_length(tmp_path: Path) -> None:
    src = tone(tmp_path / "in.wav")
    spec = clip_processing_spec(ClipFx(eq_bass_db=6.0, effects=[EffectSpec(type="chorus", params={})]))
    assert spec is not None
    report = render_clip_fx(src, tmp_path / "out.wav", spec)
    out, rate = sf.read(str(tmp_path / "out.wav"), dtype="float32", always_2d=True)
    original, _ = sf.read(str(src), dtype="float32", always_2d=True)
    assert rate == RATE and out.shape == original.shape == (report.samples, 2)
    assert np.max(np.abs(out - original)) > 0.01  # it did something
    # The two channels stay distinct (stereo is processed as stereo, not mixed down).
    assert not np.allclose(out[:, 0], out[:, 1])


def test_levelling_brings_the_file_near_its_target(tmp_path: Path) -> None:
    import pyloudnorm

    src = tone(tmp_path / "in.wav", seconds=4.0)
    spec = clip_processing_spec(ClipFx(loudness_enabled=True, loudness_target_lufs=-20.0))
    assert spec is not None and spec["stages"] == []
    report = render_clip_fx(src, tmp_path / "out.wav", spec)
    out, _ = sf.read(str(tmp_path / "out.wav"), dtype="float64", always_2d=True)
    level = pyloudnorm.Meter(RATE).integrated_loudness(out)
    assert abs(level - -20.0) < 0.5 and report.gain_db != 0.0
    assert np.max(np.abs(out)) <= 10 ** (-1 / 20) + 1e-6  # under the -1 dBFS ceiling


def test_compressor_on_mono(tmp_path: Path) -> None:
    src = tone(tmp_path / "in.wav", channels=1)
    spec = clip_processing_spec(ClipFx(compressor=CompressorSettings(enabled=True, threshold_db=-30.0, ratio=6.0)))
    assert spec is not None
    render_clip_fx(src, tmp_path / "out.wav", spec)
    out, _ = sf.read(str(tmp_path / "out.wav"), dtype="float32", always_2d=True)
    assert out.shape[1] == 1


@pytest.fixture
def session(tmp_path: Path) -> Session:
    session = Session(probe=fake_probe, decode=fake_decode)
    session.new_project(str(tmp_path), "Rack")
    return session


def set_fx(session: Session, clip_id: str, fx: ClipFx | None) -> None:
    op = TypeAdapter(EditOp).validate_python(
        {"op": "set_audio_clip_fx", "clip_id": clip_id, "fx": None if fx is None else fx.model_dump()}
    )
    session.edit([op])


def test_session_renders_once_per_file_and_chain(session: Session, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    result = session.import_audio([str(write_wav(outside / "a.wav", 1.0))], None, 0)
    clip_id = result.timeline.audio_clips[0].id
    assert session.audio_clip_fx_path(clip_id) is None  # no FX: plays the file
    set_fx(session, clip_id, ClipFx(eq_treble_db=-6.0))
    path = session.audio_clip_fx_path(clip_id)
    assert path is not None and path.is_file() and path.parent.name == Path(AUDIO_FX_DIR).name
    stamp = path.stat().st_mtime_ns
    move = TypeAdapter(EditOp).validate_python({"op": "move_audio_clip", "clip_id": clip_id, "timeline_ms": 4000})
    session.edit([move])
    again = session.audio_clip_fx_path(clip_id)
    assert again == path and again.stat().st_mtime_ns == stamp  # a move never re-renders
    set_fx(session, clip_id, ClipFx(eq_treble_db=-3.0))
    assert session.audio_clip_fx_path(clip_id) != path  # another chain: another file
    assert session.audio_clip_fx_path("0" * 12) is None


def test_export_mixes_the_fx_file_the_preview_plays(session: Session, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    result = session.import_audio([str(write_wav(outside / "a.wav", 1.0))], None, 0)
    clip_id = result.timeline.audio_clips[0].id
    file_id = result.timeline.audio_clips[0].file_id
    set_fx(session, clip_id, ClipFx(eq_bass_db=6.0))
    project = session.export_inputs().project
    decoded = session.audio_decoded_path(file_id)
    assert decoded is not None
    # Stand-ins with known content: the export must read the FX file for this clip.
    fx_file = tmp_path / "fx.wav"
    sf.write(str(fx_file), np.full((48_000, 2), 0.125, dtype=np.float32), 48_000, subtype="FLOAT")
    out = tmp_path / "out"
    out.mkdir()
    write_audio_clip_track(project, 1000, out, {file_id: decoded}, fx_paths={clip_id: fx_file})
    mixed, _ = sf.read(str(out / AUDIO_CLIPS_NAME), dtype="float32", always_2d=True)
    assert np.allclose(mixed[100:40_000], 0.125, atol=1e-6)  # the FX file, at 0 dB, no fades
    with pytest.raises(ExportError):
        write_audio_clip_track(project, 1000, out, {file_id: decoded}, fx_paths={})


def test_export_inputs_carry_the_rendered_file(session: Session, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    result = session.import_audio([str(write_wav(outside / "a.wav", 1.0))], None, 0)
    clip_id = result.timeline.audio_clips[0].id
    set_fx(session, clip_id, ClipFx(eq_mid_db=3.0))
    inputs = session.export_inputs()
    assert inputs.audio_fx_paths[clip_id] == session.audio_clip_fx_path(clip_id)


def test_preflight_reports_a_failed_render(session: Session, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    result = session.import_audio([str(write_wav(outside / "a.wav", 1.0))], None, 0)
    clip_id = result.timeline.audio_clips[0].id
    set_fx(session, clip_id, ClipFx(eq_mid_db=3.0))
    project = session.export_inputs().project
    report = preflight(project, build_timeline(project), audio_fx_problems={clip_id: "no Pedalboard"})
    errors = [i for i in report.issues if i.severity == "error"]
    assert [i.item_id for i in errors if i.kind == "audio_fx_failed"] == [clip_id]  # no_clips is also there: no footage
