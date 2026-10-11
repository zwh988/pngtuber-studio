import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.recent import (
    RecentEntry,
    add_recent,
    default_recent_path,
    load_recent,
    parse_recent,
    remove_recent,
    save_recent,
)
from backend.project.session import Session

NO_FRONTEND = Path("does-not-exist")


def _entry(name: str, folder: str, when: str = "2026-10-11T10:00:00+00:00") -> RecentEntry:
    return RecentEntry(name=name, folder=folder, last_opened=when)


def test_add_puts_newest_first() -> None:
    entries = [_entry("A", "D:\\A")]
    result = add_recent(entries, "B", "D:\\B", "2026-10-11T11:00:00+00:00")
    assert [e.name for e in result] == ["B", "A"]
    assert len(entries) == 1  # input list not mutated


def test_add_dedupes_case_and_slash_variants() -> None:
    entries = [_entry("Rack", "D:\\Projects\\Rack"), _entry("Other", "D:\\Other")]
    result = add_recent(entries, "Rack", "d:/projects/rack/", "2026-10-11T12:00:00+00:00")
    assert [e.name for e in result] == ["Rack", "Other"]
    assert result[0].folder == "d:/projects/rack/"


def test_add_respects_limit() -> None:
    entries: list[RecentEntry] = []
    for i in range(5):
        entries = add_recent(entries, f"P{i}", f"D:\\P{i}", "t", limit=3)
    assert [e.name for e in entries] == ["P4", "P3", "P2"]


def test_remove_recent() -> None:
    entries = [_entry("A", "D:\\A"), _entry("B", "D:\\B")]
    assert [e.name for e in remove_recent(entries, "d:/a")] == ["B"]
    assert remove_recent(entries, "D:\\Nope") == entries


def test_parse_recent_is_tolerant() -> None:
    assert parse_recent(None) == []
    assert parse_recent([]) == []
    assert parse_recent({"recent": "x"}) == []
    good = {"name": "A", "folder": "D:\\A", "last_opened": "t"}
    parsed = parse_recent({"recent": [good, {"name": "bad"}, 5]})
    assert [e.name for e in parsed] == ["A"]


def test_save_load_round_trip_creates_parent(tmp_path: Path) -> None:
    path = tmp_path / "cfg" / "recent.json"
    entries = [_entry("A", "D:\\A")]
    save_recent(path, entries)
    assert load_recent(path) == entries
    assert [p.name for p in path.parent.iterdir()] == ["recent.json"]


def test_load_missing_and_corrupt(tmp_path: Path) -> None:
    assert load_recent(tmp_path / "missing.json") == []
    bad = tmp_path / "recent.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_recent(bad) == []


def test_default_recent_path_uses_appdata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert default_recent_path() == tmp_path / "PNGtuberStudio" / "recent.json"


def _projects(tmp_path: Path) -> Path:
    projects = tmp_path / "projects"
    projects.mkdir()
    return projects


def test_session_records_new_and_open(tmp_path: Path) -> None:
    recent_file = tmp_path / "cfg" / "recent.json"
    projects = _projects(tmp_path)
    first = Session(recent_path=recent_file)
    created = first.new_project(str(projects), "Rack One")
    first.new_project(str(projects), "Rack Two")
    assert [i.name for i in first.recent()] == ["Rack Two", "Rack One"]
    assert all(i.exists for i in first.recent())

    second = Session(recent_path=recent_file)
    second.open_project(created.folder)
    assert [i.name for i in second.recent()] == ["Rack One", "Rack Two"]
    assert json.loads(recent_file.read_text(encoding="utf-8"))["version"] == 1


def test_session_marks_missing_folder(tmp_path: Path) -> None:
    session = Session(recent_path=tmp_path / "recent.json")
    created = session.new_project(str(_projects(tmp_path)), "Rack")
    (Path(created.folder) / "project.json").unlink()
    items = session.recent()
    assert len(items) == 1
    assert items[0].exists is False


def test_session_forget_recent(tmp_path: Path) -> None:
    session = Session(recent_path=tmp_path / "recent.json")
    created = session.new_project(str(_projects(tmp_path)), "Rack")
    session.forget_recent(created.folder)
    assert session.recent() == []


def test_session_without_recent_path_records_nothing(tmp_path: Path) -> None:
    session = Session()
    session.new_project(str(_projects(tmp_path)), "Rack")
    assert session.recent() == []
    session.forget_recent("anything")  # no-op, no error


def test_recent_endpoints(tmp_path: Path) -> None:
    session = Session(recent_path=tmp_path / "recent.json")
    client = TestClient(create_app(static_dir=NO_FRONTEND, session=session))
    assert client.get("/api/recent").json() == []
    created = client.post(
        "/api/project/new", json={"name": "Rack", "parent": str(_projects(tmp_path))}
    ).json()
    listed = client.get("/api/recent").json()
    assert [i["name"] for i in listed] == ["Rack"]
    assert listed[0]["exists"] is True
    after = client.post("/api/recent/remove", json={"folder": created["folder"]})
    assert after.status_code == 200
    assert after.json() == []
