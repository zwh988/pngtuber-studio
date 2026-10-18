"""Waveform peaks: the pure maths and the file wrapper."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend.voice.peaks import (
    PeaksError,
    build_peaks_report,
    compute_peaks,
    read_take_peaks,
)


def test_one_pair_per_bucket() -> None:
    lows, highs = compute_peaks(np.linspace(-1, 1, 1000), 7)
    assert len(lows) == 7
    assert len(highs) == 7


def test_known_values() -> None:
    lows, highs = compute_peaks(np.array([0.0, 0.5, -0.25, 0.1]), 2)
    assert lows == [0.0, -0.25]
    assert highs == [0.5, 0.1]


def test_a_ramp_rises_from_bucket_to_bucket() -> None:
    lows, highs = compute_peaks(np.linspace(-1, 1, 1000), 4)
    assert lows[0] == -1.0
    assert highs[-1] == 1.0
    assert highs == sorted(highs)
    assert all(low <= high for low, high in zip(lows, highs, strict=True))


def test_fewer_samples_than_buckets_still_fills_every_bucket() -> None:
    lows, highs = compute_peaks(np.array([0.1, 0.2, 0.3]), 8)
    assert len(lows) == 8
    assert set(lows) <= {0.1, 0.2, 0.3}
    assert set(highs) <= {0.1, 0.2, 0.3}


def test_empty_and_silent_input_give_zeros() -> None:
    assert compute_peaks(np.array([]), 5) == ([0.0] * 5, [0.0] * 5)
    assert compute_peaks(np.zeros(100), 4) == ([0.0] * 4, [0.0] * 4)


def test_values_are_clipped_and_not_a_number_counts_as_silence() -> None:
    lows, highs = compute_peaks(np.array([2.0, -3.0, np.nan, 0.0]), 1)
    assert lows == [-1.0]
    assert highs == [1.0]


def test_zero_buckets_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        compute_peaks(np.zeros(10), 0)


def test_report_gives_the_duration() -> None:
    report = build_peaks_report("t", np.zeros(12_000), 24_000, 8)
    assert report.take_id == "t"
    assert report.duration_ms == 500
    assert report.sample_rate == 24_000
    assert report.buckets == 8
    assert len(report.lows) == 8


def test_report_refuses_a_bad_sample_rate() -> None:
    with pytest.raises(ValueError, match="positive"):
        build_peaks_report("t", np.zeros(10), 0, 8)


def write_tone(path: Path) -> None:
    t = np.arange(12_000) / 24_000
    data = (0.5 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(str(path), data, 24_000, subtype="FLOAT")


def test_read_take_peaks_from_a_wav(tmp_path: Path) -> None:
    path = tmp_path / "take.wav"
    write_tone(path)
    report = read_take_peaks(path, "t", 16)
    assert report.duration_ms == 500
    assert len(report.lows) == 16
    assert len(report.highs) == 16
    assert max(report.highs) > 0.45
    assert min(report.lows) < -0.45


def test_read_take_peaks_is_cached_for_an_unchanged_file(tmp_path: Path) -> None:
    path = tmp_path / "take.wav"
    write_tone(path)
    assert read_take_peaks(path, "t", 16) is read_take_peaks(path, "t", 16)


def test_read_take_peaks_refuses_a_bucket_count_out_of_range(tmp_path: Path) -> None:
    path = tmp_path / "take.wav"
    write_tone(path)
    with pytest.raises(PeaksError):
        read_take_peaks(path, "t", 4)
    with pytest.raises(PeaksError):
        read_take_peaks(path, "t", 5000)


def test_read_take_peaks_reports_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PeaksError):
        read_take_peaks(tmp_path / "gone.wav", "t", 16)
