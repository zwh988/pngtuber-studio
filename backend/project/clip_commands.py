"""Clip commands on timeline track 0 (M2-3, part 1): add, remove, speed, reorder.

Pure: mutates the in-memory ``Project`` only. Follows the command contract in
``commands.py`` (validate first, raise ``CommandError`` before changing
anything, record undo data, ``apply`` can run again after ``revert``).

Positions (``position``, ``new_position``) count among track-0 clips, in
timeline order. Clips on other tracks are never edited and keep their place
in the clip list relative to each other.
"""

from backend.edl.timemap import TIMELINE_TRACK, clip_spans, frame_to_ms
from backend.project.commands import Command, CommandError, _find_source
from backend.project.parking import (
    ParkedItem,
    collect_cut_away,
    park_cut_away,
    restore_parked,
)
from backend.project.schema import Clip, Project, Source, new_id

SPEED_MIN = 0.25
SPEED_MAX = 8.0


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _timeline_indices(project: Project) -> list[int]:
    """List indices of the track-0 clips, in timeline order."""
    return [i for i, c in enumerate(project.clips) if c.track == TIMELINE_TRACK]


def _find_timeline_clip(project: Project, clip_id: str) -> tuple[int, Clip]:
    for index, clip in enumerate(project.clips):
        if clip.id == clip_id:
            if clip.track != TIMELINE_TRACK:
                raise CommandError(f"clip {clip_id!r} is not on the timeline track")
            return index, clip
    raise CommandError(f"unknown clip id {clip_id!r}")


def _list_index_for_position(project: Project, position: int) -> int:
    """Clip-list index at which an insert lands at ``position`` among track-0
    clips. ``position`` may equal the track-0 clip count (insert after the last)."""
    indices = _timeline_indices(project)
    if position < len(indices):
        return indices[position]
    return indices[-1] + 1 if indices else len(project.clips)


def _min_clip_ms(source: Source) -> int:
    """Shortest allowed clip: one source frame (at least 1 ms)."""
    return max(1, frame_to_ms(1, source.fps_num, source.fps_den))


def _is_trailing_bookend(project: Project, clip: Clip) -> bool:
    if clip.overlay:
        return False
    try:
        _, source = _find_source(project, clip.source_id)
    except CommandError:
        return False
    return source.external


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


class AddClip(Command):
    """Add a clip covering a whole source to the timeline.

    Default position: before a trailing bookend (last clip, ``external``
    source, overlay off), otherwise at the end.
    """

    def __init__(
        self,
        source_id: str,
        *,
        position: int | None = None,
        clip_id: str | None = None,
    ) -> None:
        self.source_id = source_id
        self.position = position
        self.clip_id = clip_id if clip_id is not None else new_id()

    @property
    def label(self) -> str:
        return "Add clip to timeline"

    def apply(self, project: Project) -> None:
        _, source = _find_source(project, self.source_id)
        if any(c.id == self.clip_id for c in project.clips):
            raise CommandError(f"clip id {self.clip_id!r} already exists")
        if source.duration_ms < _min_clip_ms(source):
            raise CommandError(
                f"{source.path!r} is shorter than one frame and cannot be a clip"
            )
        indices = _timeline_indices(project)
        count = len(indices)
        if self.position is None:
            last_is_bookend = count > 0 and _is_trailing_bookend(
                project, project.clips[indices[-1]]
            )
            position = count - 1 if last_is_bookend else count
        else:
            position = self.position
        if not 0 <= position <= count:
            raise CommandError(f"position {position} is outside 0..{count}")
        clip = Clip(
            id=self.clip_id,
            source_id=self.source_id,
            in_ms=0,
            out_ms=source.duration_ms,
        )
        project.clips.insert(_list_index_for_position(project, position), clip)

    def revert(self, project: Project) -> None:
        for index, clip in enumerate(project.clips):
            if clip.id == self.clip_id:
                del project.clips[index]
                return
        raise CommandError("nothing to remove: command was not applied")


class RemoveClip(Command):
    """Remove a clip from the timeline (ripple).

    Items anchored to it are flagged orphaned and parked at the nearest
    surviving clip edge (see ``backend/project/parking.py``). Undo puts the clip
    and every item back exactly as they were.
    """

    def __init__(self, clip_id: str) -> None:
        self.clip_id = clip_id
        self._removed: Clip | None = None
        self._index = 0
        self._parked: list[ParkedItem] = []

    @property
    def label(self) -> str:
        return "Remove clip"

    def apply(self, project: Project) -> None:
        index, clip = _find_timeline_clip(project, self.clip_id)
        span = next(s for s in clip_spans(project.clips) if s.clip_id == clip.id)
        cut_away = collect_cut_away(project, [(clip.id, 0, None)], span.start_ms)
        self._removed = clip
        self._index = index
        del project.clips[index]
        self._parked = park_cut_away(
            project, cut_away, cut_ms=span.start_ms, region_ms=span.duration_ms
        )

    def revert(self, project: Project) -> None:
        if self._removed is None:
            raise CommandError("nothing to restore: command was not applied")
        project.clips.insert(self._index, self._removed)
        restore_parked(self._parked)
        self._parked = []


class SetSpeed(Command):
    """Set a clip's playback speed (0.25x to 8x). Later clips ripple; anchors
    keep their source time."""

    def __init__(self, clip_id: str, speed: float) -> None:
        self.clip_id = clip_id
        self.speed = float(speed)
        self._old_speed: float | None = None

    @property
    def label(self) -> str:
        return "Set clip speed"

    def apply(self, project: Project) -> None:
        _, clip = _find_timeline_clip(project, self.clip_id)
        if not SPEED_MIN <= self.speed <= SPEED_MAX:
            raise CommandError(
                f"speed {self.speed} is outside {SPEED_MIN} to {SPEED_MAX}"
            )
        if self.speed == clip.speed:
            raise CommandError(f"clip speed is already {self.speed}")
        self._old_speed = clip.speed
        clip.speed = self.speed

    def revert(self, project: Project) -> None:
        if self._old_speed is None:
            raise CommandError("nothing to restore: command was not applied")
        _, clip = _find_timeline_clip(project, self.clip_id)
        clip.speed = self._old_speed


class ReorderClip(Command):
    """Move a clip to ``new_position`` among the track-0 clips.

    ``new_position`` is the clip's position after the move (0 = first).
    Anchored items keep their clip id and source time.
    """

    def __init__(self, clip_id: str, new_position: int) -> None:
        self.clip_id = clip_id
        self.new_position = new_position
        self._old_index = 0
        self._new_index = 0

    @property
    def label(self) -> str:
        return "Reorder clip"

    def apply(self, project: Project) -> None:
        old_index, clip = _find_timeline_clip(project, self.clip_id)
        indices = _timeline_indices(project)
        if not 0 <= self.new_position < len(indices):
            raise CommandError(
                f"position {self.new_position} is outside 0..{len(indices) - 1}"
            )
        if indices.index(old_index) == self.new_position:
            raise CommandError("clip is already at that position")
        del project.clips[old_index]
        new_index = _list_index_for_position(project, self.new_position)
        project.clips.insert(new_index, clip)
        self._old_index = old_index
        self._new_index = new_index

    def revert(self, project: Project) -> None:
        index, clip = _find_timeline_clip(project, self.clip_id)
        del project.clips[index]
        project.clips.insert(self._old_index, clip)
