"""Line bank commands (M3-4). Pure: they mutate the in-memory Project only.

Follows the command contract in ``commands.py``: ``apply`` validates first and
raises before changing anything. A command that would change nothing raises
``NoChange`` (a ``CommandError``), so batch callers can skip it without
creating an empty undo step.

Generating takes is not a command (takes persist, rule 1); picking the active
take, starring and editing the line itself are.
"""

from collections.abc import Collection
from typing import Any

from pydantic import ValidationError

from backend.project.commands import Command, CommandError
from backend.project.schema import Line, Project, Take, new_id


class NoChange(CommandError):
    """The command would not change anything. The project is untouched."""


def _find_line(project: Project, line_id: str) -> tuple[int, Line]:
    for index, line in enumerate(project.lines):
        if line.id == line_id:
            return index, line
    raise CommandError(f"unknown line id {line_id!r}")


def _find_take(project: Project, take_id: str) -> Take:
    for take in project.takes:
        if take.id == take_id:
            return take
    raise CommandError(f"unknown take id {take_id!r}")


def _usage(project: Project, line_id: str) -> tuple[int, int]:
    """How many takes and placements use a line."""
    takes = sum(1 for take in project.takes if take.line_id == line_id)
    placed = sum(1 for p in project.placements if p.line_id == line_id)
    return takes, placed


def _first_error(exc: ValidationError) -> str:
    errors = exc.errors()
    return str(errors[0]["msg"]) if errors else str(exc)


def _clean_emotion(emotion: str, known_emotions: Collection[str] | None) -> str:
    cleaned = emotion.strip()
    if not cleaned:
        raise CommandError("emotion must not be empty")
    if known_emotions is not None and cleaned not in known_emotions:
        raise CommandError(f"unknown emotion {cleaned!r}")
    return cleaned


# --------------------------------------------------------------------------
# Adding and removing lines
# --------------------------------------------------------------------------


class AddLine(Command):
    def __init__(
        self,
        text: str = "",
        emotion: str = "neutral",
        *,
        line_id: str | None = None,
        position: int | None = None,
        known_emotions: Collection[str] | None = None,
    ) -> None:
        cleaned = _clean_emotion(emotion, known_emotions)
        try:
            self.line = Line(id=line_id or new_id(), text=text, emotion=cleaned)
        except ValidationError as exc:
            raise CommandError(f"invalid line: {_first_error(exc)}") from exc
        self.position = position

    @property
    def line_id(self) -> str:
        return self.line.id

    @property
    def label(self) -> str:
        return "Add line"

    def apply(self, project: Project) -> None:
        if any(line.id == self.line.id for line in project.lines):
            raise CommandError(f"line id {self.line.id!r} already exists")
        position = len(project.lines) if self.position is None else self.position
        if not 0 <= position <= len(project.lines):
            raise CommandError(f"position {position} is out of range")
        project.lines.insert(position, self.line.model_copy(deep=True))

    def revert(self, project: Project) -> None:
        index, _ = _find_line(project, self.line.id)
        # Takes are generated outside the undo stack (rule 1: never lost), so
        # the line cannot be taken away from under them.
        takes, placed = _usage(project, self.line.id)
        if takes or placed:
            raise CommandError(
                f"cannot undo adding this line: {takes} take(s) and {placed} "
                "placement(s) still use it (delete its takes in the storage "
                "manager first)"
            )
        del project.lines[index]


class RemoveLine(Command):
    """Remove a line that has no takes and no placements.

    A line with takes is deleted through the storage manager instead (explicit
    confirmation, not undoable).
    """

    def __init__(self, line_id: str) -> None:
        self.line_id = line_id
        self._removed: Line | None = None
        self._index = 0

    @property
    def label(self) -> str:
        return "Remove line"

    def apply(self, project: Project) -> None:
        index, line = _find_line(project, self.line_id)
        takes, placed = _usage(project, self.line_id)
        if takes or placed:
            raise CommandError(
                f"cannot remove this line: {takes} take(s) and {placed} placement(s) "
                "still use it (remove the placements, and delete takes in the "
                "storage manager)"
            )
        self._removed = line
        self._index = index
        del project.lines[index]

    def revert(self, project: Project) -> None:
        if self._removed is None:
            raise CommandError("nothing to restore: command was not applied")
        project.lines.insert(self._index, self._removed)


