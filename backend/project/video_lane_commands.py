"""Video lane and lane clip commands (M8-2, schema v6).

Pure: they change the in-memory ``Project`` only. Lane clips sit at a timeline time
and are not anchored to footage (decision 4, 2026-11-20): no edit of the main
footage moves or cuts them, so there are no orphans here.

Rules kept by these commands:
- Clips on one lane never overlap (a clip covers ``[timeline_ms, end_ms)``).
- A recording's ``in_ms``/``out_ms`` stay inside the recording; a still starts at 0.
- A lane is removed only when empty; a locked lane refuses edits to its clips.

Command contract: ``apply`` validates first and raises ``CommandError`` before it
changes anything; ``revert`` restores the state from before ``apply``.
"""

from typing import Literal

from pydantic import ValidationError

from backend.project.commands import Command, CommandError
from backend.project.schema import (
    ImageFile,
    LaneClip,
    Project,
    Source,
    VideoLane,
    new_id,
)

# Shortest clip a trim can leave (ms), and the default length of a still.
MIN_LANE_CLIP_MS = 40
STILL_DEFAULT_MS = 5000

# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def find_video_lane(project: Project, lane_id: str) -> tuple[int, VideoLane]:
    for index, lane in enumerate(project.video_lanes):
        if lane.id == lane_id:
            return index, lane
    raise CommandError(f"unknown video lane id {lane_id!r}")


def find_lane_clip(project: Project, clip_id: str) -> tuple[int, LaneClip]:
    for index, clip in enumerate(project.lane_clips):
        if clip.id == clip_id:
            return index, clip
    raise CommandError(f"unknown lane clip id {clip_id!r}")


def find_image(project: Project, image_id: str) -> ImageFile:
    for image in project.image_files:
        if image.id == image_id:
            return image
    raise CommandError(f"unknown image id {image_id!r}")


def find_source(project: Project, source_id: str) -> Source:
    for source in project.sources:
        if source.id == source_id:
            return source
    raise CommandError(f"unknown source id {source_id!r}")


def video_lane_is_free(
    project: Project,
    lane_id: str,
    start_ms: int,
    end_ms: int,
    *,
    except_id: str | None = None,
) -> bool:
    """True when no clip on the lane overlaps ``[start_ms, end_ms)``."""
    return not any(
        clip.lane_id == lane_id
        and clip.id != except_id
        and clip.timeline_ms < end_ms
        and start_ms < clip.end_ms
        for clip in project.lane_clips
    )


def free_video_lane_from(
    project: Project, lane_id: str, start_ms: int, length_ms: int
) -> str | None:
    """The first unlocked lane, from ``lane_id`` up, where a clip of this length fits.

    ``None``: no lane has room there; the caller adds a lane on top.
    """
    index, _ = find_video_lane(project, lane_id)
    for lane in project.video_lanes[index:]:
        if not lane.locked and video_lane_is_free(
            project, lane.id, start_ms, start_ms + length_ms
        ):
            return lane.id
    return None


def next_video_lane_name(project: Project) -> str:
    """``Video N``: the main footage is Video 1, so lanes start at Video 2."""
    highest = 1
    for lane in project.video_lanes:
        prefix, _, number = lane.name.partition(" ")
        if prefix == "Video" and number.isdigit():
            highest = max(highest, int(number))
    return f"Video {highest + 1}"


def _check_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise CommandError("a lane name must not be empty")
    return cleaned


def _check_unlocked(project: Project, lane_id: str) -> None:
    _, lane = find_video_lane(project, lane_id)
    if lane.locked:
        raise CommandError(f"{lane.name} is locked: unlock it to edit its clips")


def _check_fits(project: Project, clip: LaneClip) -> None:
    _check_unlocked(project, clip.lane_id)
    if clip.source_id is not None:
        source = find_source(project, clip.source_id)
        if clip.out_ms > source.duration_ms:
            raise CommandError("the clip runs past the end of its recording")
    else:
        find_image(project, clip.image_id or "")
    if not video_lane_is_free(
        project, clip.lane_id, clip.timeline_ms, clip.end_ms, except_id=clip.id
    ):
        raise CommandError("another clip is already on that lane at that time")


def _build(clip: LaneClip, **changes: object) -> LaneClip:
    try:
        return LaneClip.model_validate({**clip.model_dump(), **changes})
    except ValidationError as error:
        raise CommandError(f"invalid lane clip: {error.errors()[0]['msg']}") from error


