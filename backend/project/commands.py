"""Command layer and undo/redo stack (M1-4).

Every edit to a Project goes through a ``Command`` executed on a
``CommandStack`` (CLAUDE.md rule 11). This module is pure: it mutates the
in-memory ``Project`` only and does no file or network I/O. Saving is the
caller's job (use ``on_change`` to mark the autosave tracker dirty).

Command contract:
- ``apply`` validates first and raises ``CommandError`` *before* changing
  anything, so a failed command leaves the project untouched.
- ``apply`` records whatever it needs to undo itself; ``revert`` restores the
  state from before ``apply``. ``apply`` may be called again after ``revert``
  (that is how redo works).
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from pydantic import ValidationError

from backend.project.schema import Project, Source


class CommandError(Exception):
    """A command could not be applied (or reverted). Project state is unchanged
    when raised from ``apply``."""


class Command(ABC):
    @property
    @abstractmethod
    def label(self) -> str:
        """Short human-readable description (for Undo/Redo menu text)."""

    @abstractmethod
    def apply(self, project: Project) -> None: ...

    @abstractmethod
    def revert(self, project: Project) -> None: ...


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _find_source(project: Project, source_id: str) -> tuple[int, Source]:
    for index, source in enumerate(project.sources):
        if source.id == source_id:
            return index, source
    raise CommandError(f"unknown source id {source_id!r}")


def _path_taken(project: Project, path: str, *, except_id: str | None = None) -> bool:
    key = path.casefold()
    return any(
        s.path.casefold() == key and s.id != except_id for s in project.sources
    )


# --------------------------------------------------------------------------
# Commands needed by M1
# --------------------------------------------------------------------------


class AddSource(Command):
    def __init__(self, source: Source) -> None:
        self.source = source

    @property
    def label(self) -> str:
        return f"Add footage {self.source.path}"

    def apply(self, project: Project) -> None:
        if any(s.id == self.source.id for s in project.sources):
            raise CommandError(f"source id {self.source.id!r} already exists")
        if _path_taken(project, self.source.path):
            raise CommandError(f"footage {self.source.path!r} is already in the project")
        # Copy so later edits to the project never alias the command's object.
        project.sources.append(self.source.model_copy(deep=True))

    def revert(self, project: Project) -> None:
        index, _ = _find_source(project, self.source.id)
        del project.sources[index]


class RemoveSource(Command):
    """Remove a source. Refused while any clip still uses it."""

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id
        self._removed: Source | None = None
        self._index = 0

    @property
    def label(self) -> str:
        return "Remove footage"

    def apply(self, project: Project) -> None:
        index, source = _find_source(project, self.source_id)
        used = sum(1 for clip in project.clips if clip.source_id == self.source_id)
        if used:
            raise CommandError(
                f"cannot remove {source.path!r}: {used} clip(s) still use it"
            )
        self._removed = source
        self._index = index
        del project.sources[index]

    def revert(self, project: Project) -> None:
        if self._removed is None:
            raise CommandError("nothing to restore: command was not applied")
        project.sources.insert(self._index, self._removed)


class RenameProject(Command):
    def __init__(self, name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise CommandError("project name must not be empty")
        self.new_name = cleaned
        self._old_name: str | None = None

    @property
    def label(self) -> str:
        return "Rename project"

    def apply(self, project: Project) -> None:
        self._old_name = project.name
        project.name = self.new_name

    def revert(self, project: Project) -> None:
        if self._old_name is None:
            raise CommandError("nothing to restore: command was not applied")
        project.name = self._old_name


class RelinkSource(Command):
    """Point an existing source at a new (relative POSIX) path.

    Only the path changes; metadata is not re-probed. Used when footage was
    moved or renamed (project screen, relink).
    """

    def __init__(self, source_id: str, new_path: str) -> None:
        self.source_id = source_id
        self.new_path = new_path
        self._old_path: str | None = None

    @property
    def label(self) -> str:
        return "Relink footage"

    def apply(self, project: Project) -> None:
        _, source = _find_source(project, self.source_id)
        if _path_taken(project, self.new_path, except_id=self.source_id):
            raise CommandError(f"footage {self.new_path!r} is already in the project")
        old = source.path
        try:
            source.path = self.new_path  # validated on assignment
        except ValidationError as exc:
            raise CommandError(f"invalid path {self.new_path!r}: {exc}") from exc
        self._old_path = old

    def revert(self, project: Project) -> None:
        if self._old_path is None:
            raise CommandError("nothing to restore: command was not applied")
        _, source = _find_source(project, self.source_id)
        source.path = self._old_path


# --------------------------------------------------------------------------
# Undo/redo stack
# --------------------------------------------------------------------------


@dataclass
class _Entry:
    label: str
    commands: list[Command]


class CommandStack:
    """Executes commands against one Project and tracks undo/redo.

    A group (``with stack.group("label"):``) collects every command executed
    inside it into one undo step. If the block raises, the commands already
    applied are reverted, nothing is recorded, and the redo stack is restored.
    Nested groups merge into the outermost one. Undo/redo are not allowed
    while a group is open. If a revert (or a redo's apply) raises
    ``CommandError``, the commands already done are undone again, the step
    stays where it was and the error is re-raised.
    """

    def __init__(
        self,
        project: Project,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self._project = project
        self._on_change = on_change
        self._undo: list[_Entry] = []
        self._redo: list[_Entry] = []
        self._group_depth = 0
        self._group_label = ""
        self._group_commands: list[Command] = []
        self._saved_redo: list[_Entry] = []

    # ---- inspection -------------------------------------------------------

    @property
    def project(self) -> Project:
        return self._project

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str | None:
        return self._undo[-1].label if self._undo else None

    @property
    def redo_label(self) -> str | None:
        return self._redo[-1].label if self._redo else None

    @property
    def in_group(self) -> bool:
        return self._group_depth > 0

    # ---- operations -------------------------------------------------------

    def execute(self, command: Command) -> None:
        """Apply a command and record it. Raises ``CommandError`` (project
        unchanged) if it cannot be applied; nothing is recorded then."""
        command.apply(self._project)
        self._redo.clear()
        if self._group_depth > 0:
            self._group_commands.append(command)
            return
        self._undo.append(_Entry(command.label, [command]))
        self._notify()

    @contextmanager
    def group(self, label: str) -> Iterator[None]:
        outermost = self._group_depth == 0
        if outermost:
            self._group_label = label
            self._group_commands = []
            self._saved_redo = list(self._redo)
        self._group_depth += 1
        try:
            yield
        except BaseException:
            self._group_depth -= 1
            if outermost:
                self._rollback_group()
            raise
        else:
            self._group_depth -= 1
            if outermost:
                self._commit_group()

    def undo(self) -> str | None:
        """Undo the latest step. Returns its label, or None if nothing to undo."""
        self._require_no_group()
        if not self._undo:
            return None
        entry = self._undo[-1]
        done: list[Command] = []
        try:
            for command in reversed(entry.commands):
                command.revert(self._project)
                done.append(command)
        except CommandError:
            for command in reversed(done):
                command.apply(self._project)
            raise
        self._undo.pop()
        self._redo.append(entry)
        self._notify()
        return entry.label

    def redo(self) -> str | None:
        """Redo the latest undone step. Returns its label, or None."""
        self._require_no_group()
        if not self._redo:
            return None
        entry = self._redo[-1]
        done: list[Command] = []
        try:
            for command in entry.commands:
                command.apply(self._project)
                done.append(command)
        except CommandError:
            for command in reversed(done):
                command.revert(self._project)
            raise
        self._redo.pop()
        self._undo.append(entry)
        self._notify()
        return entry.label

    def clear(self) -> None:
        """Forget all history (for example after loading a different project)."""
        self._require_no_group()
        self._undo.clear()
        self._redo.clear()

    # ---- internals --------------------------------------------------------

    def _commit_group(self) -> None:
        commands = self._group_commands
        self._group_commands = []
        self._saved_redo = []
        if not commands:
            return
        self._undo.append(_Entry(self._group_label, commands))
        self._notify()

    def _rollback_group(self) -> None:
        for command in reversed(self._group_commands):
            command.revert(self._project)
        self._group_commands = []
        self._redo = self._saved_redo
        self._saved_redo = []

    def _require_no_group(self) -> None:
        if self._group_depth > 0:
            raise CommandError("cannot undo, redo or clear while a group is open")

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change()
