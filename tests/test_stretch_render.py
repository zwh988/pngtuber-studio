"""Rendering a stretched copy of a take (M3-9, S8c). Needs Pedalboard for the audio tests."""

from pathlib import Path

import numpy as np
import pytest
import soundfile

from backend.voice.stretchrender import StretchError, ensure_stretched, stretched_path

RATE = 24000


def make_take(tmp_path: Path, seconds: float = 1.0, freq: float = 220.0) -> Path:
    raw = tmp_path / "media" / "takes_raw" / "t1.wav"
    raw.parent.mkdir(parents=True)
    t = np.arange(int(RATE * seconds)) / RATE
    tone = (0.3 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    soundfile.write(str(raw), tone, RATE, subtype="FLOAT", format="WAV")
    return raw


def test_the_stretched_copy_lives_in_takes_fx(tmp_path: Path) -> None:
    raw = make_take(tmp_path)
    out = stretched_path(raw, 1.25)
    assert out == tmp_path / "media" / "takes_fx" / "t1_x1250.wav"


def test_stretch_shortens_by_the_factor(tmp_path: Path) -> None:
    pytest.importorskip("pedalboard")
    raw = make_take(tmp_path)
    out = ensure_stretched(raw, 1.25)
    info = soundfile.info(str(out))
    assert info.samplerate == RATE
    assert info.channels == 1
    assert info.frames == 19200  # 24000 / 1.25


def test_pitch_is_kept(tmp_path: Path) -> None:
    pytest.importorskip("pedalboard")
    raw = make_take(tmp_path, seconds=2.0, freq=220.0)
    data, rate = soundfile.read(str(ensure_stretched(raw, 1.25)), dtype="float32")
    spectrum = np.abs(np.fft.rfft(data))
    peak_hz = np.argmax(spectrum) * rate / data.size
    assert abs(peak_hz - 220.0) < 10.0


def test_the_raw_take_is_not_touched(tmp_path: Path) -> None:
    pytest.importorskip("pedalboard")
    raw = make_take(tmp_path)
    before = raw.read_bytes()
    ensure_stretched(raw, 1.1)
    assert raw.read_bytes() == before


def test_an_existing_copy_is_reused(tmp_path: Path) -> None:
    pytest.importorskip("pedalboard")
    raw = make_take(tmp_path)
    first = ensure_stretched(raw, 1.1)
    stamp = first.stat().st_mtime_ns
    assert ensure_stretched(raw, 1.1) == first
    assert first.stat().st_mtime_ns == stamp


def test_no_temp_files_are_left(tmp_path: Path) -> None:
    pytest.importorskip("pedalboard")
    raw = make_take(tmp_path)
    ensure_stretched(raw, 1.1)
    assert [p.name for p in (tmp_path / "media" / "takes_fx").iterdir()] == ["t1_x1100.wav"]


@pytest.mark.parametrize("bad", [1.0, 0.9, 1.26, float("nan")])
def test_stretch_outside_range_is_refused(tmp_path: Path, bad: float) -> None:
    with pytest.raises(StretchError):
        ensure_stretched(make_take(tmp_path), bad)


def test_missing_take_file_is_a_stretch_error(tmp_path: Path) -> None:
    with pytest.raises(StretchError):
        ensure_stretched(tmp_path / "media" / "takes_raw" / "nope.wav", 1.1)
