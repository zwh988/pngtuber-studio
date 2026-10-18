"""Placement commands (M3-7): put a generated line on the footage.

Pure: they change the in-memory ``Project`` only. A placement is anchored to
footage (CLAUDE.md rule 4): the commands take a *timeline* time, turn it into an
anchor (clip id plus source time) with ``timemap.to_source``, and store only the
anchor. The anchor is worked out on the first ``apply`` and reused by redo, so a
redo always lands on the same footage moment.

Command contract: ``apply`` validates first and raises ``CommandError`` before it
changes anything; ``revert`` restores the state from before ``apply``.
"""

from backend.edl.timemap import to_source
from backend.project.commands import Command, CommandError
from backend.project.schema import Anchor, Line, Placement, Project, new_id


def _find_line(project: Project, line_id: str) -> Line:
    for line in project.lines:
        if line.id == line_id:
            return line
    raise CommandError(f"unknown line id {line_id!r}")


def _find_placement(project: Project, placement_id: str) -> tuple[int, Placement]:
    for index, placement in enumerate(project.placements):
        if placement.id == placement_id:
            return index, placement
    raise CommandError(f"unknown placement id {placement_id!r}")


def _anchor_at(project: Project, timeline_ms: int) -> Anchor:
    anchor = to_source(project.clips, timeline_ms)
    if anchor is None:
        raise CommandError(f"there is no footage at {timeline_ms} ms on the timeline")
    return anchor


def _check_time(timeline_ms: int) -> None:
    if timeline_ms < 0:
        raise CommandError("timeline time must not be negative")


class AddPlacement(Command):
    """Place a line at a timeline time. The line needs an active take."""

    def __init__(
        self, line_id: str, timeline_ms: int, *, placement_id: str | None = None
    ) -> None:
        _check_time(timeline_ms)
        self.line_id = line_id
        self.timeline_ms = timeline_ms
        self.placement_id = placement_id if placement_id is not None else new_id()
        self._anchor: Anchor | None = None

    @property
    def label(self) -> str:
        return "Place line"

    def apply(self, project: Project) -> None:
        line = _find_line(project, self.line_id)
        if line.active_take_id is None:
            raise CommandError("generate the line first: it has no take yet")
        if any(p.id == self.placement_id for p in project.placements):
            raise CommandError(f"placement id {self.placement_id!r} already exists")
        anchor = self._anchor
        if anchor is None:
            anchor = _anchor_at(project, self.timeline_ms)
        # Built before the append, so an invalid id raises with nothing changed.
        placement = Placement(
            id=self.placement_id, line_id=self.line_id, anchor=anchor.model_copy()
        )
        project.placements.append(placement)
        self._anchor = anchor

    def revert(self, project: Project) -> None:
        index, _ = _find_placement(project, self.placement_id)
        del project.placements[index]


class RemovePlacement(Command):
    """Take a placement off the timeline. The line and its takes stay."""

    def __init__(self, placement_id: str) -> None:
        self.placement_id = placement_id
        self._removed: Placement | None = None
        self._index = 0

    @property
    def label(self) -> str:
        return "Remove placed line"

    def apply(self, project: Project) -> None:
        index, placement = _find_placement(project, self.placement_id)
        self._removed = placement.model_copy(deep=True)
        self._index = index
        del project.placements[index]

    def revert(self, project: Project) -> None:
        if self._removed is None:
            raise CommandError("nothing to restore: command was not applied")
        project.placements.insert(self._index, self._removed.model_copy(deep=True))


class MovePlacement(Command):
    """Move a placement to another timeline time.

    The new anchor replaces the old one. Moving an orphaned placement settles
    it: the flag is cleared, and undo brings back both the old anchor and the flag.
    """

    def __init__(self, placement_id: str, timeline_ms: int) -> None:
        _check_time(timeline_ms)
        self.placement_id = placement_id
        self.timeline_ms = timeline_ms
        self._anchor: Anchor | None = None
        self._old_anchor: Anchor | None = None
        self._old_orphaned = False

    @property
    def label(self) -> str:
        return "Move placed line"

    def apply(self, project: Project) -> None:
        _, placement = _find_placement(project, self.placement_id)
        anchor = self._anchor
        if anchor is None:
            anchor = _anchor_at(project, self.timeline_ms)
        self._old_anchor = placement.anchor.model_copy()
        self._old_orphaned = placement.orphaned
        placement.anchor = anchor.model_copy()
        placement.orphaned = False
        self._anchor = anchor

    def revert(self, project: Project) -> None:
        if self._old_anchor is None:
            raise CommandError("nothing to restore: command was not applied")
        _, placement = _find_placement(project, self.placement_id)
        placement.anchor = self._old_anchor.model_copy()
        placement.orphaned = self._old_orphaned
