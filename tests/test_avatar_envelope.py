"""Loudness envelope (M5-2): maths with synthetic signals, the cache, the endpoint."""

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile

from backend.avatar.envelope import (
    Envelope,
    compute_envelope,
    envelope_for,
    envelope_path,
)
from backend.avatar.tuning import ENVELOPE_FLOOR_DB

RATE = 24000


def tone(seconds: float, amp: float) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    return amp * np.sin(2 * np.pi * 220 * t)


def test_a_sine_reads_its_rms_level() -> None:
    env = compute_envelope(tone(1.0, 0.5), RATE)
    assert env.hop_ms == 10
    assert len(env.values) == 100
    # RMS of a 0.5 sine is 0.354, about -9.0 dBFS.
    assert all(abs(v + 9.0) < 0.3 for v in env.values[2:-2])


def test_silence_is_the_floor_and_steps_are_sharp() -> None:
    data = np.concatenate([np.zeros(RATE // 2), tone(0.5, 0.5)])
    env = compute_envelope(data, RATE)
    assert env.values[10] == ENVELOPE_FLOOR_DB
    assert env.values[48] < -40 or env.values[48] == ENVELOPE_FLOOR_DB
    assert env.values[49] > env.values[48]  # the window reaches the tone
    assert env.values[60] > -10


def test_length_rounds_up_and_empty_is_empty() -> None:
    assert len(compute_envelope(np.zeros(241), RATE).values) == 2  # 10.04 ms
    assert compute_envelope(np.zeros(0), RATE).values == ()


def test_bad_input_raises() -> None:
    with pytest.raises(ValueError):
        compute_envelope(np.zeros((2, 10)), RATE)
    with pytest.raises(ValueError):
        compute_envelope(np.array([np.nan]), RATE)
    with pytest.raises(ValueError):
        compute_envelope(np.zeros(10), 0)


def test_lookup_by_time() -> None:
    env = Envelope(10, (-20.0, -30.0))
    assert env.at(0) == -20.0
    assert env.at(19.9) == -30.0
    assert env.at(20) == ENVELOPE_FLOOR_DB
    assert env.at(-1) == ENVELOPE_FLOOR_DB
    assert env.duration_ms == 20


def write_processed(folder: Path, name: str = "abcd" * 4) -> Path:
    path = folder / "media" / "takes_fx" / f"{name}.wav"
    path.parent.mkdir(parents=True)
    soundfile.write(str(path), tone(0.3, 0.5).astype(np.float32), RATE, subtype="FLOAT")
    return path


def test_cache_is_written_and_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    processed = write_processed(tmp_path)
    first = envelope_for(processed)
    cache = envelope_path(processed)
    assert cache == tmp_path / "media" / "envelopes" / f"{processed.stem}.env.json"
    assert json.loads(cache.read_text(encoding="utf-8"))["values"] == list(first.values)

    import backend.avatar.envelope as module

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("computed again")

    monkeypatch.setattr(module, "compute_envelope", boom)
    assert envelope_for(processed) == first


def test_a_damaged_cache_is_computed_again(tmp_path: Path) -> None:
    processed = write_processed(tmp_path)
    first = envelope_for(processed)
    envelope_path(processed).write_text("{bad", encoding="utf-8")
    assert envelope_for(processed) == first
