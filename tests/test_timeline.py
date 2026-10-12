import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.schema import Clip, Project, Source
from backend.project.session import Session, SessionError
from backend.project.timeline import build_timeline


def hid(name: str) -> str:
    """Readable test name to a valid 12-char hex id (the schema requires one)."""
    return hashlib.sha1(name.encode()).hexdigest()[:12]


def make_source(source_id: str = "s1", *, fps_num: int = 60, fps_den: int = 1) -> Source:
    return Source(
        id=hid(source_id),
        path=f"footage/{source_id}.mkv",
        duration_ms=10_000,
        fps_num=fps_num,
        fps_den=fps_den,
        width=2560,
        height=1440,
        audio_tracks=1,
    )


def make_clip(
    clip_id: str,
    source_id: str = "s1",
    *,
    in_ms: int = 0,
    out_ms: int = 4000,
    speed: float = 1.0,
    track: int = 0,
) -> Clip:
    return Clip(
        id=hid(clip_id),
        source_id=hid(source_id),
        in_ms=in_ms,
        out_ms=out_ms,
        speed=speed,
        track=track,
    )


def test_empty_project() -> None:
    state = build_timeline(Project(name="t"))
    assert state.clips == []
    assert state.duration_ms == 0
    assert state.problems == []
    assert state.orphan_count == 0
    assert not state.can_undo
    assert not state.can_redo


def test_spans_positions_and_speed() -> None:
    project = Project(
        name="t",
        sources=[make_source()],
        clips=[
            make_clip("a", out_ms=4000),
            make_clip("b", in_ms=1000, out_ms=3000, speed=2.0),
        ],
    )
    state = build_timeline(project)
    assert [c.id for c in state.clips] == [hid("a"), hid("b")]
    assert [c.position for c in state.clips] == [0, 1]
    assert (state.clips[0].start_ms, state.clips[0].end_ms) == (0, 4000)
    assert (state.clips[1].start_ms, state.clips[1].end_ms) == (4000, 5000)
    assert state.clips[1].duration_ms == 1000
    assert state.duration_ms == 5000
    assert state.clips[0].source is not None
    assert state.clips[0].source.fps == 60.0
    assert state.clips[0].source.file_missing is False


def test_fps_5994_is_exact() -> None:
    project = Project(
        name="t",
        sources=[make_source(fps_num=60000, fps_den=1001)],
        clips=[make_clip("a")],
    )
    source = build_timeline(project).clips[0].source
    assert source is not None
    assert (source.fps_num, source.fps_den) == (60000, 1001)


def test_other_track_clips_are_counted_not_listed() -> None:
    project = Project(
        name="t",
        sources=[make_source()],
        clips=[make_clip("a"), make_clip("x", track=1)],
    )
    state = build_timeline(project)
    assert [c.id for c in state.clips] == [hid("a")]
    assert state.other_track_clips == 1


def test_missing_file_flag() -> None:
    project = Project(name="t", sources=[make_source()], clips=[make_clip("a")])
    state = build_timeline(project, missing_source_ids={hid("s1")})
    source = state.clips[0].source
    assert source is not None
    assert source.file_missing is True


def test_unknown_source_is_reported() -> None:
    project = Project(name="t", sources=[], clips=[make_clip("a", "nope")])
    state = build_timeline(project)
    assert state.clips[0].source is None
    assert len(state.problems) == 1
    assert state.problems[0].owner_id == hid("a")
    assert state.problems[0].missing_id == hid("nope")


def test_undo_status_is_passed_through() -> None:
    state = build_timeline(
        Project(name="t"),
        can_undo=True,
        undo_label="Split clip",
        redo_label=None,
    )
    assert state.can_undo is True
    assert state.undo_label == "Split clip"
    assert state.redo_label is None


def _no_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("no footage, so nothing should be probed")


def test_session_requires_open_project() -> None:
    with pytest.raises(SessionError):
        Session(probe=_no_probe).timeline()


def test_endpoint_without_project_is_400(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=tmp_path, session=Session(probe=_no_probe)))
    response = client.get("/api/timeline")
    assert response.status_code == 400
    assert response.json()["detail"] == "no project is open"


def test_endpoint_with_empty_project(tmp_path: Path) -> None:
    session = Session(probe=_no_probe)
    session.new_project(str(tmp_path), "Rack")
    client = TestClient(create_app(static_dir=tmp_path, session=session))
    response = client.get("/api/timeline")
    assert response.status_code == 200
    body = response.json()
    assert body["clips"] == []
    assert body["duration_ms"] == 0
    assert body["problems"] == []
    assert body["save_error"] is None
