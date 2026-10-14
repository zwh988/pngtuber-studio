"""Line bank through Session and the API (M3-4)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.line_ops import (
    AddLineOp,
    RemoveLineOp,
    SetLineCfgWeightOp,
    SetLineEmotionOp,
    SetLineExaggerationOp,
    SetLineTextOp,
)
from backend.project.session import Session, SessionError
from backend.voice.presets import parse_presets

PRESETS = parse_presets(
    {
        "presets": {
            "neutral": {"exaggeration": 0.5, "cfg_weight": 0.5, "expression": "neutral"},
            "excited": {"exaggeration": 0.9, "cfg_weight": 0.3, "expression": "happy"},
        }
    }
)
L1 = "aaaaaaaaaaaa"


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def make_session() -> Session:
    return Session(probe=fake_probe, presets=PRESETS)


def open_project(tmp_path: Path, session: Session) -> Path:
    session.new_project(str(tmp_path), "Rack")
    return tmp_path / "Rack"


def test_lines_without_a_project_is_an_error() -> None:
    with pytest.raises(SessionError, match="no project is open"):
        make_session().lines()


def test_empty_bank_lists_emotions(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    state = session.lines()
    assert state.lines == []
    assert state.emotions == ["neutral", "excited"]


def test_add_line_shows_effective_values(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    state = session.edit_lines([AddLineOp(text="hello", line_id=L1)])
    item = state.lines[0]
    assert (item.id, item.text, item.emotion) == (L1, "hello", "neutral")
    assert (item.effective_exaggeration, item.effective_cfg_weight) == (0.5, 0.5)
    assert not item.generated
    assert state.undo_label == "Add line"


def test_unknown_emotion_is_refused(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    with pytest.raises(SessionError, match="unknown emotion"):
        session.edit_lines([AddLineOp(emotion="furious")])
    assert session.lines().lines == []


def test_edit_then_undo_with_the_shared_stack(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    session.edit_lines([AddLineOp(line_id=L1)])
    session.edit_lines([SetLineTextOp(line_id=L1, text="typed")])
    assert session.lines().lines[0].text == "typed"
    session.undo()
    assert session.lines().lines[0].text == ""
    session.redo()
    assert session.lines().lines[0].text == "typed"


def test_a_labelled_batch_is_one_undo_step(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    state = session.edit_lines(
        [
            AddLineOp(line_id=L1, text="hello"),
            SetLineEmotionOp(line_id=L1, emotion="excited"),
            SetLineExaggerationOp(line_id=L1, value=1.2),
        ],
        label="New line",
    )
    item = state.lines[0]
    assert (item.emotion, item.effective_exaggeration, item.effective_cfg_weight) == (
        "excited",
        1.2,
        0.3,
    )
    assert state.undo_label == "New line"
    session.undo()
    assert session.lines().lines == []


def test_a_failing_batch_applies_nothing(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    with pytest.raises(SessionError, match="unknown line"):
        session.edit_lines(
            [AddLineOp(line_id=L1), SetLineTextOp(line_id="999999999999", text="x")],
            label="Bad",
        )
    state = session.lines()
    assert state.lines == []
    assert not state.can_undo


def test_an_op_that_changes_nothing_is_skipped(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    session.edit_lines([AddLineOp(line_id=L1, text="same")])
    state = session.edit_lines([SetLineTextOp(line_id=L1, text="same")])
    assert state.undo_label == "Add line"
    session.undo()
    assert not session.lines().can_undo


def test_a_batch_of_only_no_change_ops_makes_no_undo_step(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    session.edit_lines([AddLineOp(line_id=L1, text="same")])
    state = session.edit_lines(
        [SetLineTextOp(line_id=L1, text="same")], label="Edit"
    )
    assert state.undo_label == "Add line"


def test_sliders_can_be_overridden_and_cleared(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    session.edit_lines([AddLineOp(line_id=L1)])
    state = session.edit_lines([SetLineCfgWeightOp(line_id=L1, value=0.1)])
    assert state.lines[0].effective_cfg_weight == 0.1
    state = session.edit_lines([SetLineCfgWeightOp(line_id=L1, value=None)])
    assert state.lines[0].effective_cfg_weight == 0.5
    with pytest.raises(SessionError, match="invalid cfg_weight"):
        session.edit_lines([SetLineCfgWeightOp(line_id=L1, value=3.0)])


def test_remove_line(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    session.edit_lines([AddLineOp(line_id=L1)])
    assert session.edit_lines([RemoveLineOp(line_id=L1)]).lines == []
    session.undo()
    assert [item.id for item in session.lines().lines] == [L1]


def test_no_ops_is_an_error(tmp_path: Path) -> None:
    session = make_session()
    open_project(tmp_path, session)
    with pytest.raises(SessionError, match="no edits given"):
        session.edit_lines([])


def test_edits_are_saved_to_project_json(tmp_path: Path) -> None:
    session = make_session()
    folder = open_project(tmp_path, session)
    session.edit_lines([AddLineOp(line_id=L1, text="kept")])
    reopened = make_session()
    reopened.open_project(str(folder))
    assert [item.text for item in reopened.lines().lines] == ["kept"]


def test_the_real_presets_file_is_used_when_none_is_given(tmp_path: Path) -> None:
    session = Session(probe=fake_probe)
    open_project(tmp_path, session)
    state = session.lines()
    assert "neutral" in state.emotions


# ---- API --------------------------------------------------------------------


def make_client(tmp_path: Path) -> tuple[TestClient, Session]:
    session = make_session()
    app = create_app(static_dir=tmp_path / "no-frontend", session=session)
    return TestClient(app), session


def test_api_lines_without_a_project_is_400(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)
    assert client.get("/api/lines").status_code == 400


def test_api_edit_and_get(tmp_path: Path) -> None:
    client, session = make_client(tmp_path)
    open_project(tmp_path, session)
    response = client.post(
        "/api/lines/edit",
        json={
            "label": "New line",
            "ops": [
                {"op": "add_line", "line_id": L1, "text": "hello"},
                {"op": "set_line_exaggeration", "line_id": L1, "value": 1.1},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lines"][0]["text"] == "hello"
    assert body["lines"][0]["effective_exaggeration"] == 1.1
    assert body["undo_label"] == "New line"
    assert client.get("/api/lines").json() == body


def test_api_bad_edit_is_400_and_bad_shape_is_422(tmp_path: Path) -> None:
    client, session = make_client(tmp_path)
    open_project(tmp_path, session)
    bad = client.post(
        "/api/lines/edit",
        json={"ops": [{"op": "set_line_text", "line_id": "999999999999", "text": "x"}]},
    )
    assert bad.status_code == 400
    assert "unknown line" in bad.json()["detail"]
    assert client.post("/api/lines/edit", json={"ops": [{"op": "nope"}]}).status_code == 422
