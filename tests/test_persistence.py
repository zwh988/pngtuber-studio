import json
import os
from pathlib import Path
from typing import Any

import pytest

from backend.project import store
from backend.project.autosave import AutosavePolicy, AutosaveTracker
from backend.project.migrations import (
    MigrationError,
    ProjectTooNewError,
    migrate,
)
from backend.project.schema import SCHEMA_VERSION, Line, Project, new_id
from backend.project.store import (
    LAYOUT_DIRS,
    ProjectExistsError,
    ProjectLoadError,
    backup_file,
    create_project,
    load_project,
    project_file,
    save_project,
)

# ---- migrations -------------------------------------------------------------


def test_migrate_noop_at_current_version() -> None:
    data = {"schema_version": SCHEMA_VERSION, "name": "x"}
    assert migrate(data) == data


def test_migration_chain_runs_in_order() -> None:
    calls: list[int] = []

    def v1_to_v2(d: dict[str, Any]) -> dict[str, Any]:
        calls.append(1)
        d["trail"] = [*d.get("trail", []), "1->2"]
        return d

    def v2_to_v3(d: dict[str, Any]) -> dict[str, Any]:
        calls.append(2)
        d["trail"] = [*d.get("trail", []), "2->3"]
        return d

    data = {"schema_version": 1, "name": "x"}
    out = migrate(data, target=3, migrations={1: v1_to_v2, 2: v2_to_v3})
    assert calls == [1, 2]
    assert out["trail"] == ["1->2", "2->3"]
    assert out["schema_version"] == 3
    assert data == {"schema_version": 1, "name": "x"}  # input not mutated


def test_migrate_starts_from_stored_version() -> None:
    out = migrate(
        {"schema_version": 2},
        target=3,
        migrations={2: lambda d: {**d, "ran": True}},
    )
    assert out == {"schema_version": 3, "ran": True}


def test_migrate_missing_step_raises() -> None:
    with pytest.raises(MigrationError):
        migrate({"schema_version": 1}, target=2, migrations={})


def test_migrate_too_new_raises() -> None:
    with pytest.raises(ProjectTooNewError):
        migrate({"schema_version": 5}, target=2, migrations={})


@pytest.mark.parametrize("bad", [None, 0, -1, "1", True])
def test_migrate_invalid_version_raises(bad: object) -> None:
    with pytest.raises(MigrationError):
        migrate({"schema_version": bad})
    with pytest.raises(MigrationError):
        migrate({})


# ---- autosave tracker --------------------------------------------------------


def make_tracker() -> AutosaveTracker:
    return AutosaveTracker(AutosavePolicy(debounce_s=2.0, max_wait_s=10.0))


def test_clean_tracker_never_due() -> None:
    t = make_tracker()
    assert not t.dirty
    assert t.due_at() is None
    assert t.should_save(1000.0) is False
    assert t.seconds_until_due(0.0) is None


def test_debounce_after_single_change() -> None:
    t = make_tracker()
    t.mark_dirty(100.0)
    assert t.should_save(101.9) is False
    assert t.should_save(102.0) is True
    assert t.seconds_until_due(101.0) == pytest.approx(1.0)


def test_continuous_edits_extend_debounce() -> None:
    t = make_tracker()
    for now in (100.0, 101.0, 102.0, 103.0):
        t.mark_dirty(now)
    assert t.due_at() == pytest.approx(105.0)


def test_max_wait_caps_continuous_edits() -> None:
    t = make_tracker()
    now = 100.0
    while now <= 112.0:
        t.mark_dirty(now)
        now += 1.0
    assert t.due_at() == pytest.approx(110.0)  # first change + max wait
    assert t.should_save(110.0) is True


def test_finish_save_clears_dirty() -> None:
    t = make_tracker()
    t.mark_dirty(100.0)
    token = t.begin_save()
    t.finish_save(token)
    assert not t.dirty
    assert t.due_at() is None


def test_changes_during_save_stay_dirty() -> None:
    t = make_tracker()
    t.mark_dirty(100.0)
    token = t.begin_save()
    t.mark_dirty(100.5)  # edit lands while the save is running
    t.finish_save(token)
    assert t.dirty
    assert t.due_at() == pytest.approx(102.5)


def test_failed_save_stays_dirty() -> None:
    t = make_tracker()
    t.mark_dirty(100.0)
    t.begin_save()  # save fails: finish_save is never called
    assert t.dirty
    assert t.should_save(102.0) is True


