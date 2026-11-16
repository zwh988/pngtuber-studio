"""Avatar art folder on disk, the setting, the session and the endpoints (M5-1)."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app import create_app
from backend.avatar.scan import (
    ArtFolderError,
    avatar_status_text,
    build_avatar_state,
    resolve_art_folder,
    scan_art_folder,
    to_stored_path,
)
from backend.project.avatar_commands import SetAvatarArtFolder
from backend.project.commands import CommandError, CommandStack
from backend.project.line_commands import NoChange
from backend.project.schema import AvatarSettings, Project
from backend.project.session import Session, SessionError

REPO = Path(__file__).resolve().parent.parent
REAL_ART = REPO / "avatars" / "nanairo miku"


def make_art(root: Path, name: str = "my avatar", folders: int = 3) -> Path:
    art = root / name
    for i in range(1, folders + 1):
        folder = art / f"{i:02d}_expr{i}"
        folder.mkdir(parents=True)
        for letter, code in zip("abcd", ("oicm", "oiom", "cicm", "ciom"), strict=True):
            (folder / f"{i:02d}{letter}_expr{i}_{code}.png").write_bytes(b"png")
        (folder / "looped_preview.mov").write_bytes(b"mov")
    return art


# ---- schema and command -------------------------------------------------------------


def test_art_folder_accepts_relative_and_absolute_posix() -> None:
    assert AvatarSettings(art_folder="art/miku").art_folder == "art/miku"
    assert AvatarSettings(art_folder="D:/ZWH/avatars/nanairo miku").art_folder
    assert AvatarSettings(art_folder="/home/x/art").art_folder
    for bad in ("D:\\art", "../art", "D:/a/../b", ""):
        with pytest.raises(ValidationError):
            AvatarSettings(art_folder=bad)


def test_set_art_folder_command_undo_redo() -> None:
    project = Project(name="t")
    stack = CommandStack(project)
    stack.execute(SetAvatarArtFolder("D:/art/miku"))
    assert project.avatar.art_folder == "D:/art/miku"
    assert stack.undo_label == "Set avatar art"
    stack.undo()
    assert project.avatar.art_folder is None
    stack.redo()
    assert project.avatar.art_folder == "D:/art/miku"
    with pytest.raises(NoChange):
        SetAvatarArtFolder("D:/art/miku").apply(project)
    with pytest.raises(CommandError):
        SetAvatarArtFolder("D:\\bad").apply(project)
    assert SetAvatarArtFolder(None).label == "Clear avatar art"


# ---- paths and scanning -----------------------------------------------------------


def test_stored_paths(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    inside = project / "art" / "miku"
    inside.mkdir(parents=True)
    outside = make_art(tmp_path)
    assert to_stored_path(inside, project) == "art/miku"
    stored = to_stored_path(outside, project)
    assert stored == outside.resolve().as_posix()
    assert resolve_art_folder("art/miku", project) == project / "art" / "miku"
    assert resolve_art_folder(stored, project).resolve() == outside.resolve()


def test_scan_reads_the_tree_and_avatar_json(tmp_path: Path) -> None:
    art_dir = make_art(tmp_path)
    (art_dir / "avatar.json").write_text(
        json.dumps({"default_expression": "expr2", "emotion_map": {"excited": "expr3"}}),
        encoding="utf-8",
    )
    art = scan_art_folder(art_dir)
    assert [e.id for e in art.expressions] == ["expr1", "expr2", "expr3"]
    assert art.default_expression == "expr2"
    assert dict(art.emotion_map) == {"excited": "expr3"}
    assert art.warnings == ()


def test_broken_avatar_json_is_a_warning(tmp_path: Path) -> None:
    art_dir = make_art(tmp_path)
    (art_dir / "avatar.json").write_text("{nope", encoding="utf-8")
    art = scan_art_folder(art_dir)
    assert art.default_expression == "expr1"
    assert any("avatar.json" in w for w in art.warnings)


def test_missing_folder_raises(tmp_path: Path) -> None:
    with pytest.raises(ArtFolderError):
        scan_art_folder(tmp_path / "nope")


def test_build_state(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    assert build_avatar_state(None, project).status == "not_configured"
    missing = build_avatar_state("D:/nowhere/at/all", project)
    assert missing.status == "folder_missing" and missing.problem
    assert avatar_status_text(missing) == "art folder missing"
    art_dir = make_art(tmp_path)
    (art_dir / "01_expr1" / "01d_expr1_ciom.png").unlink()
    state = build_avatar_state(art_dir.resolve().as_posix(), project)
    assert state.status == "ready"
    assert state.external and state.name == "my avatar"
    assert state.expressions[0].states == ["oicm", "oiom", "cicm"]
    assert not state.expressions[0].complete
    assert len(state.warnings) == 1
    assert avatar_status_text(state) == "my avatar: 3 expressions, 1 warnings"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert build_avatar_state(empty.as_posix(), project).status == "no_art"


# ---- session and endpoints -------------------------------------------------------


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def open_session(tmp_path: Path) -> tuple[Session, Path]:
    session = Session(probe=fake_probe)
    session.new_project(str(tmp_path), "Rack")
    return session, tmp_path / "Rack"


def test_session_sets_clears_and_undoes_the_folder(tmp_path: Path) -> None:
    session, folder = open_session(tmp_path)
    assert session.avatar().status == "not_configured"
    art_dir = make_art(tmp_path / "shared")
    state = session.set_avatar_folder(str(art_dir))
    assert state.status == "ready" and state.can_undo
    assert state.art_folder == art_dir.resolve().as_posix()
    assert session.current().avatar_status == "my avatar: 3 expressions"
    again = session.set_avatar_folder(str(art_dir))  # same folder: no new undo step
    assert again.undo_label == "Set avatar art"
    session.undo()
    assert session.avatar().status == "not_configured"
    session.redo()
    assert session.set_avatar_folder(None).status == "not_configured"
    with pytest.raises(SessionError):
        session.set_avatar_folder(str(tmp_path / "missing"))
    # Saved with the project.
    session.set_avatar_folder(str(art_dir))
    reopened = Session(probe=fake_probe)
    reopened.open_project(str(folder))
    assert reopened.avatar().status == "ready"


def test_avatar_endpoints(tmp_path: Path) -> None:
    session, _ = open_session(tmp_path)
    client = TestClient(create_app(session=session))
    assert client.get("/api/avatar").json()["status"] == "not_configured"
    art_dir = make_art(tmp_path / "shared")
    body = client.post("/api/avatar/folder", json={"path": str(art_dir)}).json()
    assert body["status"] == "ready" and len(body["expressions"]) == 3
    assert client.post("/api/avatar/folder", json={"path": "Z:/nope"}).status_code == 400
    assert client.post("/api/avatar/folder", json={"path": None}).json()["status"] == (
        "not_configured"
    )


@pytest.mark.skipif(not REAL_ART.is_dir(), reason="the user's art folder is not here")
def test_the_real_art_folder_has_ten_complete_expressions() -> None:
    art = scan_art_folder(REAL_ART)
    assert [e.id for e in art.expressions] == [
        "smile", "cheeky", "confident", "focus", "thinking",
        "loading", "somber", "mindbreak", "serious", "angry",
    ]
    assert all(e.complete for e in art.expressions)
    assert art.warnings == ()
    assert art.default_expression == "smile"
