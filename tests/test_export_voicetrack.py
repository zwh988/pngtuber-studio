"""Export voice tracks (M6-2): schedule, mixing, line file names, the writer, and the
raw-aligned take from a real session."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile

from backend.export.errors import ExportCancelled, ExportError
from backend.export.voicetrack import (
    LINES_DIR,
    PROCESSED_NAME,
    RAW_NAME,
    VoiceCue,
    line_file_name,
    mix_cues,
    ms_to_samples,
    voice_schedule,
    write_voice_tracks,
)
from backend.project.edit_ops import AddPlacementOp
from backend.project.line_ops import AddLineOp
from backend.project.schema import Clip, Source
from backend.project.session import Session
from backend.project.timeline import TimelinePlacement, TimelineState
from backend.voice.takes import NewTake

RATE = 24_000


def placed(pid: str, start: int | None, *, take: str | None = "t", orphaned: bool = False) -> TimelinePlacement:
    return TimelinePlacement(
        id=pid,
        line_id="l",
        line_text="Hi " + pid,
        allow_overlap=False,
        take_id=take,
        duration_ms=None if take is None else 500,
        start_ms=start,
        end_ms=None,
        anchor_clip_id="c",
        anchor_source_ms=0,
        orphaned=orphaned,
        stretch=1.1,
    )


def test_schedule_keeps_only_playing_placements_in_time_order() -> None:
    state = TimelineState(
        placements=[
            placed("b", 2000),
            placed("o", 100, orphaned=True),
            placed("n", None),
            placed("q", 50, take=None),
            placed("a", 1000),
            placed("c", 1000),
        ]
    )
    cues = voice_schedule(state)
    assert [c.placement_id for c in cues] == ["a", "c", "b"]
    assert cues[0] == VoiceCue("a", "t", 1.1, 1000, 500, "Hi a")


def test_ms_to_samples_is_exact() -> None:
    assert ms_to_samples(1000, RATE) == 24_000
    assert ms_to_samples(1, 44_100) == 44  # 44.1 rounds down
    assert ms_to_samples(10, 44_150) == 442  # 441.5 rounds half up


def test_mix_sums_overlaps_and_cuts_the_tail() -> None:
    one = np.full(RATE // 2, 0.6, dtype=np.float32)  # 500 ms
    track, peak, cut = mix_cues([(0, one), (250, one), (900, one)], RATE, 1000)
    assert track.size == RATE
    assert track[ms_to_samples(100, RATE)] == pytest.approx(0.6)
    assert track[ms_to_samples(300, RATE)] == pytest.approx(1.2)  # summed, not clipped
    assert track[ms_to_samples(800, RATE)] == 0.0
    assert peak == pytest.approx(1.2)
    assert cut == 400  # the last line runs 400 ms past the end
    _, _, late = mix_cues([(5000, one)], RATE, 1000)
    assert late == 500


def test_line_file_names() -> None:
    assert line_file_name(1, 65_400, "Hello, there!") == "001_01-05_hello-there.wav"
    assert line_file_name(12, 0, "Café déjà vu") == "012_00-00_cafe-deja-vu.wav"
    assert line_file_name(3, 0, "???") == "003_00-00_line.wav"
    assert len(line_file_name(1, 0, "word " * 40)) <= len("001_00-00_.wav") + 32


def write_wav(path: Path, value: float, n: int, rate: int = RATE) -> Path:
    soundfile.write(str(path), np.full(n, value, dtype=np.float32), rate, subtype="FLOAT")
    return path


def test_writer_makes_both_tracks_and_the_line_files(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    files = {"a": write_wav(src / "a.wav", 0.5, 12_000), "b": write_wav(src / "b.wav", 0.25, 12_000)}
    cues = [VoiceCue("a", "a", 1.0, 0, 500, "first"), VoiceCue("b", "b", 1.0, 250, 500, "second")]
    seen: list[float] = []
    report = write_voice_tracks(
        cues,
        1000,
        tmp_path / "out",
        processed_for=lambda cue: files[cue.take_id],
        raw_for=lambda cue: (np.full(12_000, 0.1, dtype=np.float32), RATE),
        progress=seen.append,
    )
    assert report.lines == 2 and report.sample_rate == RATE and report.samples == RATE
    assert report.peak == pytest.approx(0.75) and report.cut_ms == 0
    processed, rate = soundfile.read(str(tmp_path / "out" / PROCESSED_NAME), dtype="float32")
    assert rate == RATE and processed.size == RATE
    assert soundfile.info(str(tmp_path / "out" / PROCESSED_NAME)).subtype == "FLOAT"
    assert processed[ms_to_samples(300, RATE)] == pytest.approx(0.75)
    raw, _ = soundfile.read(str(tmp_path / "out" / RAW_NAME), dtype="float32")
    assert raw[ms_to_samples(300, RATE)] == pytest.approx(0.2)
    names = sorted(p.name for p in (tmp_path / "out" / LINES_DIR).iterdir())
    assert names == ["001_00-00_first.wav", "002_00-00_second.wav"]
    assert seen[-1] == 1.0 and seen == sorted(seen)


def test_writer_with_no_lines_writes_silent_tracks(tmp_path: Path) -> None:
    report = write_voice_tracks(
        [], 500, tmp_path, processed_for=lambda c: Path(), raw_for=lambda c: (np.zeros(1), RATE)
    )
    assert report.lines == 0 and report.samples == RATE // 2
    assert soundfile.info(str(tmp_path / RAW_NAME)).frames == RATE // 2


def test_writer_refuses_mixed_rates_and_stops_on_cancel(tmp_path: Path) -> None:
    a = write_wav(tmp_path / "a.wav", 0.5, 100)
    b = write_wav(tmp_path / "b.wav", 0.5, 100, rate=48_000)
    cues = [VoiceCue("a", "a", 1.0, 0, 5, "x"), VoiceCue("b", "b", 1.0, 10, 5, "y")]
    with pytest.raises(ExportError, match="sample rates"):
        write_voice_tracks(
            cues,
            100,
            tmp_path / "out",
            processed_for=lambda cue: a if cue.take_id == "a" else b,
            raw_for=lambda cue: (np.zeros(100, dtype=np.float32), RATE),
        )
    with pytest.raises(ExportCancelled):
        write_voice_tracks(
            cues,
            100,
            tmp_path / "out2",
            processed_for=lambda cue: a,
            raw_for=lambda cue: (np.zeros(100, dtype=np.float32), RATE),
            should_stop=lambda: True,
        )


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


SRC, CLIP, LINE, TAKE = "1" * 12, "2" * 12, "3" * 12, "4" * 12


def test_aligned_raw_take_matches_the_processed_length(tmp_path: Path) -> None:
    pytest.importorskip("pedalboard")
    pytest.importorskip("pyloudnorm")
    session = Session(probe=fake_probe)
    session.new_project(str(tmp_path), "Rack")
    stack = session._stack
    assert stack is not None
    stack.project.sources.append(
        Source(id=SRC, path="footage/a.mkv", duration_ms=60_000, fps_num=30, width=1920, height=1080)
    )
    stack.project.clips.append(Clip(id=CLIP, source_id=SRC, in_ms=0, out_ms=10_000))
    session.edit_lines([AddLineOp(line_id=LINE, text="hello")])
    t = np.arange(RATE) / RATE
    audio = np.zeros(int(RATE * 1.5), dtype=np.float32)
    audio[RATE // 4 : RATE // 4 + RATE] = 0.4 * np.sin(2 * np.pi * 220 * t)
    session.add_take(
        NewTake(
            line_id=LINE, seed=1, text="hello", exaggeration=0.5, cfg_weight=0.5,
            voice_profile_id="6" * 12, model_version="t", raw_key="a" * 64, take_id=TAKE,
        ),
        audio,
        RATE,
    )
    session.edit([AddPlacementOp(line_id=LINE, timeline_ms=3000)])
    for stretch in (1.0, 1.1):
        processed = session.processed_take_path(TAKE, stretch)
        assert processed is not None
        aligned = session.aligned_raw_take(TAKE, stretch)
        assert aligned is not None
        samples, rate = aligned
        assert rate == RATE
        assert samples.size == soundfile.info(str(processed)).frames
        assert float(np.max(np.abs(samples))) == pytest.approx(0.4, abs=0.02)  # no loudness gain
    assert session.aligned_raw_take("9" * 12) is None
    cues = voice_schedule(session.timeline())
    assert [c.start_ms for c in cues] == [3000]