# --------------------------------------------------------------------------
# Lanes
# --------------------------------------------------------------------------


class AddVideoLane(Command):
    """Add a lane at ``position`` (default: on top)."""

    def __init__(
        self,
        name: str | None = None,
        *,
        position: int | None = None,
        lane_id: str | None = None,
    ) -> None:
        self.name = None if name is None else _check_name(name)
        self.position = position
        self.lane_id = lane_id if lane_id is not None else new_id()

    @property
    def label(self) -> str:
        return "Add video lane"

    def apply(self, project: Project) -> None:
        if any(lane.id == self.lane_id for lane in project.video_lanes):
            raise CommandError(f"video lane id {self.lane_id!r} already exists")
        count = len(project.video_lanes)
        index = count if self.position is None else self.position
        if not 0 <= index <= count:
            raise CommandError(f"lane position {index} is out of range")
        if self.name is None:
            self.name = next_video_lane_name(project)
        project.video_lanes.insert(index, VideoLane(id=self.lane_id, name=self.name))

    def revert(self, project: Project) -> None:
        index, _ = find_video_lane(project, self.lane_id)
        del project.video_lanes[index]


class RemoveVideoLane(Command):
    """Remove an empty lane."""

    def __init__(self, lane_id: str) -> None:
        self.lane_id = lane_id
        self._removed: VideoLane | None = None
        self._index = 0

    @property
    def label(self) -> str:
        return "Remove video lane"

    def apply(self, project: Project) -> None:
        index, lane = find_video_lane(project, self.lane_id)
        if any(clip.lane_id == self.lane_id for clip in project.lane_clips):
            raise CommandError(
                f"{lane.name} still has clips: remove or move them first"
            )
        self._removed = lane
        self._index = index
        del project.video_lanes[index]

    def revert(self, project: Project) -> None:
        if self._removed is None:
            raise CommandError("nothing to restore: command was not applied")
        project.video_lanes.insert(self._index, self._removed)


class MoveVideoLane(Command):
    def __init__(self, lane_id: str, new_position: int) -> None:
        self.lane_id = lane_id
        self.new_position = new_position
        self._old_index = 0

    @property
    def label(self) -> str:
        return "Reorder video lanes"

    def apply(self, project: Project) -> None:
        index, lane = find_video_lane(project, self.lane_id)
        if not 0 <= self.new_position < len(project.video_lanes):
            raise CommandError(f"lane position {self.new_position} is out of range")
        self._old_index = index
        del project.video_lanes[index]
        project.video_lanes.insert(self.new_position, lane)

    def revert(self, project: Project) -> None:
        index, lane = find_video_lane(project, self.lane_id)
        del project.video_lanes[index]
        project.video_lanes.insert(self._old_index, lane)


class SetVideoLane(Command):
    """Rename a lane, hide or show it, lock or unlock it. ``None`` keeps a field."""

    def __init__(
        self,
        lane_id: str,
        *,
        name: str | None = None,
        hidden: bool | None = None,
        locked: bool | None = None,
    ) -> None:
        self.lane_id = lane_id
        self.changes: dict[str, object] = {}
        if name is not None:
            self.changes["name"] = _check_name(name)
        for key, value in (("hidden", hidden), ("locked", locked)):
            if value is not None:
                self.changes[key] = value
        if not self.changes:
            raise CommandError("nothing to change")
        self._old: VideoLane | None = None

    @property
    def label(self) -> str:
        if set(self.changes) == {"name"}:
            return "Rename video lane"
        return "Change video lane"

    def apply(self, project: Project) -> None:
        index, lane = find_video_lane(project, self.lane_id)
        self._old = lane
        project.video_lanes[index] = lane.model_copy(update=self.changes)

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        index, _ = find_video_lane(project, self.lane_id)
        project.video_lanes[index] = self._old


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------


class AddImageFile(Command):
    """Register an image already copied into ``images/`` (the import does the copy).
    Undo removes the entry only; the copy stays on disk and is found again."""

    def __init__(self, image: ImageFile) -> None:
        self.image = image

    @property
    def label(self) -> str:
        return f"Import {self.image.name}"

    def apply(self, project: Project) -> None:
        if any(i.id == self.image.id for i in project.image_files):
            raise CommandError(f"image id {self.image.id!r} already exists")
        key = self.image.path.casefold()
        if any(i.path.casefold() == key for i in project.image_files):
            raise CommandError(f"{self.image.path!r} is already in the project")
        project.image_files.append(self.image.model_copy(deep=True))

    def revert(self, project: Project) -> None:
        for index, image in enumerate(project.image_files):
            if image.id == self.image.id:
                del project.image_files[index]
                return
        raise CommandError(f"unknown image id {self.image.id!r}")


