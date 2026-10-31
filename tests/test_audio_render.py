"""Rendering a processed take (M4-1, S3a). Needs Pedalboard and pyloudnorm; the
tests are skipped when either is missing."""

import hashlib
import itertools
from pathlib import Path

import numpy as np
import pytest
import soundfile

pytest.importorskip("pedalboard")
pyloudnorm = pytest.importorskip("pyloudnorm")

from backend.audio.chainspec import processing_spec
from backend.audio.fxpresets import load_fx_presets_file
from backend.audio.loudness import CEILING_DB, db_to_linear
from backend.audio.processed import trim_bounds_for
from backend.audio.render import (
    ProcessError,
    read_mono,
    render_processed,
)
from backend.audio.trim import TrimBounds, processed_samples
from backend.project.schema import FxChain

RATE = 24000
_RENDERS = itertools.count()


def clean_chain(**changes: float) -> FxChain:
    chain = load_fx_presets_file()["Clean"]
    return chain.model_copy(update=changes)


def speech_like(seconds: float = 1.5, amp: float = 0.2, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    noise = np.clip(rng.standard_normal(n), -3, 3) / 3 * amp
    t = np.arange(n) / RATE
    envelope = 0.6 + 0.4 * np.sin(2 * np.pi * 4 * t) ** 2
    return (noise * envelope).astype(np.float32)


def make_take(
    folder: Path, body: np.ndarray, name: str = "t1", lead: float = 0.4
) -> Path:
    raw = folder / "media" / "takes_raw" / f"{name}.wav"
    raw.parent.mkdir(parents=True, exist_ok=True)
    pad = np.zeros(int(lead * RATE), dtype=np.float32)
    soundfile.write(
        str(raw), np.concatenate([pad, body, pad]), RATE, subtype="FLOAT", format="WAV"
    )
    return raw


def render(raw: Path, chain: FxChain, stretch: float = 1.0):
    bounds = trim_bounds_for(raw)
    # A file of its own per render, so two renders can be compared.
    dest = raw.parent.parent / "takes_fx" / f"{raw.stem}-{next(_RENDERS)}.wav"
    report = render_processed(raw, dest, processing_spec(chain), stretch, bounds)
    return report, dest, bounds


def lufs(path: Path) -> float:
    samples, rate = read_mono(path)
    return float(pyloudnorm.Meter(rate).integrated_loudness(samples.astype(np.float64)))


def test_length_matches_the_timeline_arithmetic(tmp_path: Path) -> None:
    raw = make_take(tmp_path, speech_like())
    for stretch in (1.0, 1.08, 1.25):
        report, dest, bounds = render(raw, clean_chain(), stretch)
        assert report.samples == processed_samples(bounds.kept, stretch)
        written, rate = read_mono(dest)
        assert written.size == report.samples
        assert rate == RATE
    assert bounds.kept < bounds.total  # the silence at both ends was trimmed


def test_loudness_lands_on_the_target(tmp_path: Path) -> None:
    raw = make_take(tmp_path, speech_like(amp=0.2))
    report, dest, _ = render(raw, clean_chain(loudness_target_lufs=-20.0))
    assert report.basis == "lufs"
    assert not report.limited
    assert abs(lufs(dest) - (-20.0)) < 1.0


def test_two_takes_of_different_levels_end_up_equally_loud(tmp_path: Path) -> None:
    quiet = make_take(tmp_path, speech_like(amp=0.05), "quiet")
    loud = make_take(tmp_path, speech_like(amp=0.3, seed=1), "loud")
    chain = clean_chain(loudness_target_lufs=-20.0)
    _, quiet_out, _ = render(quiet, chain)
    _, loud_out, _ = render(loud, chain)
    assert abs(lufs(quiet_out) - lufs(loud_out)) < 1.0


def test_nothing_clips_even_when_asked_for_the_loudest_target(tmp_path: Path) -> None:
    raw = make_take(tmp_path, speech_like(amp=0.9))
    report, dest, _ = render(raw, clean_chain(loudness_target_lufs=-5.0))
    written, _ = read_mono(dest)
    assert float(np.max(np.abs(written))) <= db_to_linear(CEILING_DB) + 1e-6
    assert report.limited


def test_silence_is_kept_and_gets_no_gain(tmp_path: Path) -> None:
    raw = tmp_path / "media" / "takes_raw" / "quiet.wav"
    raw.parent.mkdir(parents=True)
    soundfile.write(str(raw), np.zeros(RATE, dtype=np.float32), RATE, subtype="FLOAT")
    report, dest, bounds = render(raw, clean_chain())
    assert bounds.silent
    assert report.silent
    assert report.gain_db == 0.0
    written, _ = read_mono(dest)
    assert written.size == RATE
    assert not np.any(written)


def test_a_take_under_400_ms_is_measured_by_rms(tmp_path: Path) -> None:
    raw = make_take(tmp_path, speech_like(seconds=0.2, amp=0.2), lead=0.1)
    report, dest, _ = render(raw, clean_chain())
    assert report.basis == "rms"
    assert read_mono(dest)[0].size == report.samples


def test_the_raw_take_is_never_changed(tmp_path: Path) -> None:
    raw = make_take(tmp_path, speech_like())
    before = hashlib.sha256(raw.read_bytes()).hexdigest()
    render(raw, clean_chain(), 1.1)
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == before


def test_a_treble_boost_changes_the_sound(tmp_path: Path) -> None:
    raw = make_take(tmp_path, speech_like())
    _, plain, _ = render(raw, clean_chain())
    _, bright, _ = render(raw, clean_chain(eq_treble_db=12.0))

    def high_to_low(path: Path) -> float:
        samples, rate = read_mono(path)
        power = np.abs(np.fft.rfft(samples)) ** 2
        freqs = np.fft.rfftfreq(samples.size, 1 / rate)
        return float(power[freqs > 4000].sum() / power[freqs < 1000].sum())

    assert high_to_low(bright) > high_to_low(plain) * 2


def test_bounds_of_another_file_are_refused(tmp_path: Path) -> None:
    raw = make_take(tmp_path, speech_like())
    wrong = TrimBounds(0, 100, 100, RATE)
    with pytest.raises(ProcessError, match="do not match"):
        render_processed(
            raw, tmp_path / "out.wav", processing_spec(clean_chain()), 1.0, wrong
        )


def test_a_stretch_out_of_range_is_refused(tmp_path: Path) -> None:
    raw = make_take(tmp_path, speech_like())
    bounds = trim_bounds_for(raw)
    for bad in (0.9, 1.5):
        with pytest.raises(ProcessError, match="stretch"):
            render_processed(
                raw, tmp_path / "out.wav", processing_spec(clean_chain()), bad, bounds
            )
