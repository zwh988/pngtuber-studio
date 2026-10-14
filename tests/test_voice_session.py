"""Voice profile through Session and the API (M3-1). Audio decoding is faked;
the file copy, hashing, commands, saving and endpoints are real."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.session import Session, SessionError
from backend.voice.profile import AudioInfo
from backend.voice.reference import AudioInfoFn, VoiceProfileError


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def good_info(path: Path) -> AudioInfo:
    return AudioInfo(duration_ms=8000, sample_rate=24000, channels=1)


def make_session(audio_info: AudioInfoFn = good_info) -> Session:
    return Session(probe=fake_probe, audio_info=audio_info)


def open_project(tmp_path: Path, session: Session) -> Path:
    session.new_project(str(tmp_path), "Rack")
    return tmp_path / "Rack"


def make_clip(tmp_path: Path, name: str = "ref.wav", data: bytes = b"abc" * 50) -> Path:
    clip = tmp_path / name
    clip.write_bytes(data)
    return clip


def test_voice_without_a_project_is_an_error() -> None:
    with pytest.raises(SessionError, match="no project is open"):
        make_session().voice()


def test_new_project_has_no_usable_voice_yet(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    state = session.voice()
    assert not state.ready
    assert state.status in ("no_profile", "no_reference")


def test_set_reference_copies_checks_and_hashes(tmp_path: Path) -> None:
    session = make_session()
    folder = open_project(tmp_path, session)
    state = session.set_voice_reference(str(make_clip(tmp_path)))
    assert state.status == "ready"
    assert state.ready
    assert state.reference_path is not None
    assert state.reference_path.startswith("media/voice/ref-")
    assert (folder / state.reference_path).is_file()
    assert state.hash is not None
    assert len(state.hash) == 64
    assert state.duration_ms == 8000


def test_set_reference_is_one_undo_step_and_is_saved(tmp_path: Path) -> None:
    session = make_session()
    folder = open_project(tmp_path, session)
    session.set_voice_reference(str(make_clip(tmp_path)))
    assert session.timeline().undo_label == "Set voice reference"

    reopened = make_session()
    reopened.open_project(str(folder))
    assert reopened.voice().ready

    session.undo()
    assert not session.voice().ready


def test_setting_the_same_clip_again_adds_no_undo_step(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    clip = make_clip(tmp_path)
    session.set_voice_reference(str(clip))
    session.set_voice_reference(str(clip))
    session.undo()
    assert not session.timeline().can_undo


def test_a_second_clip_replaces_the_first(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    first = session.set_voice_reference(str(make_clip(tmp_path, "a.wav", b"a" * 50)))
    second = session.set_voice_reference(str(make_clip(tmp_path, "b.wav", b"b" * 60)))
    assert first.reference_path != second.reference_path
    assert first.hash != second.hash
    session.undo()
    assert session.voice().reference_path == first.reference_path


def test_missing_file_is_refused(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    with pytest.raises(SessionError, match="file not found"):
        session.set_voice_reference(str(tmp_path / "nope.wav"))
    with pytest.raises(SessionError, match="file not found"):
        session.set_voice_reference("   ")


def test_undecodable_clip_is_refused_and_changes_nothing(tmp_path: Path) -> None:
    def broken(path: Path) -> AudioInfo:
        raise VoiceProfileError("cannot decode ref.wav: bad header")

    session = make_session(audio_info=broken)
    folder = open_project(tmp_path, session)
    with pytest.raises(SessionError, match="cannot decode"):
        session.set_voice_reference(str(make_clip(tmp_path)))
    assert not session.voice().ready
    assert not (folder / "media" / "voice").exists() or not list(
        (folder / "media" / "voice").iterdir()
    )


def test_too_short_clip_is_refused(tmp_path: Path) -> None:
    def short(path: Path) -> AudioInfo:
        return AudioInfo(duration_ms=300, sample_rate=24000, channels=1)

    session = make_session(audio_info=short)
    open_project(tmp_path, session)
    with pytest.raises(SessionError, match="at least"):
        session.set_voice_reference(str(make_clip(tmp_path)))


def test_deleted_reference_file_shows_as_missing(tmp_path: Path) -> None:
    session = make_session()
    folder = open_project(tmp_path, session)
    state = session.set_voice_reference(str(make_clip(tmp_path)))
    assert state.reference_path is not None
    (folder / state.reference_path).unlink()
    after = session.voice()
    assert after.status == "file_missing"
    assert not after.ready


def test_unreadable_reference_shows_the_error(tmp_path: Path) -> None:
    calls = {"n": 0}

    def flaky(path: Path) -> AudioInfo:
        calls["n"] += 1
        if calls["n"] > 1:
            raise VoiceProfileError("cannot decode: gone bad")
        return good_info(path)

    session = make_session(audio_info=flaky)
    open_project(tmp_path, session)
    session.set_voice_reference(str(make_clip(tmp_path)))
    state = session.voice()
    assert state.status == "unreadable"
    assert state.problems == ["cannot decode: gone bad"]


def test_new_project_creates_the_voice_folder(tmp_path: Path) -> None:
    session = make_session()
    folder = open_project(tmp_path, session)
    assert (folder / "media" / "voice").is_dir()


# ---- API --------------------------------------------------------------------


def make_client(tmp_path: Path) -> tuple[TestClient, Session]:
    session = make_session()
    app = create_app(static_dir=tmp_path / "no-frontend", session=session)
    return TestClient(app), session


def test_api_voice_without_a_project_is_400(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    response = client.get("/api/voice")
    assert response.status_code == 400
    assert "no project is open" in response.json()["detail"]


def test_api_set_reference_then_get(tmp_path: Path) -> None:
    client, session = make_client(tmp_path)
    open_project(tmp_path, session)
    clip = make_clip(tmp_path)
    response = client.post("/api/voice/reference", json={"path": str(clip)})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["ready"] is True
    assert body["reference_path"].startswith("media/voice/")
    assert client.get("/api/voice").json() == body


def test_api_bad_path_is_400(tmp_path: Path) -> None:
    client, session = make_client(tmp_path)
    open_project(tmp_path, session)
    response = client.post(
        "/api/voice/reference", json={"path": str(tmp_path / "nope.wav")}
    )
    assert response.status_code == 400
    assert "file not found" in response.json()["detail"]