# --------------------------------------------------------------------------
# Clips
# --------------------------------------------------------------------------


class AddLaneClip(Command):
    """Put a recording (whole, or ``in_ms`` to ``out_ms``) or a still (``length_ms``,
    default 5 s) on a lane at a timeline time. Full frame, sound at 0 dB."""

    def __init__(
        self,
        lane_id: str,
        timeline_ms: int,
        *,
        source_id: str | None = None,
        image_id: str | None = None,
        in_ms: int = 0,
        out_ms: int | None = None,
        length_ms: int = STILL_DEFAULT_MS,
        clip_id: str | None = None,
    ) -> None:
        if timeline_ms < 0:
            raise CommandError("timeline time must not be negative")
        if (source_id is None) == (image_id is None):
            raise CommandError("give either a recording or an image")
        self.lane_id = lane_id
        self.timeline_ms = timeline_ms
        self.source_id = source_id
        self.image_id = image_id
        self.in_ms = in_ms
        self.out_ms = out_ms
        self.length_ms = length_ms
        self.clip_id = clip_id if clip_id is not None else new_id()

    @property
    def label(self) -> str:
        return "Add clip to a video lane"

    def apply(self, project: Project) -> None:
        if any(c.id == self.clip_id for c in project.lane_clips):
            raise CommandError(f"lane clip id {self.clip_id!r} already exists")
        if self.source_id is not None:
            source = find_source(project, self.source_id)
            in_ms = self.in_ms
            out_ms = source.duration_ms if self.out_ms is None else self.out_ms
        else:
            find_image(project, self.image_id or "")
            in_ms, out_ms = 0, self.length_ms
        try:
            clip = LaneClip(
                id=self.clip_id,
                lane_id=self.lane_id,
                source_id=self.source_id,
                image_id=self.image_id,
                timeline_ms=self.timeline_ms,
                in_ms=in_ms,
                out_ms=out_ms,
            )
        except ValidationError as error:
            raise CommandError(
                f"invalid lane clip: {error.errors()[0]['msg']}"
            ) from error
        _check_fits(project, clip)
        project.lane_clips.append(clip)

    def revert(self, project: Project) -> None:
        index, _ = find_lane_clip(project, self.clip_id)
        del project.lane_clips[index]


class RemoveLaneClip(Command):
    def __init__(self, clip_id: str) -> None:
        self.clip_id = clip_id
        self._removed: LaneClip | None = None
        self._index = 0

    @property
    def label(self) -> str:
        return "Remove clip from a video lane"

    def apply(self, project: Project) -> None:
        index, clip = find_lane_clip(project, self.clip_id)
        _check_unlocked(project, clip.lane_id)
        self._removed = clip
        self._index = index
        del project.lane_clips[index]

    def revert(self, project: Project) -> None:
        if self._removed is None:
            raise CommandError("nothing to restore: command was not applied")
        project.lane_clips.insert(self._index, self._removed)


class _ReplaceLaneClip(Command):
    clip_id: str
    _old: LaneClip | None = None

    def changed(self, project: Project, clip: LaneClip) -> LaneClip:
        raise NotImplementedError

    def apply(self, project: Project) -> None:
        index, clip = find_lane_clip(project, self.clip_id)
        _check_unlocked(project, clip.lane_id)
        new_clip = self.changed(project, clip)
        _check_fits(project, new_clip)
        self._old = clip
        project.lane_clips[index] = new_clip

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        index, _ = find_lane_clip(project, self.clip_id)
        project.lane_clips[index] = self._old


class MoveLaneClip(_ReplaceLaneClip):
    """Move a clip to a timeline time, and to another lane when ``lane_id`` is given."""

    def __init__(
        self, clip_id: str, timeline_ms: int, lane_id: str | None = None
    ) -> None:
        if timeline_ms < 0:
            raise CommandError("timeline time must not be negative")
        self.clip_id = clip_id
        self.timeline_ms = timeline_ms
        self.lane_id = lane_id

    @property
    def label(self) -> str:
        return "Move clip on a video lane"

    def changed(self, project: Project, clip: LaneClip) -> LaneClip:
        lane_id = clip.lane_id if self.lane_id is None else self.lane_id
        return _build(clip, timeline_ms=self.timeline_ms, lane_id=lane_id)


