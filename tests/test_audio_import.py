"""Importing dropped music and sound effects (M8-1): pure helpers, file I/O,
the session method and the API routes. ffprobe and ffmpeg are faked."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.audio.clipimport import (
    DECODED_RATE,
    AudioImportError,
    copy_name,
    decode_args,
    decoded_path,
    find_reuse,
    import_audio_file,
    is_audio_file,
    parse_audio_probe,
)
from backend.dropfiles import PAGE_CALLBACK, dropped_files, page_call
from backend.project.schema import AudioFile
from backend.project.session import Session, SessionError

# ---- fakes ---------------------------------------------------------------------------


def write_wav(
    path: Path, seconds: float, rate: int = 44_100, channels: int = 2
) -> Path:
    frames = int(seconds * rate)
    data = np.zeros((frames, channels), dtype=np.float32)
    data[:, 0] = 0.25 * np.sin(np.arange(frames) * 0.05)
    sf.write(str(path), data, rate)
    return path


def fake_probe(path: Path) -> dict[str, Any]:
    info = sf.info(str(path))
    return {
        "streams": [
            {
                "codec_type": "audio",
                "sample_rate": str(info.samplerate),
                "channels": info.channels,
                "duration": str(info.frames / info.samplerate),
            }
        ],
        "format": {"duration": str(info.frames / info.samplerate)},
    }


def fake_decode(source: Path, dest: Path, channels: int) -> None:
    info = sf.info(str(source))
    frames = round(info.frames * DECODED_RATE / info.samplerate)
    sf.write(
        str(dest), np.zeros((frames, channels), dtype=np.int16), DECODED_RATE, "PCM_16"
    )


def failing_probe(path: Path) -> dict[str, Any]:
    return {"streams": [{"codec_type": "video"}]}


# ---- pure ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "ok"),
    [
        ("a.wav", True),
        ("B.MP3", True),
        ("c.flac", True),
        ("d.ogg", True),
        ("e.m4a", True),
        ("f.mkv", False),
        ("g", False),
        ("h.wav.txt", False),
    ],
)
def test_is_audio_file(name: str, ok: bool) -> None:
    assert is_audio_file(name) is ok


def test_parse_audio_probe() -> None:
    data = {
        "streams": [
            {"codec_type": "video"},
            {"codec_type": "audio", "sample_rate": "44100", "channels": 2},
        ],
        "format": {"duration": "12.3456"},
    }
    probe = parse_audio_probe(data, "x.mp3")
    assert (probe.duration_ms, probe.sample_rate, probe.channels) == (12_346, 44_100, 2)


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"streams": [{"codec_type": "video"}]},
        {"streams": [{"codec_type": "audio", "sample_rate": "x", "channels": 2}]},
        {"streams": [{"codec_type": "audio", "sample_rate": "48000", "channels": 2}]},
    ],
)
def test_parse_audio_probe_refusals(data: dict[str, Any]) -> None:
    with pytest.raises(AudioImportError):
        parse_audio_probe(data, "x.mp3")


def test_copy_name_avoids_clashes_case_insensitively() -> None:
    assert copy_name("song.mp3", []) == "song.mp3"
    assert copy_name("song.mp3", ["SONG.mp3"]) == "song (2).mp3"
    assert copy_name("song.mp3", ["song.mp3", "song (2).mp3"]) == "song (3).mp3"


def make_file(file_id: str, name: str, size: int) -> AudioFile:
    return AudioFile(
        id=file_id,
        path=f"audio/{name}",
        name=name,
        size_bytes=size,
        duration_ms=1000,
        sample_rate=48_000,
        channels=2,
    )


def test_find_reuse_matches_name_and_size() -> None:
    known = [make_file("a" * 12, "pop.wav", 100)]
    assert find_reuse(known, "POP.wav", 100) is known[0]
    assert find_reuse(known, "pop.wav", 101) is None
    assert find_reuse(known, "other.wav", 100) is None


def test_decode_args_are_a_list_with_the_paths_as_given() -> None:
    args = decode_args(
        Path("C:/a b/ffmpeg.exe"), Path("D:/my music/x.mp3"), Path("o.wav"), 1
    )
    assert args[0].endswith("ffmpeg.exe") and "D:/my music/x.mp3" in args[
        args.index("-i") + 1
    ].replace("\\", "/")
    assert args[args.index("-ac") + 1] == "1"
    assert args[args.index("-ar") + 1] == "48000"
    assert (
        decode_args(Path("f"), Path("s"), Path("d"), 6)[
            decode_args(Path("f"), Path("s"), Path("d"), 6).index("-ac") + 1
        ]
        == "2"
    )


# ---- drop messages -------------------------------------------------------------------


def test_dropped_files_gives_paths_and_point() -> None:
    event = {
        "clientX": 10.5,
        "clientY": 20,
        "dataTransfer": {
            "files": [
                {"name": "a b.wav", "pywebviewFullPath": "D:\\my music\\a b.wav"},
                {"name": "x.wav"},  # no path: left out
            ]
        },
    }
    assert dropped_files(event) == {
        "x": 10.5,
        "y": 20,
        "paths": ["D:\\my music\\a b.wav"],
    }


@pytest.mark.parametrize(
    "event",
    [
        {
            "clientX": 1,
            "clientY": 1,
            "dataTransfer": {"files": []},
        },  # a line from the bank
        {"clientX": 1, "clientY": 1},
        {"dataTransfer": {"files": [{"pywebviewFullPath": "C:\\a.wav"}]}},
    ],
)
def test_dropped_files_ignores_other_drops(event: dict[str, Any]) -> None:
    assert dropped_files(event) is None


def test_page_call_quotes_the_message() -> None:
    js = page_call({"x": 1, "y": 2, "paths": ['C:\\a "b".wav']})
    assert js.startswith(f"window.{PAGE_CALLBACK} && window.{PAGE_CALLBACK}(")
    assert '"C:\\\\a \\"b\\".wav"' in js


# ---- file I/O ------------------------------------------------------------------------


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    folder = tmp_path / "my music"
    folder.mkdir()
    return folder


def test_import_copies_probes_and_decodes(tmp_path: Path, outside: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = write_wav(outside / "Song One.wav", 1.5)
    before = source.read_bytes()
    audio_file, reused = import_audio_file(
        project, source, [], probe=fake_probe, decode=fake_decode
    )
    assert not reused
    assert audio_file.path == "audio/Song One.wav"
    assert (project / audio_file.path).read_bytes() == before
    assert source.read_bytes() == before  # original untouched
    assert (audio_file.duration_ms, audio_file.sample_rate, audio_file.channels) == (
        1500,
        44_100,
        2,
    )
    assert audio_file.size_bytes == len(before)
    decoded = decoded_path(project, audio_file.id)
    assert sf.info(str(decoded)).samplerate == DECODED_RATE


def test_import_reuses_a_known_file_without_copying(
    tmp_path: Path, outside: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = write_wav(outside / "pop.wav", 0.5)
    first, _ = import_audio_file(
        project, source, [], probe=fake_probe, decode=fake_decode
    )
    decoded_path(project, first.id).unlink()  # the cache can go; it is made again
    again, reused = import_audio_file(
        project, source, [first], probe=fake_probe, decode=fake_decode
    )
    assert reused and again is first
    assert decoded_path(project, first.id).is_file()
    assert sorted(p.name for p in (project / "audio").iterdir()) == ["pop.wav"]


def test_import_uses_the_copy_left_by_an_undone_import(
    tmp_path: Path, outside: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = write_wav(outside / "pop.wav", 0.5)
    first, _ = import_audio_file(
        project, source, [], probe=fake_probe, decode=fake_decode
    )
    # Undo removed the entry; the copy is still in audio/.
    again, reused = import_audio_file(
        project, source, [], probe=fake_probe, decode=fake_decode
    )
    assert not reused and again.path == first.path
    assert sorted(p.name for p in (project / "audio").iterdir()) == ["pop.wav"]


def test_a_different_file_with_the_same_name_gets_a_new_name(
    tmp_path: Path, outside: Path
) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    first, _ = import_audio_file(
        project,
        write_wav(outside / "pop.wav", 0.5),
        [],
        probe=fake_probe,
        decode=fake_decode,
    )
    other_folder = outside / "other"
    other_folder.mkdir()
    second, reused = import_audio_file(
        project,
        write_wav(other_folder / "pop.wav", 0.8),
        [first],
        probe=fake_probe,
        decode=fake_decode,
    )
    assert not reused and second.path == "audio/pop (2).wav"


def test_an_unusable_file_leaves_nothing_behind(tmp_path: Path, outside: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    source = write_wav(outside / "silent.wav", 0.5)
    with pytest.raises(AudioImportError, match="no sound"):
        import_audio_file(project, source, [], probe=failing_probe, decode=fake_decode)
    assert list((project / "audio").iterdir()) == []
    with pytest.raises(AudioImportError, match="not a supported"):
        import_audio_file(
            project, outside / "x.mkv", [], probe=fake_probe, decode=fake_decode
        )


# ---- session -------------------------------------------------------------------------


@pytest.fixture
def session(tmp_path: Path) -> Session:
    session = Session(probe=fake_probe, decode=fake_decode)
    session.new_project(str(tmp_path), "Rack")
    return session


def test_session_import_places_files_one_after_another(
    session: Session, outside: Path
) -> None:
    a = write_wav(outside / "a.wav", 1.0)
    b = write_wav(outside / "b.wav", 2.0)
    result = session.import_audio([str(a), str(b)], None, 500)
    assert result.errors == []
    assert [(i.name, i.timeline_ms, i.lane_name) for i in result.imported] == [
        ("a.wav", 500, "Audio 1"),
        ("b.wav", 1500, "Audio 1"),
    ]
    clips = result.timeline.audio_clips
    assert [(c.name, c.timeline_ms, c.end_ms) for c in clips] == [
        ("a.wav", 500, 1500),
        ("b.wav", 1500, 3500),
    ]
    assert result.timeline.undo_label == "Import 2 audio files"
    undone = session.undo()
    assert undone.timeline.audio_clips == []


def test_session_import_goes_to_a_free_or_new_lane(
    session: Session, outside: Path
) -> None:
    a = write_wav(outside / "a.wav", 1.0)
    session.import_audio([str(a)], None, 0)
    second = session.import_audio([str(a)], None, 500)  # overlaps on Audio 1
    assert second.imported[0].reused
    assert second.imported[0].lane_name == "Audio 2"
    assert [lane.name for lane in second.timeline.audio_lanes] == ["Audio 1", "Audio 2"]
    session.undo()
    assert len(session.timeline().audio_lanes) == 1  # the new lane goes with the undo


def test_session_import_onto_a_new_lane(session: Session, outside: Path) -> None:
    a = write_wav(outside / "a.wav", 1.0)
    result = session.import_audio([str(a)], None, 0, new_lane=True)
    assert [lane.name for lane in result.timeline.audio_lanes] == ["Audio 1", "Audio 2"]
    assert result.imported[0].lane_name == "Audio 2"
    session.undo()
    assert len(session.timeline().audio_lanes) == 1


def test_session_import_reports_bad_files_and_places_the_rest(
    session: Session, outside: Path
) -> None:
    good = write_wav(outside / "good.wav", 1.0)
    result = session.import_audio(
        [str(outside / "gone.wav"), str(outside / "x.txt"), str(good)], None, 0
    )
    assert [i.name for i in result.imported] == ["good.wav"]
    assert len(result.errors) == 2 and "gone.wav: file not found" in result.errors[0]


def test_session_import_needs_a_project_and_a_known_lane(
    tmp_path: Path, outside: Path
) -> None:
    a = write_wav(outside / "a.wav", 1.0)
    with pytest.raises(SessionError):
        Session(probe=fake_probe, decode=fake_decode).import_audio([str(a)], None, 0)
    session = Session(probe=fake_probe, decode=fake_decode)
    session.new_project(str(tmp_path), "R2")
    with pytest.raises(SessionError, match="unknown audio lane"):
        session.import_audio([str(a)], "f" * 12, 0)


# ---- API -----------------------------------------------------------------------------


def test_api_import_media_and_peaks(session: Session, outside: Path) -> None:
    client = TestClient(create_app(static_dir=Path("does-not-exist"), session=session))
    a = write_wav(outside / "a b.wav", 1.0)
    response = client.post(
        "/api/audio/import", json={"paths": [str(a)], "timeline_ms": 0}
    )
    assert response.status_code == 200, response.text
    file_id = response.json()["timeline"]["audio_clips"][0]["file_id"]
    media = client.get(f"/media/audio/{file_id}")
    assert media.status_code == 200 and media.content[:4] == b"RIFF"
    peaks = client.get(f"/api/audio/{file_id}/peaks?buckets=16")
    assert peaks.status_code == 200 and peaks.json()["buckets"] == 16
    assert client.get("/media/audio/ffffffffffff").status_code == 404
    bad = client.post("/api/audio/import", json={"paths": [], "timeline_ms": 0})
    assert bad.status_code == 422
