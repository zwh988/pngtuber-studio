"""Processed take cache and trim sidecars (M4-1, S3a). No Pedalboard needed:
the render step is replaced by a fake."""

import json
import os
import threading
from pathlib import Path

import numpy as np
import pytest
import soundfile

from backend.audio import processed
from backend.audio.processed import (
    TrimCache,
    ensure_processed,
    processed_path,
    sidecar_path,
    trim_bounds_for,
)
from backend.audio.render import ProcessError

RATE = 24000
SPEC: dict[str, object] = {"version": 1, "stages": [], "loudness": {"target_lufs": -16}}


def make_take(folder: Path, name: str = "t1", *, amp: float = 0.3) -> Path:
    """0.5 s silence, 1 s tone, 0.5 s silence."""
    raw = folder / "media" / "takes_raw" / f"{name}.wav"
    raw.parent.mkdir(parents=True, exist_ok=True)
    tone = amp * np.sin(2 * np.pi * 220 * np.arange(RATE) / RATE)
    data = np.concatenate(
        [np.zeros(RATE // 2), tone, np.zeros(RATE // 2)]
    ).astype(np.float32)
    soundfile.write(str(raw), data, RATE, subtype="FLOAT", format="WAV")
    return raw


def bump_mtime(path: Path, seconds: float) -> None:
    stat = path.stat()
    ns = stat.st_mtime_ns + int(seconds * 1e9)
    os.utime(path, ns=(ns, ns))


def test_bounds_are_measured_and_a_sidecar_is_written(tmp_path: Path) -> None:
    raw = make_take(tmp_path)
    bounds = trim_bounds_for(raw)
    assert bounds.total == RATE * 2
    assert 0 < bounds.start < RATE // 2
    assert RATE * 3 // 2 < bounds.end < bounds.total
    assert not bounds.silent
    data = json.loads(sidecar_path(raw).read_text(encoding="utf-8"))
    assert data["start"] == bounds.start
    assert data["end"] == bounds.end


def test_a_valid_sidecar_is_used_without_measuring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = make_take(tmp_path)
    first = trim_bounds_for(raw)

    def boom(_path: Path, *_cuts: int | None) -> None:
        raise AssertionError("measured again")

    monkeypatch.setattr(processed, "measure_bounds", boom)
    assert trim_bounds_for(raw) == first


def test_a_damaged_sidecar_is_measured_again_and_rewritten(tmp_path: Path) -> None:
    raw = make_take(tmp_path)
    first = trim_bounds_for(raw)
    sidecar_path(raw).write_text("{not json", encoding="utf-8")
    assert trim_bounds_for(raw) == first
    json.loads(sidecar_path(raw).read_text(encoding="utf-8"))  # valid again


def test_a_sidecar_for_a_different_length_is_ignored(tmp_path: Path) -> None:
    raw = make_take(tmp_path)
    trim_bounds_for(raw)
    side = sidecar_path(raw)
    data = json.loads(side.read_text(encoding="utf-8"))
    data["total"] += 1
    side.write_text(json.dumps(data), encoding="utf-8")
    bump_mtime(side, 5)
    assert trim_bounds_for(raw).total == RATE * 2


def test_a_sidecar_older_than_the_take_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = make_take(tmp_path)
    trim_bounds_for(raw)
    bump_mtime(raw, 60)  # the take is now newer than its sidecar
    calls: list[Path] = []
    real = processed.measure_bounds

    def counting(path: Path, *cuts: int | None):
        calls.append(path)
        return real(path, *cuts)

    monkeypatch.setattr(processed, "measure_bounds", counting)
    trim_bounds_for(raw)
    assert len(calls) == 1


def test_memory_cache_skips_disk_until_the_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = make_take(tmp_path)
    cache = TrimCache()
    first = trim_bounds_for(raw, cache)
    sidecar_path(raw).unlink()

    def boom(_path: Path, *_cuts: int | None) -> None:
        raise AssertionError("measured again")

    monkeypatch.setattr(processed, "measure_bounds", boom)
    assert trim_bounds_for(raw, cache) == first  # served from memory
    bump_mtime(raw, 60)
    with pytest.raises(AssertionError):
        trim_bounds_for(raw, cache)  # file changed: the cache entry no longer matches


def test_missing_take_file_is_a_process_error(tmp_path: Path) -> None:
    with pytest.raises(ProcessError, match="not found"):
        trim_bounds_for(tmp_path / "media" / "takes_raw" / "nope.wav")


def test_processed_path_depends_on_every_input(tmp_path: Path) -> None:
    raw = make_take(tmp_path)
    base = processed_path(raw, "a" * 64, 1.0, SPEC)
    assert base.parent == tmp_path / "media" / "takes_fx"
    assert base.suffix == ".wav"
    assert processed_path(raw, "a" * 64, 1.0, SPEC) == base
    assert processed_path(raw, "b" * 64, 1.0, SPEC) != base
    assert processed_path(raw, "a" * 64, 1.08, SPEC) != base
    other = {**SPEC, "stages": [{"plugin": "chorus", "mix": 0.5}]}
    assert processed_path(raw, "a" * 64, 1.0, other) != base


def test_bad_stretch_is_refused(tmp_path: Path) -> None:
    raw = make_take(tmp_path)
    for bad in (0.9, 1.5, float("nan")):
        with pytest.raises(ProcessError, match="stretch"):
            processed_path(raw, "a" * 64, bad, SPEC)


def _fake_render(calls: list[Path]):
    def fake(raw_path, dest, spec, stretch, bounds):
        calls.append(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")

    return fake


def test_a_processed_file_is_rendered_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = make_take(tmp_path)
    calls: list[Path] = []
    monkeypatch.setattr(processed, "render_processed", _fake_render(calls))
    first = ensure_processed(raw, "a" * 64, 1.0, SPEC)
    second = ensure_processed(raw, "a" * 64, 1.0, SPEC)
    assert first == second
    assert len(calls) == 1
    ensure_processed(raw, "a" * 64, 1.08, SPEC)  # another stretch: another file
    assert len(calls) == 2


def test_reuse_refreshes_the_modification_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = make_take(tmp_path)
    monkeypatch.setattr(processed, "render_processed", _fake_render([]))
    path = ensure_processed(raw, "a" * 64, 1.0, SPEC)
    bump_mtime(path, -3600)
    old = path.stat().st_mtime_ns
    ensure_processed(raw, "a" * 64, 1.0, SPEC)
    assert path.stat().st_mtime_ns > old


def test_parallel_requests_render_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = make_take(tmp_path)
    calls: list[Path] = []
    fake = _fake_render(calls)

    def slow(raw_path, dest, spec, stretch, bounds):
        threading.Event().wait(0.05)
        fake(raw_path, dest, spec, stretch, bounds)

    monkeypatch.setattr(processed, "render_processed", slow)
    results: list[Path] = []
    threads = [
        threading.Thread(
            target=lambda: results.append(ensure_processed(raw, "a" * 64, 1.0, SPEC))
        )
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1
    assert len(set(results)) == 1 and len(results) == 8
