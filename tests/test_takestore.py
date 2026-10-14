"""Take files on disk (M3-4)."""

from pathlib import Path

import numpy as np
import pytest
import soundfile

from backend.voice.takes import TakeError
from backend.voice.takestore import TakeStore

REL = "media/takes_raw/aaaaaaaaaaaa.wav"
RATE = 24000


def tone(samples: int = 2400) -> np.ndarray:
    t = np.arange(samples) / RATE
    return (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def test_write_raw_writes_a_readable_mono_float32_wav(tmp_path: Path) -> None:
    store = TakeStore(tmp_path)
    duration = store.write_raw(REL, tone(), RATE)
    assert duration == 100
    data, rate = soundfile.read(tmp_path / REL, dtype="float32")
    assert rate == RATE
    assert data.ndim == 1
    assert soundfile.info(str(tmp_path / REL)).subtype == "FLOAT"
    assert np.array_equal(data, tone())


def test_write_raw_leaves_no_temp_file_and_can_overwrite(tmp_path: Path) -> None:
    store = TakeStore(tmp_path)
    store.write_raw(REL, tone(2400), RATE)
    store.write_raw(REL, tone(4800), RATE)
    names = [p.name for p in (tmp_path / "media" / "takes_raw").iterdir()]
    assert names == ["aaaaaaaaaaaa.wav"]
    assert soundfile.info(str(tmp_path / REL)).frames == 4800


@pytest.mark.parametrize(
    "samples",
    [np.zeros(0, dtype=np.float32), np.zeros((10, 2), dtype=np.float32), np.array([0.0, np.nan])],
)
def test_write_raw_rejects_bad_audio(tmp_path: Path, samples: np.ndarray) -> None:
    store = TakeStore(tmp_path)
    with pytest.raises(TakeError):
        store.write_raw(REL, samples, RATE)
    assert not (tmp_path / REL).exists()


def test_write_raw_rejects_a_bad_sample_rate(tmp_path: Path) -> None:
    with pytest.raises(TakeError, match="sample_rate"):
        TakeStore(tmp_path).write_raw(REL, tone(), 0)


@pytest.mark.parametrize(
    "rel", ["media/voice/x.wav", "x.wav", "media/takes_raw/../x.wav", "/media/takes_raw/x.wav"]
)
def test_paths_outside_the_take_folder_are_refused(tmp_path: Path, rel: str) -> None:
    with pytest.raises(TakeError, match="take files live in"):
        TakeStore(tmp_path).path(rel)


def test_copy_raw(tmp_path: Path) -> None:
    store = TakeStore(tmp_path)
    store.write_raw(REL, tone(), RATE)
    copy = "media/takes_raw/bbbbbbbbbbbb.wav"
    store.copy_raw(REL, copy)
    assert (tmp_path / copy).read_bytes() == (tmp_path / REL).read_bytes()
    assert sorted(p.name for p in (tmp_path / "media" / "takes_raw").iterdir()) == [
        "aaaaaaaaaaaa.wav",
        "bbbbbbbbbbbb.wav",
    ]


def test_copy_raw_missing_source(tmp_path: Path) -> None:
    with pytest.raises(TakeError, match="cannot copy"):
        TakeStore(tmp_path).copy_raw(REL, "media/takes_raw/bbbbbbbbbbbb.wav")
    assert not (tmp_path / "media" / "takes_raw" / "bbbbbbbbbbbb.wav").exists()


def test_size(tmp_path: Path) -> None:
    store = TakeStore(tmp_path)
    assert store.size(REL) is None
    store.write_raw(REL, tone(), RATE)
    assert store.size(REL) == (tmp_path / REL).stat().st_size
    assert store.size("media/voice/x.wav") is None


def test_unreferenced_lists_only_unknown_files(tmp_path: Path) -> None:
    store = TakeStore(tmp_path)
    assert store.unreferenced([]) == {}  # folder does not exist yet
    store.write_raw(REL, tone(), RATE)
    folder = tmp_path / "media" / "takes_raw"
    (folder / "stray.wav").write_bytes(b"12345")
    (folder / "half.wav.tmp").write_bytes(b"12")
    (folder / "subdir").mkdir()
    assert store.unreferenced([REL]) == {
        "media/takes_raw/half.wav.tmp": 2,
        "media/takes_raw/stray.wav": 5,
    }


def test_delete_files(tmp_path: Path) -> None:
    store = TakeStore(tmp_path)
    store.write_raw(REL, tone(), RATE)
    folder = tmp_path / "media" / "takes_raw"
    (folder / "stuck.wav").mkdir()  # a directory cannot be unlinked as a file
    failed = store.delete_files(
        [REL, "media/takes_raw/missing.wav", "media/takes_raw/stuck.wav"]
    )
    assert failed == ["media/takes_raw/stuck.wav"]
    assert not (tmp_path / REL).exists()
