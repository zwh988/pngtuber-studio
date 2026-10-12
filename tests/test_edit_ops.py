import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import create_app
from backend.project.clip_commands import AddClip, RemoveClip, ReorderClip, SetSpeed
from backend.project.commands import AddSource
from backend.project.cut_commands import RippleDelete, SplitClip, TrimClip
from backend.project.edit_ops import (
    AddClipOp,
    EditBatch,
    EditOp,
    RemoveClipOp,
    ReorderClipOp,
    RippleDeleteOp,
    SetSpeedOp,
    SplitClipOp,
    TrimClipOp,
    build_command,
)
from backend.project.schema import Source
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
    session = Session(probe=_no_probe)
    session.new_project(str(tmp_path), "Rack")
    stack = session._stack
    assert stack is not None
    for source in sources:
        stack.execute(AddSource(source))
    stack.clear()
    return session


def one_clip_session(tmp_path: Path) -> Session:
    """A 10 s clip on the timeline with an empty undo history."""
    session = open_session(tmp_path, make_source("s1"))
    session.add_clip(hid("s1"))
    stack = session._stack
    assert stack is not None
    stack.clear()
    return session


def durations(session: Session) -> list[int]:
    return [clip.duration_ms for clip in session.timeline().clips]


# ---- pure: op models and command building ------------------------------------


@pytest.mark.parametrize(
    ("op", "expected"),
    [
        (AddClipOp(source_id="x"), AddClip),
        (RemoveClipOp(clip_id="x"), RemoveClip),
        (SetSpeedOp(clip_id="x", speed=2.0), SetSpeed),
        (ReorderClipOp(clip_id="x", new_position=0), ReorderClip),
        (SplitClipOp(timeline_ms=1000), SplitClip),
        (TrimClipOp(clip_id="x", edge="in", source_ms=500), TrimClip),
        (RippleDeleteOp(start_ms=0, end_ms=500), RippleDelete),
    ],
)
def test_build_command_returns_matching_command(op: EditOp, expected: type) -> None:
    assert isinstance(build_command(op), expected)


def test_batch_parses_each_op_by_its_op_field() -> None:
    batch = EditBatch.model_validate(
        {
            "label": "Cut",
            "ops": [
                {"op": "split_clip", "timeline_ms": 1000},
                {"op": "trim_clip", "clip_id": "c", "edge": "out", "source_ms": 900},
            ],
        }
    )
    assert isinstance(batch.ops[0], SplitClipOp)
    assert isinstance(batch.ops[1], TrimClipOp)


