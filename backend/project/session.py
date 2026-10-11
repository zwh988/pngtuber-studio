"""The one project the app currently has open (M1-6).

``clean_folder_name`` is pure. ``Session`` does file I/O through ``store`` and
optionally runs ffprobe for template bookend clips (the probe is injectable).
"""

import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.project.commands import CommandStack
from backend.project.footage import parse_probe, run_ffprobe
from backend.project.schema import Source
from backend.project.store import create_project, load_project, project_file
from backend.project.summary import ProjectSummary, summarize
from backend.project.template import (
    apply_template,
    external_source,
    load_template_file,
)

Probe = Callable[[Path], dict[str, Any]]

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class SessionError(Exception):
    """A user-facing problem creating or opening a project."""


def clean_folder_name(name: str) -> str:
    """Validate a project name that is also used as a Windows folder name."""
    text = name.strip()
    if not text:
        raise ValueError("project name must not be empty")
    if _BAD_CHARS.search(text):
        raise ValueError('project name must not contain < > : " / \\ | ? *')
    if text.endswith("."):
        raise ValueError("project name must not end with a dot")
    if text.split(".")[0].upper() in _RESERVED:
        raise ValueError(f"'{text}' is a reserved Windows name")
    return text


class Session:
    def __init__(
        self,
        *,
        template_path: Path | None = None,
        probe: Probe | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._template_path = template_path
        self._probe: Probe = probe if probe is not None else run_ffprobe
        self._folder: Path | None = None
        self._stack: CommandStack | None = None

    def current(self) -> ProjectSummary | None:
        with self._lock:
            if self._folder is None or self._stack is None:
                return None
            return summarize(str(self._folder), self._stack.project)

    def new_project(self, parent: str, name: str) -> ProjectSummary:
        try:
            clean = clean_folder_name(name)
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        parent_path = Path(parent.strip())
        if not parent.strip() or not parent_path.is_dir():
            raise SessionError(f"parent folder does not exist: {parent_path}")
        folder = parent_path / clean
        if project_file(folder).exists():
            raise SessionError(f"a project already exists in {folder}")

        template = load_template_file(self._template_path)
        intro = self._probe_bookend(template.intro.path) if template.intro else None
        outro = self._probe_bookend(template.outro.path) if template.outro else None
        project = apply_template(
            template, clean, intro_source=intro, outro_source=outro
        )

        with self._lock:
            folder.mkdir(exist_ok=True)
            create_project(folder, project)
            return self._set_open(folder, project)

    def open_project(self, folder: str) -> ProjectSummary:
        folder_path = Path(folder.strip())
        if not folder.strip() or not project_file(folder_path).is_file():
            raise SessionError(f"no project.json found in {folder_path}")
        project = load_project(folder_path)
        with self._lock:
            return self._set_open(folder_path, project)

    def _set_open(self, folder: Path, project: Any) -> ProjectSummary:
        self._folder = folder
        self._stack = CommandStack(project)
        return summarize(str(folder), project)

    def _probe_bookend(self, raw_path: str) -> Source:
        data = self._probe(Path(raw_path))
        # The placeholder relative path is replaced by external_source.
        return external_source(parse_probe(data, "bookend.mkv"), raw_path)
