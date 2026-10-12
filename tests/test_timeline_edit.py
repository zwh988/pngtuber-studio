import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.commands import AddSource
from backend.project.schema import Clip, Source
from backend.project.session import Session, SessionError


def hid(name: str) -> str:
    """Readable test name to a valid 12-char hex id (the schema requires one)."""
    return hashlib.sha1(name.encode()).hexdigest()[:12]


def make_source(name: str, duration_ms: int = 10_000) -> Source:
    return Source(
        id=hid(name),
        path=f"footage/{name}.mkv",
        duration_ms=duration_ms,
        fps_num=60,
        fps_den=1,
        width=2560,
        height=1440,
        audio_tracks=1,
    )


def _no_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("no footage files, so nothing should be probed")


def open_session(tmp_path: Path, *sources: Source) -> Session:
    """A session with an open project that already holds the given sources.

    The sources are added directly (their files need not exist), and the undo
    history is cleared so tests start from an empty stack.
    """
    session = Session(probe=_no_probe)
    session.new_project(str(tmp_path), "Rack")
    stack = session._stack
    assert stack is not None
    for source in sources:
        stack.execute(AddSource(source))
    stack.clear()
    return session


def test_add_clip_puts_whole_source_on_timeline(tmp_path: Path) -> None:
    session = open_session(tmp_path, make_source("s1"))
    state = session.add_clip(hid("s1"))
    assert len(state.clips) == 1
    assert state.clips[0].source_id == hid("s1")
    assert (state.clips[0].in_ms, state.clips[0].out_ms) == (0, 10_000)
    assert state.duration_ms == 10_000
    assert state.can_undo is True
    assert state.undo_label is not None
    summary = session.current()
    assert summary is not None
    assert summary.clip_count == 1


def test_add_clip_unknown_source_is_refused(tmp_path: Path) -> None:
    session = open_session(tmp_path)
    with pytest.raises(SessionError):
        session.add_clip(hid("nope"))
    assert session.timeline().clips == []
    assert session.timeline().can_undo is False


def test_add_clip_requires_open_project() -> None:
    with pytest.raises(SessionError):
        Session(probe=_no_probe).add_clip(hid("s1"))


def test_second_clip_appends_and_explicit_position_inserts(tmp_path: Path) -> None:
    session = open_session(
        tmp_path, make_source("s1", 10_000), make_source("s2", 6_000)
    )
    session.add_clip(hid("s1"))
    state = session.add_clip(hid("s2"))
    assert [c.source_id for c in state.clips] == [hid("s1"), hid("s2")]
    assert state.duration_ms == 16_000
    state = session.add_clip(hid("s2"), position=0)
    assert [c.source_id for c in state.clips] == [hid("s2"), hid("s1"), hid("s2")]
    assert [c.position for c in state.clips] == [0, 1, 2]
    assert state.duration_ms == 22_000


def test_bad_position_is_refused(tmp_path: Path) -> None:
    session = open_session(tmp_path, make_source("s1"))
    with pytest.raises(SessionError):
        session.add_clip(hid("s1"), position=5)
    assert session.timeline().clips == []


def test_undo_and_redo(tmp_path: Path) -> None:
    session = open_session(tmp_path, make_source("s1"))
    session.add_clip(hid("s1"))

    undone = session.undo()
    assert undone.label is not None
    assert undone.timeline.clips == []
    assert undone.timeline.can_undo is False
    assert undone.timeline.can_redo is True
    assert undone.timeline.redo_label == undone.label

    redone = session.redo()
    assert redone.label == undone.label
    assert len(redone.timeline.clips) == 1
    assert redone.timeline.can_redo is False


def test_undo_with_nothing_to_undo_is_not_an_error(tmp_path: Path) -> None:
    session = open_session(tmp_path)
    assert session.undo().label is None
    assert session.redo().label is None


def test_undo_requires_open_project() -> None:
    with pytest.raises(SessionError):
        Session(probe=_no_probe).undo()


def test_edit_is_saved_and_survives_reopen(tmp_path: Path) -> None:
    session = open_session(tmp_path, make_source("s1"))
    session.add_clip(hid("s1"))

    reopened = Session(probe=_no_probe)
    reopened.open_project(str(tmp_path / "Rack"))
    state = reopened.timeline()
    assert len(state.clips) == 1
    assert state.duration_ms == 10_000
    # History starts empty after opening: nothing from before is undoable.
    assert state.can_undo is False


def test_problem_count_reports_broken_references(tmp_path: Path) -> None:
    session = open_session(tmp_path)
    summary = session.current()
    assert summary is not None
    assert summary.problem_count == 0

    stack = session._stack
    assert stack is not None
    # A clip whose source is not in the project (cannot be made by commands).
    stack.project.clips.append(
        Clip(id=hid("a"), source_id=hid("nope"), in_ms=0, out_ms=1000)
    )
    summary = session.current()
    assert summary is not None
    assert summary.problem_count == 1
    assert len(session.timeline().problems) == 1


def client_for(session: Session, tmp_path: Path) -> TestClient:
    return TestClient(create_app(static_dir=tmp_path, session=session))


def test_endpoints_add_undo_redo(tmp_path: Path) -> None:
    session = open_session(tmp_path, make_source("s1"))
    client = client_for(session, tmp_path)

    added = client.post("/api/timeline/clips", json={"source_id": hid("s1")})
    assert added.status_code == 200
    assert len(added.json()["clips"]) == 1
    assert added.json()["can_undo"] is True

    undone = client.post("/api/timeline/undo")
    assert undone.status_code == 200
    assert undone.json()["label"] is not None
    assert undone.json()["timeline"]["clips"] == []
    assert undone.json()["timeline"]["can_redo"] is True

    redone = client.post("/api/timeline/redo")
    assert redone.status_code == 200
    assert len(redone.json()["timeline"]["clips"]) == 1

    assert client.get("/api/timeline").json()["duration_ms"] == 10_000


def test_endpoint_unknown_source_is_400(tmp_path: Path) -> None:
    client = client_for(open_session(tmp_path), tmp_path)
    response = client.post("/api/timeline/clips", json={"source_id": hid("nope")})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]


def test_endpoint_undo_with_nothing_returns_null_label(tmp_path: Path) -> None:
    client = client_for(open_session(tmp_path), tmp_path)
    response = client.post("/api/timeline/undo")
    assert response.status_code == 200
    assert response.json()["label"] is None


def test_endpoints_without_project_are_400(tmp_path: Path) -> None:
    client = client_for(Session(probe=_no_probe), tmp_path)
    for path, body in [
        ("/api/timeline/clips", {"source_id": hid("s1")}),
        ("/api/timeline/undo", None),
        ("/api/timeline/redo", None),
    ]:
        response = client.post(path, json=body)
        assert response.status_code == 400
        assert response.json()["detail"] == "no project is open"
