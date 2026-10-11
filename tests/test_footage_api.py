from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.footage import FfprobeNotFoundError, ProbeError
from backend.project.schema import Source
from backend.project.session import Session, SessionError
from backend.project.store import load_project
from backend.project.summary import describe_source

NO_FRONTEND = Path("does-not-exist")


def _probe_json(duration_s: str = "12.5") -> dict[str, Any]:
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 2560,
                "height": 1440,
                "avg_frame_rate": "60/1",
                "r_frame_rate": "60/1",
            },
            {"codec_type": "audio", "codec_name": "aac", "channels": 2},
        ],
        "format": {"duration": duration_s},
    }


def _fake_probe(path: Path) -> dict[str, Any]:
    if path.name == "bad.mkv":
        raise ProbeError("boom")
    return _probe_json()


def _no_ffprobe(path: Path) -> dict[str, Any]:
    raise FfprobeNotFoundError("ffprobe missing")


def _new(tmp_path: Path) -> tuple[Session, Path]:
    projects = tmp_path / "projects"
    projects.mkdir()
    session = Session(probe=_fake_probe)
    summary = session.new_project(str(projects), "My Rack")
    return session, Path(summary.folder)


def _drop(folder: Path, name: str = "a.mkv") -> Path:
    path = folder / "footage" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_describe_source_is_pure() -> None:
    source = Source(
        id="aaaaaaaaaaaa",
        path="footage/a.mkv",
        duration_ms=1000,
        fps_num=60000,
        fps_den=1001,
        width=1920,
        height=1080,
        audio_tracks=1,
    )
    item = describe_source(source, exists=False)
    assert item.exists is False
    assert item.fps == pytest.approx(59.94, abs=0.001)
    assert item.path == "footage/a.mkv"
    assert item.external is False


def test_rescan_adds_new_footage(tmp_path: Path) -> None:
    session, folder = _new(tmp_path)
    _drop(folder)
    report = session.rescan_footage()
    assert report.added == 1
    assert report.errors == []
    (item,) = report.items
    assert item.path == "footage/a.mkv"
    assert item.exists is True
    assert (item.width, item.height) == (2560, 1440)
    assert item.fps == 60.0
    assert item.duration_ms == 12500
    assert item.audio_tracks == 1


def test_rescan_twice_adds_nothing_new(tmp_path: Path) -> None:
    session, folder = _new(tmp_path)
    _drop(folder)
    session.rescan_footage()
    assert session.rescan_footage().added == 0
    assert len(session.footage().items) == 1


def test_rescan_saves_project_to_disk(tmp_path: Path) -> None:
    session, folder = _new(tmp_path)
    _drop(folder)
    session.rescan_footage()
    assert [s.path for s in load_project(folder).sources] == ["footage/a.mkv"]


def test_open_scans_footage_and_saves(tmp_path: Path) -> None:
    _, folder = _new(tmp_path)
    _drop(folder)
    other = Session(probe=_fake_probe)
    summary = other.open_project(str(folder))
    assert summary.source_count == 1
    assert len(load_project(folder).sources) == 1


def test_missing_file_is_flagged_not_removed(tmp_path: Path) -> None:
    session, folder = _new(tmp_path)
    path = _drop(folder)
    session.rescan_footage()
    path.unlink()
    (item,) = session.footage().items
    assert item.exists is False
    assert len(load_project(folder).sources) == 1


def test_bad_file_is_reported_and_others_added(tmp_path: Path) -> None:
    session, folder = _new(tmp_path)
    _drop(folder, "a.mkv")
    _drop(folder, "bad.mkv")
    report = session.rescan_footage()
    assert report.added == 1
    assert len(report.items) == 1
    assert len(report.errors) == 1
    assert "bad.mkv" in report.errors[0]


def test_open_survives_missing_ffprobe(tmp_path: Path) -> None:
    _, folder = _new(tmp_path)
    _drop(folder)
    other = Session(probe=_no_ffprobe)
    summary = other.open_project(str(folder))
    assert summary.source_count == 0
    assert other.footage().errors


def test_footage_requires_open_project() -> None:
    session = Session(probe=_fake_probe)
    with pytest.raises(SessionError, match="no project is open"):
        session.footage()
    with pytest.raises(SessionError, match="no project is open"):
        session.rescan_footage()


def test_save_failure_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    session, folder = _new(tmp_path)
    _drop(folder)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("backend.project.session.save_project", boom)
    session.rescan_footage()
    current = session.current()
    assert current is not None
    assert current.save_error == "disk full"
    assert current.source_count == 1


def test_footage_endpoints(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    client = TestClient(
        create_app(static_dir=NO_FRONTEND, session=Session(probe=_fake_probe))
    )
    assert client.get("/api/footage").status_code == 400
    assert client.post("/api/footage/rescan").status_code == 400

    created = client.post(
        "/api/project/new", json={"name": "Rack", "parent": str(projects)}
    ).json()
    assert created["save_error"] is None
    _drop(Path(created["folder"]))

    body = client.post("/api/footage/rescan").json()
    assert body["added"] == 1
    listed = client.get("/api/footage").json()
    assert [i["path"] for i in listed["items"]] == ["footage/a.mkv"]
    assert listed["items"][0]["exists"] is True
