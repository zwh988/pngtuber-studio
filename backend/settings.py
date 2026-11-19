"""The Settings screen's data (M7 S5, decision 4): paths and the response model.

Settings links to what already has a home (voice reference and art folder on the
project screen, FX presets, takes and avatar motion in the editor) and adds what
had none: emotion preset editing (``backend/voice/userpresets.py``), the open
project's export defaults (``SetExportSettings``, undoable), the keyboard
shortcuts map (frontend) and the paths below, each with "Open folder".
"""

import os
from pathlib import Path

from pydantic import BaseModel

from backend.project.schema import ExportSettings
from backend.voice.userpresets import PresetsState

APP_DATA_NAME = "PNGtuberStudio"


def app_data_dir() -> Path:
    """``%APPDATA%\\PNGtuberStudio`` (recent list, worker log, edited presets)."""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / APP_DATA_NAME


def default_user_templates_dir() -> Path:
    """Where "Save as template" writes (M7 S6)."""
    return app_data_dir() / "templates"


class PathItem(BaseModel):
    key: str
    label: str
    path: str
    exists: bool
    folder: bool  # a folder (opened itself) or a file (its folder is opened)


class AppSettings(BaseModel):
    """``GET /api/settings``."""

    presets: PresetsState | None
    presets_error: str | None = None  # the built-in presets file cannot be read
    tools_problem: str | None = None  # ffmpeg / NVENC, as the export pre-flight says it
    export: ExportSettings | None = None  # the open project's defaults; None without one
    paths: list[PathItem]


def path_items(entries: list[tuple[str, str, Path, bool]]) -> list[PathItem]:
    """``(key, label, path, is_folder)`` to items, with whether each exists."""
    items: list[PathItem] = []
    for key, label, path, is_folder in entries:
        try:
            exists = path.is_dir() if is_folder else path.is_file()
        except OSError:
            exists = False
        items.append(PathItem(key=key, label=label, path=str(path), exists=exists, folder=is_folder))
    return items


def folder_to_open(item: PathItem) -> Path:
    path = Path(item.path)
    return path if item.folder else path.parent
