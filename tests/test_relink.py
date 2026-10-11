import shutil
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.relink import relink_mismatches, to_footage_relpath
from backend.project.schema import Source
from backend.project.session import Session, SessionError
from backend.project.store import load_project

NO_FRONTEND = Path("does-not-exist")
PROJECT = PureWindowsPath("D:/Projects/My Rack")


# ---- pure helpers ----------------------------------------------------------


def test_relpath_inside_footage() -> None:
    picked = PureWindowsPath("D:/Projects/My Rack/footage/sub/a.mkv")
    assert to_footage_relpath(PROJECT, picked) == "footage/sub/a.mkv"


def test_relpath_footage_folder_is_case_insensitive() -> None:
    picked = PureWindowsPath("d:/projects/my rack/Footage/a.mkv")
    assert to_footage_relpath(PROJECT, picked) == "Footage/a.mkv"


@pytest.mark.parametrize(
    "picked",
    [
        "D:/Elsewhere/a.mkv",
        "D:/Projects/My Rack/a.mkv",
        "D:/Projects/My Rack/media/a.mkv",
        "D:/Projects/My Rack/footage",
    ],
)
def test_relpath_rejects_outside_footage(picked: str) -> None:
    with pytest.raises(ValueError, match="footage folder"):
        to_footage_relpath(PROJECT, PureWindowsPath(picked))


def _source(**overrides: Any) -> Source:
    data: dict[str, Any] = {
        "id": "aaaaaaaaaaaa",
        "path": "footage/a.mkv",
        "duration_ms": 12500,
        "fps_num": 60,
        "fps_den": 1,
        "width": 2560,
        "height": 1440,
        "audio_tracks": 1,
    }
    data.update(overrides)
    return Source(**data)


def test_mismatches_empty_when_same() -> None:
    assert relink_mismatches(_source(), _source(path="footage/b.mkv")) == []


def test_mismatches_allows_small_duration_difference() -> None:
    assert relink_mismatches(_source(), _source(duration_ms=12550)) == []


def test_mismatches_reports_each_difference() -> None:
    problems = relink_mismatches(
        _source(),
        _source(width=1920, height=1080, fps_num=30, duration_ms=20000, audio_tracks=2),
    )
    assert len(problems) == 4
    joined = " ".join(problems)
    assert "resolution" in joined
    assert "frame rate" in joined
    assert "length" in joined
    assert "audio" in joined


def test_mismatches_ntsc_rate_compared_exactly() -> None:
    ntsc = _source(fps_num=60000, fps_den=1001)
    assert relink_mismatches(ntsc, _source(fps_num=60000, fps_den=1001)) == []
    assert any("frame rate" in p for p in relink_mismatches(ntsc, _source()))


# ---- session and API -------------------------------------------------------


def _probe_json(width: int = 2560, height: int = 1440) -> dict[str, Any]:
    return {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": width,
                "height": height,
                "avg_frame_rate": "60/1",
                "r_frame_rate": "60/1",
            },
            {"codec_type": "audio", "codec_name": "aac", "channels": 2},
        ],
        "format": {"duration": "12.5"},
    }


def _fake_probe(path: Path) -> dict[str, Any]:
    if path.name == "other.mkv":
        return _probe_json(width=1920, height=1080)
    return _probe_json()


def _setup(tmp_path: Path) -> tuple[Session, Path, str]:
    """A project with one scanned source at footage/a.mkv. Returns the id."""
    projects = tmp_path / "projects"
    projects.mkdir()
    session = Session(probe=_fake_probe)
    folder = Path(session.new_project(str(projects), "My Rack").folder)
    (folder / "footage").mkdir(exist_ok=True)
    (folder / "footage" / "a.mkv").write_bytes(b"x")
    report = session.rescan_footage()
    return session, folder, report.items[0].id


def test_relink_after_move(tmp_path: Path) -> None:
    session, folder, source_id = _setup(tmp_path)
    moved = folder / "footage" / "moved" / "a.mkv"
    moved.parent.mkdir()
    shutil.move(folder / "footage" / "a.mkv", moved)
    assert session.footage().items[0].exists is False

    report = session.relink_source(source_id, str(moved))
    (item,) = report.items
    assert item.id == source_id
    assert item.path == "footage/moved/a.mkv"
    assert item.exists is True
    assert load_project(folder).sources[0].path == "footage/moved/a.mkv"


def test_relink_to_same_path_is_a_no_op(tmp_path: Path) -> None:
    session, folder, source_id = _setup(tmp_path)
    report = session.relink_source(source_id, str(folder / "footage" / "a.mkv"))
    assert report.items[0].path == "footage/a.mkv"


def test_relink_outside_footage_is_refused(tmp_path: Path) -> None:
    session, _folder, source_id = _setup(tmp_path)
    elsewhere = tmp_path / "elsewhere" / "a.mkv"
    elsewhere.parent.mkdir()
    elsewhere.write_bytes(b"x")
    with pytest.raises(SessionError, match="footage folder"):
        session.relink_source(source_id, str(elsewhere))
    assert session.footage().items[0].path == "footage/a.mkv"


def test_relink_mismatching_file_is_refused(tmp_path: Path) -> None:
    session, folder, source_id = _setup(tmp_path)
    (folder / "footage" / "a.mkv").unlink()
    other = folder / "footage" / "sub" / "other.mkv"
    other.parent.mkdir()
    other.write_bytes(b"x")
    with pytest.raises(SessionError, match="resolution"):
        session.relink_source(source_id, str(other))
    assert session.footage().items[0].path == "footage/a.mkv"


def test_relink_unknown_source_and_missing_file(tmp_path: Path) -> None:
    session, folder, source_id = _setup(tmp_path)
    with pytest.raises(SessionError, match="unknown footage source"):
        session.relink_source("0" * 12, str(folder / "footage" / "a.mkv"))
    with pytest.raises(SessionError, match="file not found"):
        session.relink_source(source_id, str(folder / "footage" / "nope.mkv"))


def test_relink_requires_open_project() -> None:
    with pytest.raises(SessionError, match="no project is open"):
        Session(probe=_fake_probe).relink_source("0" * 12, "x")


def test_relink_endpoint(tmp_path: Path) -> None:
    session, folder, source_id = _setup(tmp_path)
    client = TestClient(create_app(static_dir=NO_FRONTEND, session=session))
    moved = folder / "footage" / "moved" / "a.mkv"
    moved.parent.mkdir()
    shutil.move(folder / "footage" / "a.mkv", moved)

    bad = client.post(
        "/api/footage/relink", json={"source_id": "0" * 12, "path": str(moved)}
    )
    assert bad.status_code == 400

    ok = client.post(
        "/api/footage/relink", json={"source_id": source_id, "path": str(moved)}
    )
    assert ok.status_code == 200
    assert ok.json()["items"][0]["path"] == "footage/moved/a.mkv"
    assert ok.json()["items"][0]["exists"] is True