class TrimLaneClip(_ReplaceLaneClip):
    """Drag a clip edge to a timeline time. For a recording the start edge moves
    ``timeline_ms`` and ``in_ms`` together (the picture under the rest stays put);
    a still just gets shorter or longer."""

    def __init__(
        self, clip_id: str, edge: Literal["start", "end"], timeline_ms: int
    ) -> None:
        self.clip_id = clip_id
        self.edge = edge
        self.edge_ms = timeline_ms

    @property
    def label(self) -> str:
        return "Trim clip on a video lane"

    def changed(self, project: Project, clip: LaneClip) -> LaneClip:
        still = clip.image_id is not None
        if self.edge == "start":
            delta = self.edge_ms - clip.timeline_ms
            if self.edge_ms < 0:
                raise CommandError("timeline time must not be negative")
            if still:
                in_ms, out_ms = 0, clip.out_ms - delta
            else:
                in_ms, out_ms = clip.in_ms + delta, clip.out_ms
                if in_ms < 0:
                    raise CommandError(
                        "the clip already starts at the start of its recording"
                    )
            if out_ms - in_ms < MIN_LANE_CLIP_MS:
                raise CommandError("the clip would be too short")
            return _build(clip, timeline_ms=self.edge_ms, in_ms=in_ms, out_ms=out_ms)
        out_ms = clip.in_ms + (self.edge_ms - clip.timeline_ms)
        if out_ms - clip.in_ms < MIN_LANE_CLIP_MS:
            raise CommandError("the clip would be too short")
        return _build(clip, out_ms=out_ms)


class SplitLaneClip(Command):
    """Cut one video-lane clip in two at a timeline time (M8-2 addition).

    Both parts keep the position, size, opacity and sound settings; the right part
    gets a new id (or ``right_clip_id``). A still is split into two stills.
    """

    def __init__(
        self, clip_id: str, timeline_ms: int, right_clip_id: str | None = None
    ) -> None:
        self.clip_id = clip_id
        self.at_ms = timeline_ms
        self.right_id = right_clip_id or new_id()
        self._old: LaneClip | None = None

    @property
    def label(self) -> str:
        return "Split clip on a video lane"

    def apply(self, project: Project) -> None:
        index, clip = find_lane_clip(project, self.clip_id)
        _check_unlocked(project, clip.lane_id)
        offset = self.at_ms - clip.timeline_ms
        if offset < MIN_LANE_CLIP_MS or clip.end_ms - self.at_ms < MIN_LANE_CLIP_MS:
            raise CommandError("the playhead is not inside the clip")
        if clip.image_id is not None:
            left = _build(clip, out_ms=offset)
            right = _build(
                clip,
                id=self.right_id,
                timeline_ms=self.at_ms,
                out_ms=clip.out_ms - offset,
            )
        else:
            cut = clip.in_ms + offset
            left = _build(clip, out_ms=cut)
            right = _build(clip, id=self.right_id, timeline_ms=self.at_ms, in_ms=cut)
        self._old = clip
        project.lane_clips[index] = left
        project.lane_clips.insert(index + 1, right)

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        project.lane_clips = [c for c in project.lane_clips if c.id != self.right_id]
        index, _ = find_lane_clip(project, self.clip_id)
        project.lane_clips[index] = self._old


class SetLaneClip(_ReplaceLaneClip):
    """Change a clip's placement (x, y, scale), opacity, sound level or mute.
    ``None`` leaves a field as it is."""

    def __init__(
        self,
        clip_id: str,
        *,
        x: float | None = None,
        y: float | None = None,
        scale: float | None = None,
        opacity: float | None = None,
        gain_db: float | None = None,
        mute: bool | None = None,
    ) -> None:
        self.clip_id = clip_id
        self.changes: dict[str, object] = {
            key: value
            for key, value in (
                ("x", x),
                ("y", y),
                ("scale", scale),
                ("opacity", opacity),
                ("gain_db", gain_db),
                ("mute", mute),
            )
            if value is not None
        }
        if not self.changes:
            raise CommandError("nothing to change")

    @property
    def label(self) -> str:
        if set(self.changes) <= {"x", "y", "scale"}:
            return "Place clip on a video lane"
        return "Change clip on a video lane"

    def changed(self, project: Project, clip: LaneClip) -> LaneClip:
        return _build(clip, **self.changes)