@pytest.mark.parametrize(
    "body",
    [
        {"label": "x", "ops": []},
        {"label": "", "ops": [{"op": "split_clip", "timeline_ms": 1}]},
        {"label": "x", "ops": [{"op": "explode"}]},
        {"label": "x", "ops": [{"op": "split_clip", "timeline_ms": 1, "oops": 1}]},
        {"label": "x", "ops": [{"op": "trim_clip", "clip_id": "c", "edge": "mid", "source_ms": 1}]},
    ],
)
def test_batch_rejects_bad_bodies(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EditBatch.model_validate(body)


# ---- session: each operation --------------------------------------------------


def test_split(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    original = session.timeline().clips[0].id
    state = session.edit([SplitClipOp(timeline_ms=4000, right_clip_id=hid("r"))])
    assert [c.duration_ms for c in state.clips] == [4000, 6000]
    assert state.clips[0].id == original
    assert state.clips[1].id == hid("r")
    assert state.duration_ms == 10_000


def test_split_undo_and_redo(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    session.edit([SplitClipOp(timeline_ms=4000)])
    assert len(session.timeline().clips) == 2
    assert len(session.undo().timeline.clips) == 1
    assert durations(session) == [10_000]
    assert len(session.redo().timeline.clips) == 2


def test_split_without_right_id_generates_one(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    state = session.edit([SplitClipOp(timeline_ms=4000)])
    assert state.clips[0].id != state.clips[1].id


def test_refused_edit_changes_nothing(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    with pytest.raises(SessionError):
        session.edit([SplitClipOp(timeline_ms=20_000)])
    assert durations(session) == [10_000]
    assert session.timeline().can_undo is False


def test_split_at_existing_cut_is_refused(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    session.edit([SplitClipOp(timeline_ms=4000)])
    with pytest.raises(SessionError):
        session.edit([SplitClipOp(timeline_ms=4000)])
    assert len(session.timeline().clips) == 2


def test_ripple_delete_inside_a_clip(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    state = session.edit([RippleDeleteOp(start_ms=2000, end_ms=4000)])
    assert [c.duration_ms for c in state.clips] == [2000, 6000]
    assert state.duration_ms == 8000
    assert session.undo().timeline.duration_ms == 10_000


def test_trim_out_edge(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    clip_id = session.timeline().clips[0].id
    state = session.edit([TrimClipOp(clip_id=clip_id, edge="out", source_ms=8000)])
    assert state.clips[0].out_ms == 8000
    assert state.duration_ms == 8000


def test_trim_unknown_clip_is_refused(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    with pytest.raises(SessionError):
        session.edit([TrimClipOp(clip_id=hid("nope"), edge="out", source_ms=8000)])


def test_reorder(tmp_path: Path) -> None:
    session = open_session(tmp_path, make_source("s1"), make_source("s2", 6000))
    session.add_clip(hid("s1"))
    state = session.add_clip(hid("s2"))
    first = state.clips[0].id
    state = session.edit([ReorderClipOp(clip_id=first, new_position=1)])
    assert [c.source_id for c in state.clips] == [hid("s2"), hid("s1")]
    assert state.duration_ms == 16_000


def test_set_speed(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    clip_id = session.timeline().clips[0].id
    state = session.edit([SetSpeedOp(clip_id=clip_id, speed=2.0)])
    assert state.clips[0].speed == 2.0
    assert state.duration_ms == 5000


@pytest.mark.parametrize("speed", [0.1, 9.0, 1.0])
def test_bad_or_unchanged_speed_is_refused(tmp_path: Path, speed: float) -> None:
    session = one_clip_session(tmp_path)
    clip_id = session.timeline().clips[0].id
    with pytest.raises(SessionError):
        session.edit([SetSpeedOp(clip_id=clip_id, speed=speed)])
    assert durations(session) == [10_000]


def test_remove_clip(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    clip_id = session.timeline().clips[0].id
    state = session.edit([RemoveClipOp(clip_id=clip_id)])
    assert state.clips == []
    assert len(session.undo().timeline.clips) == 1


# ---- session: batches and groups ----------------------------------------------


def test_batch_is_one_undo_step(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    state = session.edit(
        [
            SplitClipOp(timeline_ms=4000, right_clip_id=hid("r")),
            TrimClipOp(clip_id=hid("r"), edge="out", source_ms=8000),
        ],
        label="Cut and trim",
    )
    assert [c.duration_ms for c in state.clips] == [4000, 4000]
    assert state.undo_label == "Cut and trim"

    undone = session.undo()
    assert undone.label == "Cut and trim"
    assert durations(session) == [10_000]
    assert undone.timeline.can_undo is False

    redone = session.redo()
    assert redone.label == "Cut and trim"
    assert [c.id for c in redone.timeline.clips][1] == hid("r")
    assert durations(session) == [4000, 4000]


def test_batch_is_all_or_nothing(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    with pytest.raises(SessionError):
        session.edit(
            [
                SplitClipOp(timeline_ms=4000),
                TrimClipOp(clip_id=hid("missing"), edge="out", source_ms=8000),
            ],
            label="Broken",
        )
    assert durations(session) == [10_000]
    assert session.timeline().can_undo is False


def test_single_op_with_label_is_a_group_with_that_label(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    state = session.edit([SplitClipOp(timeline_ms=4000)], label="Split at playhead")
    assert state.undo_label == "Split at playhead"


def test_edit_with_no_ops_is_refused(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    with pytest.raises(SessionError):
        session.edit([])


def test_edit_requires_open_project() -> None:
    with pytest.raises(SessionError):
        Session(probe=_no_probe).edit([SplitClipOp(timeline_ms=1000)])


def test_edit_is_saved_and_survives_reopen(tmp_path: Path) -> None:
    session = one_clip_session(tmp_path)
    session.edit([SplitClipOp(timeline_ms=4000)])
    session.edit([SetSpeedOp(clip_id=session.timeline().clips[1].id, speed=2.0)])

    reopened = Session(probe=_no_probe)
    reopened.open_project(str(tmp_path / "Rack"))
    assert [c.duration_ms for c in reopened.timeline().clips] == [4000, 3000]


# ---- endpoints -----------------------------------------------------------------


def client_for(session: Session, tmp_path: Path) -> TestClient:
    return TestClient(create_app(static_dir=tmp_path, session=session))


def test_endpoints_every_operation(tmp_path: Path) -> None:
    client = client_for(one_clip_session(tmp_path), tmp_path)

    state = client.post("/api/timeline/split", json={"timeline_ms": 4000}).json()
    assert [c["duration_ms"] for c in state["clips"]] == [4000, 6000]
    first, second = state["clips"][0]["id"], state["clips"][1]["id"]

    state = client.post("/api/timeline/speed", json={"clip_id": second, "speed": 2.0}).json()
    assert state["duration_ms"] == 7000

    state = client.post(
        "/api/timeline/trim", json={"clip_id": first, "edge": "out", "source_ms": 3000}
    ).json()
    assert state["duration_ms"] == 6000

    state = client.post(
        "/api/timeline/reorder", json={"clip_id": first, "new_position": 1}
    ).json()
    assert [c["id"] for c in state["clips"]] == [second, first]

    state = client.post("/api/timeline/remove", json={"clip_id": second}).json()
    assert [c["id"] for c in state["clips"]] == [first]
    assert state["duration_ms"] == 3000

    state = client.post(
        "/api/timeline/ripple-delete", json={"start_ms": 500, "end_ms": 1000}
    ).json()
    assert [c["duration_ms"] for c in state["clips"]] == [500, 2000]
    assert state["duration_ms"] == 2500


def test_endpoint_batch_is_one_undo_step(tmp_path: Path) -> None:
    client = client_for(one_clip_session(tmp_path), tmp_path)
    body = {
        "label": "Cut and trim",
        "ops": [
            {"op": "split_clip", "timeline_ms": 4000, "right_clip_id": hid("r")},
            {"op": "trim_clip", "clip_id": hid("r"), "edge": "out", "source_ms": 8000},
        ],
    }
    response = client.post("/api/timeline/batch", json=body)
    assert response.status_code == 200
    assert response.json()["undo_label"] == "Cut and trim"
    assert response.json()["duration_ms"] == 8000

    undone = client.post("/api/timeline/undo").json()
    assert undone["label"] == "Cut and trim"
    assert undone["timeline"]["duration_ms"] == 10_000


def test_endpoint_refused_edit_is_400_with_message(tmp_path: Path) -> None:
    client = client_for(one_clip_session(tmp_path), tmp_path)
    response = client.post("/api/timeline/split", json={"timeline_ms": 20_000})
    assert response.status_code == 400
    assert isinstance(response.json()["detail"], str)
    assert response.json()["detail"]


def test_endpoint_failed_batch_changes_nothing(tmp_path: Path) -> None:
    client = client_for(one_clip_session(tmp_path), tmp_path)
    body = {
        "label": "Broken",
        "ops": [
            {"op": "split_clip", "timeline_ms": 4000},
            {"op": "remove_clip", "clip_id": hid("missing")},
        ],
    }
    assert client.post("/api/timeline/batch", json=body).status_code == 400
    state = client.get("/api/timeline").json()
    assert len(state["clips"]) == 1
    assert state["can_undo"] is False


def test_edit_endpoints_without_project_are_400(tmp_path: Path) -> None:
    client = client_for(Session(probe=_no_probe), tmp_path)
    for path, body in [
        ("/api/timeline/split", {"timeline_ms": 1000}),
        ("/api/timeline/ripple-delete", {"start_ms": 0, "end_ms": 500}),
        ("/api/timeline/trim", {"clip_id": "x", "edge": "in", "source_ms": 500}),
        ("/api/timeline/reorder", {"clip_id": "x", "new_position": 0}),
        ("/api/timeline/speed", {"clip_id": "x", "speed": 2.0}),
        ("/api/timeline/remove", {"clip_id": "x"}),
        (
            "/api/timeline/batch",
            {"label": "x", "ops": [{"op": "remove_clip", "clip_id": "x"}]},
        ),
    ]:
        response = client.post(path, json=body)
        assert response.status_code == 400, path
        assert response.json()["detail"] == "no project is open"
