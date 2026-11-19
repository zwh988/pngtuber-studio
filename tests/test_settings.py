"""Settings (M7 S5): app-wide emotion presets, export defaults, paths and routes."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.commands import CommandError
from backend.project.edit_ops import SetExportSettingsOp, build_command
from backend.project.export_commands import SetExportSettings, check_fps
from backend.project.line_commands import NoChange
from backend.project.schema import Project
from backend.project.session import Session, SessionError
from backend.settings import PathItem, folder_to_open, path_items
from backend.voice.presets import EmotionPreset, PresetError, load_presets_file
from backend.voice.userpresets import (
    PresetEdit,
    build_presets_state,
    check_edit,
    encode_presets,
    load_effective,
    merge_with_builtin,
)

BUILTIN = load_presets_file()
NAMES = list(BUILTIN)


def edits(**changes: tuple[float, float, str]) -> list[PresetEdit]:
    out = []
    for name, p in BUILTIN.items():
        ex, cfg, expr = changes.get(name, (p.exaggeration, p.cfg_weight, p.expression))
        out.append(PresetEdit(name=name, exaggeration=ex, cfg_weight=cfg, expression=expr))
    return out


def _no_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("nothing should be probed")


# ---- presets, pure ------------------------------------------------------------


def test_check_edit_accepts_new_values_and_rounds() -> None:
    edited = check_edit(BUILTIN, edits(excited=(0.81234, 0.3, " happy ")))
    assert edited["excited"] == EmotionPreset("excited", 0.812, 0.3, "happy")
    assert edited["neutral"] == BUILTIN["neutral"]
    assert list(edited) == NAMES


def test_check_edit_refuses_added_removed_or_reordered_presets() -> None:
    with pytest.raises(PresetError, match="built-in ones"):
        check_edit(BUILTIN, edits()[:-1])
    with pytest.raises(PresetError, match="built-in ones"):
        check_edit(BUILTIN, list(reversed(edits())))
    extra = [*edits(), PresetEdit(name="angry", exaggeration=1, cfg_weight=0.3, expression="angry")]
    with pytest.raises(PresetError, match="built-in ones"):
        check_edit(BUILTIN, extra)


def test_check_edit_refuses_values_out_of_range_and_empty_expressions() -> None:
    with pytest.raises(PresetError, match="exaggeration"):
        check_edit(BUILTIN, edits(neutral=(2.5, 0.5, "neutral")))
    with pytest.raises(PresetError, match="cfg_weight"):
        check_edit(BUILTIN, edits(neutral=(0.5, -0.1, "neutral")))
    with pytest.raises(PresetError, match="expression"):
        check_edit(BUILTIN, edits(neutral=(0.5, 0.5, "  ")))


def test_merge_keeps_builtin_names_and_order() -> None:
    user = {"excited": EmotionPreset("excited", 1.0, 0.2, "hyped"), "gone": EmotionPreset("gone", 1, 1, "x")}
    merged = merge_with_builtin(BUILTIN, user)
    assert list(merged) == NAMES
    assert merged["excited"].exaggeration == 1.0
    assert merged["neutral"] == BUILTIN["neutral"]


def test_state_lists_builtin_values_beside_the_effective_ones(tmp_path: Path) -> None:
    effective = dict(BUILTIN)
    effective["nervous"] = EmotionPreset("nervous", 0.9, 0.3, "worried")
    state = build_presets_state(BUILTIN, effective, customized=True, path=tmp_path / "p.json", problem=None)
    nervous = next(item for item in state.presets if item.name == "nervous")
    assert (nervous.exaggeration, nervous.builtin_exaggeration) == (0.9, BUILTIN["nervous"].exaggeration)
    assert state.customized
    assert state.exaggeration_max == 2.0


# ---- presets, files -------------------------------------------------------------


def test_load_effective_without_a_user_file_is_builtin(tmp_path: Path) -> None:
    builtin, effective, customized, problem = load_effective(tmp_path / "none.json")
    assert effective == builtin == BUILTIN
    assert not customized and problem is None
    assert load_effective(None)[2] is False


def test_load_effective_uses_a_valid_user_file(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    changed = check_edit(BUILTIN, edits(confident=(0.7, 0.45, "smug")))
    path.write_text(json.dumps(encode_presets(changed)), encoding="utf-8")
    _, effective, customized, problem = load_effective(path)
    assert customized and problem is None
    assert effective["confident"].exaggeration == 0.7


def test_a_broken_user_file_falls_back_with_a_problem(tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    path.write_text("{not json", encoding="utf-8")
    _, effective, customized, problem = load_effective(path)
    assert effective == BUILTIN
    assert not customized
    assert problem is not None and "built-in values are in use" in problem


# ---- presets through the session ------------------------------------------------


def test_session_saves_resets_and_reloads_presets(tmp_path: Path) -> None:
    path = tmp_path / "app" / "emotion_presets.json"
    session = Session(probe=_no_probe, user_presets_path=path)
    assert not session.presets_state().customized
    state = session.save_presets(edits(excited=(0.9, 0.3, "excited")))
    assert state.customized and path.is_file()
    assert session._presets_or_raise()["excited"].exaggeration == 0.9  # used from now on
    # values equal to the built-ins remove the file
    assert not session.save_presets(edits()).customized
    assert not path.exists()
    session.save_presets(edits(nervous=(0.6, 0.4, "worried")))
    assert not session.reset_presets().customized
    assert not path.exists()
    assert session._presets_or_raise() == BUILTIN


def test_session_without_a_presets_path_cannot_save(tmp_path: Path) -> None:
    session = Session(probe=_no_probe)
    with pytest.raises(SessionError, match="not available"):
        session.save_presets(edits())
    with pytest.raises(SessionError, match="built-in ones"):
        Session(probe=_no_probe, user_presets_path=tmp_path / "p.json").save_presets(edits()[:2])


# ---- export defaults -------------------------------------------------------------


def project() -> Project:
    return Project(name="Rack")


def test_set_export_settings_applies_and_reverts() -> None:
    p = project()
    command = SetExportSettings(height=720, fps=30, include_avatar_overlay=True)
    command.apply(p)
    assert (p.export.height, p.export.fps, p.export.include_avatar_overlay) == (720, 30.0, True)
    assert p.export.include_raw_video_link is True  # untouched
    command.revert(p)
    assert (p.export.height, p.export.fps, p.export.include_avatar_overlay) == (1080, "match", False)
    assert command.label == "Change export defaults"


def test_set_export_settings_validates() -> None:
    with pytest.raises(CommandError, match="720 or 1080"):
        SetExportSettings(height=2160)
    with pytest.raises(CommandError, match="frame rate"):
        SetExportSettings(fps=0)
    with pytest.raises(CommandError, match="frame rate"):
        SetExportSettings(fps="fast")
    with pytest.raises(CommandError, match="true or false"):
        SetExportSettings(include_raw_video_link=1)  # type: ignore[arg-type]
    with pytest.raises(NoChange):
        SetExportSettings(height=1080, fps="match").apply(project())
    assert check_fps(59.94) == 59.94


def test_the_edit_op_builds_the_command() -> None:
    command = build_command(SetExportSettingsOp(unload_tts_before_export=True))
    p = project()
    command.apply(p)
    assert p.export.unload_tts_before_export is True


def test_export_defaults_through_the_batch_route_are_one_undo_step(tmp_path: Path) -> None:
    session = Session(probe=_no_probe)
    session.new_project(str(tmp_path), "Rack")
    client = TestClient(create_app(static_dir=tmp_path, session=session, export_tools=lambda: None))
    body = {
        "label": "Change export defaults",
        "ops": [{"op": "set_export_settings", "height": 720, "include_avatar_overlay": True}],
    }
    assert client.post("/api/timeline/batch", json=body).status_code == 200
    settings = client.get("/api/settings").json()
    assert settings["export"]["height"] == 720
    assert settings["export"]["include_avatar_overlay"] is True
    assert client.post("/api/timeline/undo").status_code == 200
    assert client.get("/api/settings").json()["export"]["height"] == 1080


# ---- paths and routes -------------------------------------------------------------


def test_path_items_report_existence_and_open_the_right_folder(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x")
    items = path_items([("a", "A", tmp_path, True), ("b", "B", tmp_path / "f.txt", False), ("c", "C", tmp_path / "no.txt", False)])
    assert [i.exists for i in items] == [True, True, False]
    assert folder_to_open(items[1]) == tmp_path
    assert folder_to_open(PathItem(key="d", label="D", path=str(tmp_path), exists=True, folder=True)) == tmp_path


@pytest.fixture
def client(tmp_path: Path) -> tuple[TestClient, list[Path]]:
    opened: list[Path] = []
    session = Session(probe=_no_probe, user_presets_path=tmp_path / "app" / "emotion_presets.json")
    app = create_app(
        static_dir=tmp_path,
        session=session,
        export_tools=lambda: "ffmpeg was not found",
        open_path=opened.append,
    )
    return TestClient(app), opened


def test_settings_route_without_a_project(client: tuple[TestClient, list[Path]]) -> None:
    c, _ = client
    body = c.get("/api/settings").json()
    assert body["export"] is None
    assert body["tools_problem"] == "ffmpeg was not found"
    assert [p["name"] for p in body["presets"]["presets"]] == NAMES
    keys = {p["key"] for p in body["paths"]}
    assert {"app_data", "recent", "worker_log", "presets", "ffmpeg", "ffprobe", "model", "templates"} <= keys


def test_presets_routes(client: tuple[TestClient, list[Path]]) -> None:
    c, _ = client
    payload = {"presets": [e.model_dump() for e in edits(neutral=(0.6, 0.5, "neutral"))]}
    saved = c.post("/api/settings/presets", json=payload).json()
    assert saved["customized"] is True
    assert saved["presets"][0]["exaggeration"] == 0.6
    bad = c.post("/api/settings/presets", json={"presets": payload["presets"][:1]})
    assert bad.status_code == 400
    assert c.post("/api/settings/presets/reset").json()["customized"] is False


def test_open_route(client: tuple[TestClient, list[Path]]) -> None:
    c, opened = client
    response = c.post("/api/settings/open", json={"key": "templates"})
    assert response.status_code == 200
    assert opened and opened[0].name == "templates"
    assert c.post("/api/settings/open", json={"key": "nope"}).status_code == 400


def test_the_presets_path_row_is_the_session_file(client: tuple[TestClient, list[Path]]) -> None:
    c, _ = client
    body = c.get("/api/settings").json()
    row = next(p for p in body["paths"] if p["key"] == "presets")
    assert row["path"] == body["presets"]["path"]
    assert row["path"].endswith("emotion_presets.json")