# ---- store -------------------------------------------------------------------


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    # A path with spaces, as users have on Windows.
    return tmp_path / "My Rack Project"


def sample_project(name: str = "My Rack") -> Project:
    return Project(name=name, lines=[Line(id=new_id(), text="Nice break.")])


def test_create_makes_layout_and_valid_file(folder: Path) -> None:
    project = sample_project()
    create_project(folder, project)
    for rel in LAYOUT_DIRS:
        assert (folder / rel).is_dir()
    assert project_file(folder).is_file()
    data = json.loads(project_file(folder).read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION
    assert isinstance(data["seed"], int)


def test_create_refuses_existing_project(folder: Path) -> None:
    create_project(folder, sample_project())
    with pytest.raises(ProjectExistsError):
        create_project(folder, sample_project("other"))


def test_round_trip(folder: Path) -> None:
    project = sample_project()
    create_project(folder, project)
    assert load_project(folder) == project


def test_save_then_load_reflects_changes(folder: Path) -> None:
    project = sample_project()
    create_project(folder, project)
    project.name = "Renamed"
    save_project(folder, project)
    assert load_project(folder).name == "Renamed"


def test_no_temp_files_left_after_save(folder: Path) -> None:
    create_project(folder, sample_project())
    save_project(folder, sample_project())
    names = {p.name for p in folder.iterdir() if p.is_file()}
    assert names <= {"project.json", "project.json.bak"}


def test_backup_rotates(folder: Path) -> None:
    project = sample_project("v1")
    create_project(folder, project)
    assert not backup_file(folder).exists()  # first save has nothing to back up

    project.name = "v2"
    save_project(folder, project)
    assert json.loads(backup_file(folder).read_text(encoding="utf-8"))["name"] == "v1"

    project.name = "v3"
    save_project(folder, project)
    assert json.loads(backup_file(folder).read_text(encoding="utf-8"))["name"] == "v2"
    assert load_project(folder).name == "v3"


def test_failed_replace_keeps_old_file(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = sample_project("original")
    create_project(folder, project)
    before = project_file(folder).read_text(encoding="utf-8")

    real_replace = os.replace

    def flaky_replace(src: Any, dst: Any) -> None:
        if Path(dst).name == "project.json":
            raise OSError("simulated crash during replace")
        real_replace(src, dst)

    monkeypatch.setattr(store.os, "replace", flaky_replace)
    project.name = "should not land"
    with pytest.raises(OSError):
        save_project(folder, project)
    monkeypatch.undo()

    assert project_file(folder).read_text(encoding="utf-8") == before
    assert load_project(folder).name == "original"
    assert not (folder / "project.json.tmp").exists()


def test_failed_write_keeps_old_file(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_project(folder, sample_project("original"))
    before = project_file(folder).read_text(encoding="utf-8")

    def boom(_fd: int) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(store.os, "fsync", boom)
    with pytest.raises(OSError):
        save_project(folder, sample_project("new"))
    monkeypatch.undo()

    assert project_file(folder).read_text(encoding="utf-8") == before
    assert not (folder / "project.json.tmp").exists()


def test_corrupt_file_does_not_overwrite_good_backup(folder: Path) -> None:
    project = sample_project("good")
    create_project(folder, project)
    project.name = "good2"
    save_project(folder, project)  # .bak now holds "good"

    project_file(folder).write_text("{ not json", encoding="utf-8")
    project.name = "good3"
    save_project(folder, project)

    assert json.loads(backup_file(folder).read_text(encoding="utf-8"))["name"] == "good"
    assert load_project(folder).name == "good3"


def test_load_from_backup(folder: Path) -> None:
    project = sample_project("v1")
    create_project(folder, project)
    project.name = "v2"
    save_project(folder, project)
    project_file(folder).write_text("garbage", encoding="utf-8")

    with pytest.raises(ProjectLoadError):
        load_project(folder)
    assert load_project(folder, use_backup=True).name == "v1"


def test_load_errors(folder: Path) -> None:
    folder.mkdir(parents=True)
    with pytest.raises(ProjectLoadError):  # missing
        load_project(folder)

    project_file(folder).write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ProjectLoadError):  # not an object
        load_project(folder)

    project_file(folder).write_text('{"schema_version": 1}', encoding="utf-8")
    with pytest.raises(ProjectLoadError):  # fails validation (no name)
        load_project(folder)

    project_file(folder).write_text(
        '{"schema_version": 99, "name": "x"}', encoding="utf-8"
    )
    with pytest.raises(ProjectLoadError, match="newer"):  # too new
        load_project(folder)
