"""Reference clip I/O (M3-1): decode, hash cache, import into the project."""

import os
import wave
from pathlib import Path

import pytest

from backend.voice.profile import AudioInfo
from backend.voice.reference import (
    FileHashCache,
    VoiceProfileError,
    hash_file,
    import_reference,
    read_audio_info,
)


def write_wav(path: Path, seconds: float, rate: int = 24000) -> None:
    frames = round(seconds * rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)


def fake_info(path: Path) -> AudioInfo:
    return AudioInfo(duration_ms=8000, sample_rate=24000, channels=1)


def test_read_audio_info_reads_a_wav(tmp_path: Path) -> None:
    clip = tmp_path / "ref.wav"
    write_wav(clip, 2.0)
    info = read_audio_info(clip)
    assert info.duration_ms == 2000
    assert info.sample_rate == 24000
    assert info.channels == 1


def test_read_audio_info_rejects_a_file_that_is_not_audio(tmp_path: Path) -> None:
    clip = tmp_path / "notes.wav"
    clip.write_text("this is not audio", encoding="utf-8")
    with pytest.raises(VoiceProfileError, match="cannot decode"):
        read_audio_info(clip)


def test_hash_file_is_stable_and_content_based(tmp_path: Path) -> None:
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"hello")
    b.write_bytes(b"hello")
    assert hash_file(a) == hash_file(b)
    assert len(hash_file(a)) == 64
    b.write_bytes(b"hellp")
    assert hash_file(a) != hash_file(b)


def test_hash_cache_reuses_until_the_file_changes(tmp_path: Path) -> None:
    clip = tmp_path / "a.bin"
    clip.write_bytes(b"one")
    cache = FileHashCache()
    first = cache.digest(clip)
    assert cache.digest(clip) == first
    clip.write_bytes(b"three")  # different size, so the entry is stale
    assert cache.digest(clip) != first
    assert cache.digest(clip) == hash_file(clip)


def test_hash_cache_does_not_rehash_an_unchanged_file(tmp_path: Path) -> None:
    clip = tmp_path / "a.bin"
    clip.write_bytes(b"abc")
    cache = FileHashCache()
    first = cache.digest(clip)
    # Same size and mtime but different bytes: the cache cannot see it. This
    # pins down that the key is (size, mtime), not the content.
    stat = clip.stat()
    clip.write_bytes(b"xyz")
    os.utime(clip, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert cache.digest(clip) == first


def test_import_copies_into_media_voice(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = tmp_path / "My Voice.wav"
    write_wav(source, 6.0)
    imported = import_reference(project, source)
    assert imported.rel_path.startswith("media/voice/My Voice-")
    assert imported.rel_path.endswith(".wav")
    assert (project / imported.rel_path).read_bytes() == source.read_bytes()
    assert source.is_file()  # the source is untouched
    assert imported.digest == hash_file(source)
    assert imported.warnings == ()


def test_import_same_file_twice_reuses_the_copy(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = tmp_path / "ref.wav"
    write_wav(source, 6.0)
    first = import_reference(project, source)
    second = import_reference(project, source)
    assert first.rel_path == second.rel_path
    assert len(list((project / "media" / "voice").iterdir())) == 1


def test_import_different_files_with_the_same_name_do_not_collide(
    tmp_path: Path,
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    write_wav(one / "ref.wav", 6.0)
    write_wav(two / "ref.wav", 7.0)
    a = import_reference(project, one / "ref.wav")
    b = import_reference(project, two / "ref.wav")
    assert a.rel_path != b.rel_path
    assert len(list((project / "media" / "voice").iterdir())) == 2


def test_import_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = tmp_path / "ref.wav"
    write_wav(source, 6.0)
    import_reference(project, source)
    names = [p.name for p in (project / "media" / "voice").iterdir()]
    assert not any(name.endswith(".tmp") for name in names)


def test_import_returns_warnings_for_a_short_clip(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = tmp_path / "ref.wav"
    write_wav(source, 2.0)
    imported = import_reference(project, source)
    assert len(imported.warnings) == 1


def test_import_refuses_a_clip_that_is_too_short(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = tmp_path / "ref.wav"
    write_wav(source, 0.5)
    with pytest.raises(VoiceProfileError, match="at least"):
        import_reference(project, source)
    assert not (project / "media" / "voice").exists()


def test_import_refuses_an_undecodable_file(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = tmp_path / "ref.wav"
    source.write_text("nope", encoding="utf-8")
    with pytest.raises(VoiceProfileError, match="cannot decode"):
        import_reference(project, source)


def test_import_refuses_an_unsupported_extension(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = tmp_path / "ref.aac"
    source.write_bytes(b"abc")
    with pytest.raises(VoiceProfileError, match="unsupported audio type"):
        import_reference(project, source, audio_info=fake_info)


def test_import_uses_the_given_hash_cache(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = tmp_path / "ref.wav"
    source.write_bytes(b"abc" * 10)
    cache = FileHashCache()
    imported = import_reference(project, source, audio_info=fake_info, hashes=cache)
    assert cache.digest(source) == imported.digest
