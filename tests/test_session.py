from pathlib import Path

import pytest

from backend.project.schema import SCHEMA_VERSION, Project
from backend.project.session import Session, SessionError, clean_folder_name
from backend.project.store import project_file
from backend.project.summary import NOT_CONFIGURED, PATH_SET, summarize


@pytest.mark.parametrize("name", ["MyRack", "  My Rack 2  ", "a.b", "Rack-1_final"])
def test_clean_folder_name_accepts(name: str) -> None:
    assert clean_folder_name(name) == name.strip()


@pytest.mark.parametrize(
    "name", ["", "   ", "a/b", "a\\b", "x:y", "q?", "end.", "CON", "nul.txt", "LPT3"]
)
def test_clean_folder_name_rejects(name: str) -> None:
    with pytest.raises(ValueError):
        clean_folder_name(name)


def test_summarize_defaults() -> None:
    summary = summarize("C:/x", Project(name="P"))
    assert summary.name == "P"
    assert summary.folder == "C:/x"
    assert summary.schema_version == SCHEMA_VERSION
    assert summary.source_count == 0
    assert summary.clip_count == 0
    assert summary.voice_status == NOT_CONFIGURED
    assert summary.avatar_status == NOT_CONFIGURED


def test_summarize_avatar_path_set() -> None:
    project = Project(name="P")
    project.avatar.art_folder = "art/miku"
    assert summarize("x", project).avatar_status == PATH_SET


def test_current_is_none_initially() -> None:
    assert Session().current() is None


def test_new_project_creates_files_and_opens(tmp_path: Path) -> None:
    session = Session()
    summary = session.new_project(str(tmp_path), "My Rack")
    folder = tmp_path / "My Rack"
    assert project_file(folder).is_file()
    for sub in ("footage", "exports", "media/takes_raw"):
        assert (folder / sub).is_dir()
    assert summary.name == "My Rack"
    assert summary.folder == str(folder)
    assert summary.clip_count == 0
    assert session.current() == summary


def test_new_project_twice_is_refused(tmp_path: Path) -> None:
    session = Session()
    session.new_project(str(tmp_path), "Rack")
    with pytest.raises(SessionError, match="already exists"):
        session.new_project(str(tmp_path), "Rack")


def test_new_project_missing_parent(tmp_path: Path) -> None:
    with pytest.raises(SessionError, match="parent folder"):
        Session().new_project(str(tmp_path / "nope"), "Rack")


def test_new_project_bad_name(tmp_path: Path) -> None:
    with pytest.raises(SessionError):
        Session().new_project(str(tmp_path), "a/b")


def test_open_project_round_trip(tmp_path: Path) -> None:
    created = Session().new_project(str(tmp_path), "Rack")
    other = Session()
    opened = other.open_project(created.folder)
    assert opened == created
    assert other.current() == created


def test_open_folder_without_project(tmp_path: Path) -> None:
    with pytest.raises(SessionError, match="no project.json"):
        Session().open_project(str(tmp_path))


def test_failed_open_keeps_current_project(tmp_path: Path) -> None:
    session = Session()
    created = session.new_project(str(tmp_path), "Rack")
    with pytest.raises(SessionError):
        session.open_project(str(tmp_path / "empty"))
    assert session.current() == created
