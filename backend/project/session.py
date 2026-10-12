"""The one project the app currently has open (M1-6).

``clean_folder_name`` is pure. ``Session`` does file I/O through ``store`` and
runs ffprobe (injectable) for footage and template bookend clips. Every
change made through the command stack is saved straight away (``on_change``).
Pass ``recent_path`` to record opened projects; ``None`` records nothing.
"""

import re
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.edl.anchoring import check_references
from backend.project.clip_commands import AddClip
from backend.project.commands import (
    AddSource,
    CommandError,
    CommandStack,
    RelinkSource,
)
from backend.project.edit_ops import EditOp, build_command
from backend.project.footage import (
    FootageError,
    parse_probe,
    run_ffprobe,
    scan_footage,
)
from backend.project.recent import (
    RecentItem,
    add_recent,
    load_recent,
    remove_recent,
    save_recent,
)
from backend.project.relink import relink_mismatches, to_footage_relpath
from backend.project.schema import Project, Source
from backend.project.store import (
    ProjectError,
    create_project,
    load_project,
    project_file,
    save_project,
)
from backend.project.summary import (
    FootageReport,
    ProjectSummary,
    describe_source,
    summarize,
)
from backend.project.template import (
    apply_template,
    external_source,
    load_template_file,
)
from backend.project.timeline import EditResult, TimelineState, build_timeline

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
        recent_path: Path | None = None,
    ) -> None:
        # Re-entrant: the stack's on_change callback runs while a command
        # method already holds the lock.
        self._lock = threading.RLock()
        self._template_path = template_path
        self._probe: Probe = probe if probe is not None else run_ffprobe
        self._recent_path = recent_path
        self._folder: Path | None = None
        self._stack: CommandStack | None = None
        self._save_error: str | None = None
        self._scan_errors: list[str] = []

    # ---- project lifecycle -------------------------------------------------

    def current(self) -> ProjectSummary | None:
        with self._lock:
            if self._folder is None or self._stack is None:
                return None
            return self._summary()

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

    # ---- footage -----------------------------------------------------------

    def footage(self) -> FootageReport:
        with self._lock:
            folder, stack = self._require_open()
            return self._report(folder, stack.project, added=0)

    def rescan_footage(self) -> FootageReport:
        with self._lock:
            folder, stack = self._require_open()
            added = self._scan(folder, stack)
            return self._report(folder, stack.project, added=added)

    def relink_source(self, source_id: str, new_path: str) -> FootageReport:
        """Point a footage source at a moved file, after checking it matches."""
        with self._lock:
            folder, stack = self._require_open()
            source = next(
                (s for s in stack.project.sources if s.id == source_id), None
            )
            if source is None:
                raise SessionError("unknown footage source")
            if source.external:
                raise SessionError(
                    "relinking template bookend clips is not supported yet"
                )
            picked = Path(new_path.strip())
            if not picked.is_file():
                raise SessionError(f"file not found: {picked}")
            try:
                rel = to_footage_relpath(folder.resolve(), picked.resolve())
            except ValueError as exc:
                raise SessionError(str(exc)) from exc
            if rel.casefold() == source.path.casefold():
                return self._report(folder, stack.project, added=0)

            probed = parse_probe(self._probe(picked), rel)
            problems = relink_mismatches(source, probed)
            if problems:
                raise SessionError(
                    "that file does not match the original footage: "
                    + "; ".join(problems)
                )
            try:
                stack.execute(RelinkSource(source.id, rel))
            except CommandError as exc:
                raise SessionError(str(exc)) from exc
            return self._report(folder, stack.project, added=0)

    # ---- media -------------------------------------------------------------

    def source_path(self, source_id: str) -> Path | None:
        """Disk path of a source of the open project, for the media endpoint.

        None when no project is open or the id is not one of its sources. The
        path comes only from the project's source list, never from the browser.
        """
        with self._lock:
            if self._folder is None or self._stack is None:
                return None
            source = next(
                (s for s in self._stack.project.sources if s.id == source_id), None
            )
            if source is None:
                return None
            return Path(source.path) if source.external else self._folder / source.path

    # ---- timeline ----------------------------------------------------------

    def timeline(self) -> TimelineState:
        with self._lock:
            return self._timeline_state()

    def add_clip(self, source_id: str, position: int | None = None) -> TimelineState:
        """Put a whole source on the timeline (before a trailing bookend)."""
        with self._lock:
            _, stack = self._require_open()
            try:
                stack.execute(AddClip(source_id, position=position))
            except CommandError as exc:
                raise SessionError(str(exc)) from exc
            return self._timeline_state()

    def undo(self) -> EditResult:
        with self._lock:
            _, stack = self._require_open()
            try:
                label = stack.undo()
            except CommandError as exc:
                raise SessionError(str(exc)) from exc
            return EditResult(label=label, timeline=self._timeline_state())

    def redo(self) -> EditResult:
        with self._lock:
            _, stack = self._require_open()
            try:
                label = stack.redo()
            except CommandError as exc:
                raise SessionError(str(exc)) from exc
            return EditResult(label=label, timeline=self._timeline_state())

    def edit(self, ops: Sequence[EditOp], label: str | None = None) -> TimelineState:
        """Apply edit ops. One op without a label is a plain undo step; several
        ops (or a label) run as one group, so they undo together and either
        all apply or none do."""
        if not ops:
            raise SessionError("no edits given")
        with self._lock:
            _, stack = self._require_open()
            try:
                if len(ops) == 1 and label is None:
                    stack.execute(build_command(ops[0]))
                else:
                    with stack.group(label or "Edit"):
                        for op in ops:
                            stack.execute(build_command(op))
            except (CommandError, ValueError) as exc:
                raise SessionError(str(exc)) from exc
            return self._timeline_state()

    # ---- recent projects ---------------------------------------------------

    def recent(self) -> list[RecentItem]:
        if self._recent_path is None:
            return []
        return [
            RecentItem(
                **entry.model_dump(),
                exists=project_file(Path(entry.folder)).is_file(),
            )
            for entry in load_recent(self._recent_path)
        ]

    def forget_recent(self, folder: str) -> None:
        if self._recent_path is None:
            return
        with self._lock:
            entries = load_recent(self._recent_path)
            save_recent(self._recent_path, remove_recent(entries, folder))

    # ---- internals ---------------------------------------------------------

    def _require_open(self) -> tuple[Path, CommandStack]:
        if self._folder is None or self._stack is None:
            raise SessionError("no project is open")
        return self._folder, self._stack

    def _timeline_state(self) -> TimelineState:
        folder, stack = self._require_open()
        missing = {
            source.id
            for source in stack.project.sources
            if not self._source_exists(folder, source)
        }
        state = build_timeline(
            stack.project,
            can_undo=stack.can_undo,
            can_redo=stack.can_redo,
            undo_label=stack.undo_label,
            redo_label=stack.redo_label,
            missing_source_ids=missing,
        )
        return state.model_copy(update={"save_error": self._save_error})

    def _summary(self) -> ProjectSummary:
        folder, stack = self._require_open()
        summary = summarize(str(folder), stack.project)
        return summary.model_copy(
            update={
                "save_error": self._save_error,
                "problem_count": len(check_references(stack.project)),
            }
        )

    def _set_open(self, folder: Path, project: Project) -> ProjectSummary:
        self._folder = folder
        self._save_error = None
        self._scan_errors = []
        self._stack = CommandStack(project, on_change=self._on_change)
        self._record_recent(folder, project)
        # Opening must never fail because of footage trouble (for example a
        # missing ffprobe); problems are reported in the footage report.
        try:
            self._scan(folder, self._stack)
        except (FootageError, SessionError) as exc:
            self._scan_errors = [str(exc)]
        # Footage found on open is not an edit the user should be able to undo.
        self._stack.clear()
        return self._summary()

    def _on_change(self, *_args: object) -> None:
        """Save right after every change (debounce comes later with M2)."""
        if self._folder is None or self._stack is None:
            return
        try:
            save_project(self._folder, self._stack.project)
        except (ProjectError, OSError) as exc:
            self._save_error = str(exc)
        else:
            self._save_error = None

    def _scan(self, folder: Path, stack: CommandStack) -> int:
        result = scan_footage(folder, list(stack.project.sources), probe=self._probe)
        self._scan_errors = [f"{rel}: {message}" for rel, message in result.errors]
        if not result.new_sources:
            return 0
        try:
            with stack.group("Add footage"):
                for source in result.new_sources:
                    stack.execute(AddSource(source))
        except CommandError as exc:
            raise SessionError(str(exc)) from exc
        return len(result.new_sources)

    def _report(self, folder: Path, project: Project, added: int) -> FootageReport:
        return FootageReport(
            items=[
                describe_source(source, self._source_exists(folder, source))
                for source in project.sources
            ],
            added=added,
            errors=list(self._scan_errors),
        )

    @staticmethod
    def _source_exists(folder: Path, source: Source) -> bool:
        path = Path(source.path) if source.external else folder / source.path
        return path.is_file()

    def _record_recent(self, folder: Path, project: Project) -> None:
        if self._recent_path is None:
            return
        opened_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            entries = load_recent(self._recent_path)
            save_recent(
                self._recent_path,
                add_recent(entries, project.name, str(folder), opened_at),
            )
        except OSError:
            # A failure to write the recent list must never block opening.
            return

    def _probe_bookend(self, raw_path: str) -> Source:
        data = self._probe(Path(raw_path))
        # The placeholder relative path is replaced by external_source.
        return external_source(parse_probe(data, "bookend.mkv"), raw_path)