# --------------------------------------------------------------------------
# Editing one field of a line
# --------------------------------------------------------------------------


class _SetLineField(Command):
    _field: str = ""
    _label: str = ""

    def __init__(self, line_id: str, value: Any) -> None:
        self.line_id = line_id
        self.value = value
        self._old: Any = None
        self._applied = False

    @property
    def label(self) -> str:
        return self._label

    def apply(self, project: Project) -> None:
        _, line = _find_line(project, self.line_id)
        old = getattr(line, self._field)
        if old == self.value:
            raise NoChange(f"{self._field} is already {self.value!r}")
        try:
            setattr(line, self._field, self.value)  # validated on assignment
        except ValidationError as exc:
            raise CommandError(
                f"invalid {self._field} {self.value!r}: {_first_error(exc)}"
            ) from exc
        self._old = old
        self._applied = True

    def revert(self, project: Project) -> None:
        if not self._applied:
            raise CommandError("nothing to restore: command was not applied")
        _, line = _find_line(project, self.line_id)
        setattr(line, self._field, self._old)


class SetLineText(_SetLineField):
    _field = "text"
    _label = "Edit line text"

    def __init__(self, line_id: str, text: str) -> None:
        super().__init__(line_id, text)


class SetLineEmotion(_SetLineField):
    _field = "emotion"
    _label = "Set emotion"

    def __init__(
        self,
        line_id: str,
        emotion: str,
        *,
        known_emotions: Collection[str] | None = None,
    ) -> None:
        super().__init__(line_id, _clean_emotion(emotion, known_emotions))


class SetLineExaggeration(_SetLineField):
    """Override the preset's exaggeration; ``None`` goes back to the preset."""

    _field = "exaggeration"
    _label = "Set exaggeration"

    def __init__(self, line_id: str, value: float | None) -> None:
        super().__init__(line_id, value)


class SetLineCfgWeight(_SetLineField):
    """Override the preset's cfg_weight; ``None`` goes back to the preset."""

    _field = "cfg_weight"
    _label = "Set cfg weight"

    def __init__(self, line_id: str, value: float | None) -> None:
        super().__init__(line_id, value)


class SetAllowOverlap(_SetLineField):
    _field = "allow_overlap"
    _label = "Set allow overlap"

    def __init__(self, line_id: str, value: bool) -> None:
        super().__init__(line_id, value)


# --------------------------------------------------------------------------
# Takes
# --------------------------------------------------------------------------


class SetActiveTake(Command):
    """Make one of the line's takes the active one (``None`` clears it)."""

    def __init__(self, line_id: str, take_id: str | None) -> None:
        self.line_id = line_id
        self.take_id = take_id
        self._old: str | None = None
        self._applied = False

    @property
    def label(self) -> str:
        return "Set active take"

    def apply(self, project: Project) -> None:
        _, line = _find_line(project, self.line_id)
        if self.take_id is not None:
            take = _find_take(project, self.take_id)
            if take.line_id != self.line_id:
                raise CommandError("that take belongs to another line")
        if line.active_take_id == self.take_id:
            raise NoChange("that take is already the active take")
        self._old = line.active_take_id
        line.active_take_id = self.take_id
        self._applied = True

    def revert(self, project: Project) -> None:
        if not self._applied:
            raise CommandError("nothing to restore: command was not applied")
        _, line = _find_line(project, self.line_id)
        line.active_take_id = self._old


class StarTake(Command):
    def __init__(self, take_id: str, starred: bool = True) -> None:
        self.take_id = take_id
        self.starred = starred
        self._old: bool | None = None

    @property
    def label(self) -> str:
        return "Star take" if self.starred else "Unstar take"

    def apply(self, project: Project) -> None:
        take = _find_take(project, self.take_id)
        if take.starred == self.starred:
            state = "starred" if take.starred else "not starred"
            raise NoChange(f"the take is already {state}")
        self._old = take.starred
        take.starred = self.starred

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        _find_take(project, self.take_id).starred = self._old
