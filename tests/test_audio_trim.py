"""Silence trimming maths, lengths and the sidecar encoding (M4-1). No audio files."""

import json

import numpy as np
import pytest

from backend.audio.trim import (
    TrimBounds,
    bounds_from_data,
    bounds_to_data,
    find_speech_bounds,
    processed_duration_ms,
    processed_samples,
    samples_to_ms,
    sidecar_name,
    trim_params,
    trimmed_duration_ms,
)

RATE = 24000


def silence(ms: int) -> np.ndarray:
    return np.zeros(RATE * ms // 1000, dtype=np.float32)


def tone(ms: int, amp: float = 0.1) -> np.ndarray:
    n = RATE * ms // 1000
    t = np.arange(n) / RATE
    return (amp * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def test_trims_both_sides_with_padding() -> None:
    # 300 ms silence, 500 ms tone, 400 ms silence: tone is frames 30..79 (10 ms frames)
    audio = np.concatenate([silence(300), tone(500), silence(400)])
    b = find_speech_bounds(audio, RATE)
    assert b.start == 30 * 240 - 960  # 40 ms before
    assert b.end == 80 * 240 + 1920  # 80 ms after
    assert b.total == audio.size
    assert not b.silent


def test_no_leading_silence_starts_at_zero() -> None:
    audio = np.concatenate([tone(500), silence(400)])
    b = find_speech_bounds(audio, RATE)
    assert b.start == 0


def test_padding_never_runs_past_the_ends() -> None:
    audio = np.concatenate([silence(20), tone(500), silence(30)])
    b = find_speech_bounds(audio, RATE)
    assert b.start == 0
    assert b.end == audio.size


def test_quiet_noise_below_threshold_is_silent() -> None:
    audio = tone(500, amp=0.001)  # about -63 dBFS
    b = find_speech_bounds(audio, RATE)
    assert b.silent
    assert (b.start, b.end) == (0, audio.size)


def test_all_zeros_keeps_the_whole_take() -> None:
    audio = silence(500)
    b = find_speech_bounds(audio, RATE)
    assert b.silent
    assert b.kept == audio.size


def test_empty_take() -> None:
    b = find_speech_bounds(np.zeros(0, dtype=np.float32), RATE)
    assert b == TrimBounds(0, 0, 0, RATE, silent=True)


def test_threshold_can_be_changed() -> None:
    quiet = np.concatenate([silence(200), tone(300, amp=0.004), silence(200)])  # ~ -51 dBFS
    assert find_speech_bounds(quiet, RATE).silent
    b = find_speech_bounds(quiet, RATE, threshold_db=-60.0)
    assert not b.silent
    assert b.start == 20 * 240 - 960


def test_partial_last_frame_is_handled() -> None:
    audio = np.concatenate([silence(100), tone(205)])  # 205 ms: last frame is partial
    b = find_speech_bounds(audio, RATE)
    assert b.end == audio.size


def test_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        find_speech_bounds(np.zeros((2, 100), dtype=np.float32), RATE)
    with pytest.raises(ValueError):
        find_speech_bounds(np.array([0.0, np.nan], dtype=np.float32), RATE)
    with pytest.raises(ValueError):
        find_speech_bounds(tone(100), 0)


def test_samples_to_ms_rounds_half_up() -> None:
    assert samples_to_ms(24000, RATE) == 1000
    assert samples_to_ms(12, RATE) == 1  # 0.5 ms
    assert samples_to_ms(11, RATE) == 0
    with pytest.raises(ValueError):
        samples_to_ms(-1, RATE)


def test_processed_lengths() -> None:
    b = TrimBounds(0, 24000, 30000, RATE)
    assert trimmed_duration_ms(b) == 1000
    assert processed_duration_ms(b, 1.0) == 1000
    assert processed_duration_ms(b, 1.25) == 800
    assert processed_samples(24000, 1.25) == 19200
    # stretch 1.0 keeps the length exactly
    assert processed_samples(12345, 1.0) == 12345


def test_processed_length_uses_the_trimmed_part_only() -> None:
    b = TrimBounds(6000, 18000, 30000, RATE)  # 12000 kept = 500 ms
    assert trimmed_duration_ms(b) == 500
    assert processed_duration_ms(b, 1.25) == 400


def test_sidecar_name() -> None:
    assert sidecar_name("abc123") == "abc123.trim.json"
    with pytest.raises(ValueError):
        sidecar_name("")


def test_sidecar_round_trip_through_json() -> None:
    b = TrimBounds(960, 21120, 28800, RATE)
    data = json.loads(json.dumps(bounds_to_data(b)))
    assert bounds_from_data(data, expect_total=28800) == b
    assert bounds_from_data(data) == b


def test_sidecar_is_stale_when_settings_changed() -> None:
    data = bounds_to_data(TrimBounds(0, 100, 200, RATE))
    data["params"]["threshold_db"] = -40.0
    assert bounds_from_data(data) is None


def test_sidecar_is_stale_when_the_take_length_differs() -> None:
    data = bounds_to_data(TrimBounds(0, 100, 200, RATE))
    assert bounds_from_data(data, expect_total=201) is None


def test_sidecar_is_stale_when_version_differs() -> None:
    data = bounds_to_data(TrimBounds(0, 100, 200, RATE))
    data["version"] = 99
    assert bounds_from_data(data) is None


@pytest.mark.parametrize(
    "change",
    [
        {"start": -1},
        {"start": 150, "end": 100},
        {"end": 201},
        {"start": True},
        {"start": 1.5},
        {"sample_rate": 0},
        {"silent": "no"},
    ],
)
def test_damaged_sidecar_is_ignored(change: dict) -> None:
    data = bounds_to_data(TrimBounds(0, 100, 200, RATE))
    data.update(change)
    assert bounds_from_data(data) is None


def test_missing_field_or_wrong_shape_is_ignored() -> None:
    data = bounds_to_data(TrimBounds(0, 100, 200, RATE))
    del data["total"]
    assert bounds_from_data(data) is None
    assert bounds_from_data([1, 2]) is None
    assert bounds_from_data(None) is None


def test_trim_params_are_plain_numbers() -> None:
    params = trim_params()
    assert set(params) == {"threshold_db", "frame_ms", "pad_before_ms", "pad_after_ms"}
    json.dumps(params)
