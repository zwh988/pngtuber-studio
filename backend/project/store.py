"""Project folder I/O: layout, create, load, atomic save with rotating backup.

Thin I/O wrapper around the pure schema and migrations modules.
"""

import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from backend.project.migrations import Migration, MigrationError, migrate
from backend.project.schema import Project

PROJECT_FILE = "project.json"
BACKUP_FILE = "project.json.bak"
TEMP_FILE = "project.json.tmp"

# Subfolders created for every project (spec section 5).
LAYOUT_DIRS = (
    "footage",
    "media/voice",
    "media/takes_raw",
    "media/takes_fx",
    "media/envelopes",
    "exports",
)


class ProjectError(Exception):
    """Base class for project store errors."""


class ProjectExistsError(ProjectError):
    """A project already exists in the target folder."""


class ProjectLoadError(ProjectError):
    """project.json is missing, unreadable, invalid, or too new."""


def project_file(folder: Path) -> Path:
    return folder / PROJECT_FILE


def backup_file(folder: Path) -> Path:
    return folder / BACKUP_FILE


def ensure_layout(folder: Path) -> None:
    """Create the project folder and its standard subfolders (idempotent)."""
    for rel in LAYOUT_DIRS:
        (folder / rel).mkdir(parents=True, exist_ok=True)


def create_project(folder: Path, project: Project) -> None:
    """Create the folder layout and write the first ``project.json``."""
    folder = Path(folder)
    if project_file(folder).exists():
        raise ProjectExistsError(f"a project already exists in {folder}")
    ensure_layout(folder)
    save_project(folder, project)


def load_project(
    folder: Path,
    *,
    use_backup: bool = False,
    migrations: Mapping[int, Migration] | None = None,
) -> Project:
    """Load, migrate, and validate a project.

    With ``use_backup=True`` the ``.bak`` file is read instead (for recovery
    when ``project.json`` is damaged). Raises ``ProjectLoadError`` on any failure.
    """
    folder = Path(folder)
    path = backup_file(folder) if use_backup else project_file(folder)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ProjectLoadError(f"{path.name} not found in {folder}") from exc
    except OSError as exc:
        raise ProjectLoadError(f"cannot read {path}: {exc}") from exc

    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectLoadError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ProjectLoadError(f"{path.name} does not contain a JSON object")

    try:
        data = migrate(data, migrations=migrations)
        return Project.model_validate(data)
    except MigrationError as exc:
        raise ProjectLoadError(str(exc)) from exc
    except ValidationError as exc:
        raise ProjectLoadError(f"{path.name} failed validation: {exc}") from exc


def _is_valid_json_file(path: Path) -> bool:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return True


def save_project(folder: Path, project: Project) -> None:
    """Atomically write ``project.json`` and rotate the previous one to ``.bak``.

    Order: write a temp file in the same folder (flushed and fsynced), copy the
    current ``project.json`` to ``.bak`` (only if it is valid JSON, so a corrupt
    file never overwrites a good backup), then ``os.replace`` the temp file over
    ``project.json``. A failure at any point leaves the old ``project.json``.
    """
    folder = Path(folder)
    target = project_file(folder)
    tmp = folder / TEMP_FILE
    text = project.model_dump_json(indent=2)

    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())

        if target.exists() and _is_valid_json_file(target):
            bak = backup_file(folder)
            bak_tmp = folder / (BACKUP_FILE + ".tmp")
            shutil.copyfile(target, bak_tmp)
            os.replace(bak_tmp, bak)

        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        (folder / (BACKUP_FILE + ".tmp")).unlink(missing_ok=True)
        raise
