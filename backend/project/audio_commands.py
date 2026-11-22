"""Audio lane and audio clip commands (M8-1, schema v5).

Pure: they change the in-memory ``Project`` only. Audio clips sit at a timeline
time and are not anchored to footage (decision 2, 2026-11-20): no video edit
moves or cuts them, so there are no orphans here.

Rules kept by these commands:
- Clips on one lane never overlap (a clip covers ``[timeline_ms, end_ms)``).
- A clip's ``in_ms``/``out_ms`` stay inside its file's duration.
- There is always at least one audio lane; a lane is removed only when empty.

Command contract: ``apply`` validates first and raises ``CommandError`` before it
changes anything; ``revert`` restores the state from before ``apply``.
"""

from typing import Literal

from pydantic import ValidationError

from backend.audio.chainspec import FxChainError
from backend.audio.clipfx import validate_clip_fx
from backend.project.commands import Command, CommandError
from backend.project.line_commands import NoChange
from backend.project.schema import (
    AudioClip,
    AudioFile,
    AudioLane,
    ClipFx,
    Project,
    new_id,
)

# Shortest clip a trim can leave (ms).
MIN_AUDIO_CLIP_MS = 10

# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def find_lane(project: Project, lane_id: str) -> tuple[int, AudioLane]:
    for index, lane in enumerate(project.audio_lanes):
        if lane.id == lane_id:
            return index, lane
    raise CommandError(f"unknown audio lane id {lane_id!r}")


def find_audio_file(project: Project, file_id: str) -> AudioFile:
    for audio_file in project.audio_files:
        if audio_file.id == file_id:
            return audio_file
    raise CommandError(f"unknown audio file id {file_id!r}")


def find_audio_clip(project: Project, clip_id: str) -> tuple[int, AudioClip]:
    for index, clip in enumerate(project.audio_clips):
        if clip.id == clip_id:
            return index, clip
    raise CommandError(f"unknown audio clip id {clip_id!r}")


def lane_is_free(
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
        for clip in project.audio_clips
    )


def free_lane_from(
    project: Project, lane_id: str, start_ms: int, length_ms: int
) -> str | None:
    """The first lane, from ``lane_id`` down, where a clip of this length fits.

    ``None`` means no lane has room there: the caller adds a lane below the last.
    """
    index, _ = find_lane(project, lane_id)
    for lane in project.audio_lanes[index:]:
        if lane_is_free(project, lane.id, start_ms, start_ms + length_ms):
            return lane.id
    return None


def next_lane_name(project: Project) -> str:
    """``Audio N`` with N one past the highest number in use."""
    highest = 0
    for lane in project.audio_lanes:
        prefix, _, number = lane.name.partition(" ")
        if prefix == "Audio" and number.isdigit():
            highest = max(highest, int(number))
    return f"Audio {highest + 1}"


def _check_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise CommandError("a lane name must not be empty")
    return cleaned


def _check_fits(project: Project, clip: AudioClip) -> None:
    find_lane(project, clip.lane_id)
    audio_file = find_audio_file(project, clip.file_id)
    if clip.out_ms > audio_file.duration_ms:
        raise CommandError("the clip runs past the end of its file")
    if not lane_is_free(
        project, clip.lane_id, clip.timeline_ms, clip.end_ms, except_id=clip.id
    ):
        raise CommandError("another clip is already on that lane at that time")


def _build_clip(clip: AudioClip, **changes: object) -> AudioClip:
    try:
        return AudioClip.model_validate({**clip.model_dump(), **changes})
    except ValidationError as error:
        raise CommandError(f"invalid audio clip: {error.errors()[0]['msg']}") from error


# --------------------------------------------------------------------------
# Lanes
# --------------------------------------------------------------------------


class AddAudioLane(Command):
    """Add a lane at ``position`` (default: below the last one)."""

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
        self._index = 0

    @property
    def label(self) -> str:
        return "Add audio lane"

    def apply(self, project: Project) -> None:
        if any(lane.id == self.lane_id for lane in project.audio_lanes):
            raise CommandError(f"audio lane id {self.lane_id!r} already exists")
        count = len(project.audio_lanes)
        index = count if self.position is None else self.position
        if not 0 <= index <= count:
            raise CommandError(f"lane position {index} is out of range")
        if self.name is None:
            self.name = next_lane_name(project)
        lane = AudioLane(id=self.lane_id, name=self.name)
        project.audio_lanes.insert(index, lane)
        self._index = index

    def revert(self, project: Project) -> None:
        index, _ = find_lane(project, self.lane_id)
        del project.audio_lanes[index]


class RemoveAudioLane(Command):
    """Remove an empty lane. The last lane is never removed."""

    def __init__(self, lane_id: str) -> None:
        self.lane_id = lane_id
        self._removed: AudioLane | None = None
        self._index = 0

    @property
    def label(self) -> str:
        return "Remove audio lane"

    def apply(self, project: Project) -> None:
        index, lane = find_lane(project, self.lane_id)
        if len(project.audio_lanes) == 1:
            raise CommandError("the last audio lane cannot be removed")
        if any(clip.lane_id == self.lane_id for clip in project.audio_clips):
            raise CommandError(
                f"{lane.name} still has clips: remove or move them first"
            )
        self._removed = lane
        self._index = index
        del project.audio_lanes[index]

    def revert(self, project: Project) -> None:
        if self._removed is None:
            raise CommandError("nothing to restore: command was not applied")
        project.audio_lanes.insert(self._index, self._removed)


class MoveAudioLane(Command):
    def __init__(self, lane_id: str, new_position: int) -> None:
        self.lane_id = lane_id
        self.new_position = new_position
        self._old_index = 0

    @property
    def label(self) -> str:
        return "Reorder audio lanes"

    def apply(self, project: Project) -> None:
        index, lane = find_lane(project, self.lane_id)
        if not 0 <= self.new_position < len(project.audio_lanes):
            raise CommandError(f"lane position {self.new_position} is out of range")
        self._old_index = index
        del project.audio_lanes[index]
        project.audio_lanes.insert(self.new_position, lane)

    def revert(self, project: Project) -> None:
        index, lane = find_lane(project, self.lane_id)
        del project.audio_lanes[index]
        project.audio_lanes.insert(self._old_index, lane)


class SetAudioLane(Command):
    """Rename a lane or change its level, mute or solo. ``None`` leaves a field as it is."""

    def __init__(
        self,
        lane_id: str,
        *,
        name: str | None = None,
        gain_db: float | None = None,
        mute: bool | None = None,
        solo: bool | None = None,
    ) -> None:
        self.lane_id = lane_id
        self.changes: dict[str, object] = {}
        if name is not None:
            self.changes["name"] = _check_name(name)
        for key, value in (("gain_db", gain_db), ("mute", mute), ("solo", solo)):
            if value is not None:
                self.changes[key] = value
        if not self.changes:
            raise CommandError("nothing to change")
        self._old: AudioLane | None = None

    @property
    def label(self) -> str:
        if set(self.changes) == {"name"}:
            return "Rename audio lane"
        return "Change audio lane"

    def apply(self, project: Project) -> None:
        index, lane = find_lane(project, self.lane_id)
        try:
            new_lane = AudioLane.model_validate({**lane.model_dump(), **self.changes})
        except ValidationError as error:
            raise CommandError(
                f"invalid audio lane: {error.errors()[0]['msg']}"
            ) from error
        self._old = lane
        project.audio_lanes[index] = new_lane

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        index, _ = find_lane(project, self.lane_id)
        project.audio_lanes[index] = self._old


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


class AddAudioFile(Command):
    """Register a file already copied into ``audio/`` (the import does the copy).

    Undo removes the entry only; the copy stays on disk, and importing the same
    file again finds it there.
    """

    def __init__(self, audio_file: AudioFile) -> None:
        self.audio_file = audio_file

    @property
    def label(self) -> str:
        return f"Import {self.audio_file.name}"

    def apply(self, project: Project) -> None:
        if any(f.id == self.audio_file.id for f in project.audio_files):
            raise CommandError(f"audio file id {self.audio_file.id!r} already exists")
        key = self.audio_file.path.casefold()
        if any(f.path.casefold() == key for f in project.audio_files):
            raise CommandError(f"{self.audio_file.path!r} is already in the project")
        project.audio_files.append(self.audio_file.model_copy(deep=True))

    def revert(self, project: Project) -> None:
        for index, audio_file in enumerate(project.audio_files):
            if audio_file.id == self.audio_file.id:
                del project.audio_files[index]
                return
        raise CommandError(f"unknown audio file id {self.audio_file.id!r}")


# --------------------------------------------------------------------------
# Clips
# --------------------------------------------------------------------------


class AddAudioClip(Command):
    """Put (part of) an audio file on a lane at a timeline time.

    ``out_ms`` defaults to the end of the file.
    """

    def __init__(
        self,
        file_id: str,
        lane_id: str,
        timeline_ms: int,
        *,
        in_ms: int = 0,
        out_ms: int | None = None,
        clip_id: str | None = None,
    ) -> None:
        if timeline_ms < 0:
            raise CommandError("timeline time must not be negative")
        self.file_id = file_id
        self.lane_id = lane_id
        self.timeline_ms = timeline_ms
        self.in_ms = in_ms
        self.out_ms = out_ms
        self.clip_id = clip_id if clip_id is not None else new_id()

    @property
    def label(self) -> str:
        return "Add audio clip"

    def apply(self, project: Project) -> None:
        if any(c.id == self.clip_id for c in project.audio_clips):
            raise CommandError(f"audio clip id {self.clip_id!r} already exists")
        audio_file = find_audio_file(project, self.file_id)
        out_ms = audio_file.duration_ms if self.out_ms is None else self.out_ms
        try:
            clip = AudioClip(
                id=self.clip_id,
                lane_id=self.lane_id,
                file_id=self.file_id,
                timeline_ms=self.timeline_ms,
                in_ms=self.in_ms,
                out_ms=out_ms,
            )
        except ValidationError as error:
            raise CommandError(
                f"invalid audio clip: {error.errors()[0]['msg']}"
            ) from error
        _check_fits(project, clip)
        project.audio_clips.append(clip)

    def revert(self, project: Project) -> None:
        index, _ = find_audio_clip(project, self.clip_id)
        del project.audio_clips[index]


class RemoveAudioClip(Command):
    def __init__(self, clip_id: str) -> None:
        self.clip_id = clip_id
        self._removed: AudioClip | None = None
        self._index = 0

    @property
    def label(self) -> str:
        return "Remove audio clip"

    def apply(self, project: Project) -> None:
        index, clip = find_audio_clip(project, self.clip_id)
        self._removed = clip
        self._index = index
        del project.audio_clips[index]

    def revert(self, project: Project) -> None:
        if self._removed is None:
            raise CommandError("nothing to restore: command was not applied")
        project.audio_clips.insert(self._index, self._removed)


class _ReplaceClip(Command):
    """Base for commands that swap one clip for a changed copy."""

    clip_id: str
    _old: AudioClip | None = None

    def changed(self, project: Project, clip: AudioClip) -> AudioClip:
        raise NotImplementedError

    def apply(self, project: Project) -> None:
        index, clip = find_audio_clip(project, self.clip_id)
        new_clip = self.changed(project, clip)
        _check_fits(project, new_clip)
        self._old = clip
        project.audio_clips[index] = new_clip

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        index, _ = find_audio_clip(project, self.clip_id)
        project.audio_clips[index] = self._old


class MoveAudioClip(_ReplaceClip):
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
        return "Move audio clip"

    def changed(self, project: Project, clip: AudioClip) -> AudioClip:
        lane_id = clip.lane_id if self.lane_id is None else self.lane_id
        return _build_clip(clip, timeline_ms=self.timeline_ms, lane_id=lane_id)


class TrimAudioClip(_ReplaceClip):
    """Drag a clip edge to a timeline time.

    The start edge moves ``timeline_ms`` and ``in_ms`` together, so the sound
    under the rest of the clip stays where it was. Fades shrink when the clip
    gets too short for them.
    """

    def __init__(
        self, clip_id: str, edge: Literal["start", "end"], timeline_ms: int
    ) -> None:
        self.clip_id = clip_id
        self.edge = edge
        self.edge_ms = timeline_ms

    @property
    def label(self) -> str:
        return "Trim audio clip"

    def changed(self, project: Project, clip: AudioClip) -> AudioClip:
        if self.edge == "start":
            in_ms = clip.in_ms + (self.edge_ms - clip.timeline_ms)
            if in_ms < 0:
                raise CommandError("the clip already starts at the start of its file")
            if clip.out_ms - in_ms < MIN_AUDIO_CLIP_MS:
                raise CommandError("the clip would be too short")
            timeline_ms, out_ms = self.edge_ms, clip.out_ms
        else:
            out_ms = clip.in_ms + (self.edge_ms - clip.timeline_ms)
            if out_ms - clip.in_ms < MIN_AUDIO_CLIP_MS:
                raise CommandError("the clip would be too short")
            timeline_ms, in_ms = clip.timeline_ms, clip.in_ms
        fade_in, fade_out = _fit_fades(
            clip.fade_in_ms, clip.fade_out_ms, out_ms - in_ms
        )
        return _build_clip(
            clip,
            timeline_ms=timeline_ms,
            in_ms=in_ms,
            out_ms=out_ms,
            fade_in_ms=fade_in,
            fade_out_ms=fade_out,
        )


def _fit_fades(fade_in: int, fade_out: int, length: int) -> tuple[int, int]:
    """Scale both fades down by the same factor when they no longer fit."""
    total = fade_in + fade_out
    if total <= length:
        return fade_in, fade_out
    new_in = fade_in * length // total
    return new_in, min(fade_out, length - new_in)


class SplitAudioClip(Command):
    """Cut one audio clip in two at a timeline time (M8-2 addition, 2026-11-20).

    The left part keeps the clip's id and fade-in, the right part gets a new id
    (or ``right_clip_id``) and the fade-out; the sound itself does not move.
    """

    def __init__(
        self, clip_id: str, timeline_ms: int, right_clip_id: str | None = None
    ) -> None:
        self.clip_id = clip_id
        self.at_ms = timeline_ms
        self.right_id = right_clip_id or new_id()
        self._old: AudioClip | None = None

    @property
    def label(self) -> str:
        return "Split audio clip"

    def apply(self, project: Project) -> None:
        index, clip = find_audio_clip(project, self.clip_id)
        offset = self.at_ms - clip.timeline_ms
        if offset < MIN_AUDIO_CLIP_MS or clip.end_ms - self.at_ms < MIN_AUDIO_CLIP_MS:
            raise CommandError("the playhead is not inside the clip")
        cut = clip.in_ms + offset
        left_in, _ = _fit_fades(clip.fade_in_ms, 0, offset)
        _, right_out = _fit_fades(0, clip.fade_out_ms, clip.out_ms - cut)
        left = _build_clip(clip, out_ms=cut, fade_in_ms=left_in, fade_out_ms=0)
        right = _build_clip(
            clip,
            id=self.right_id,
            timeline_ms=self.at_ms,
            in_ms=cut,
            fade_in_ms=0,
            fade_out_ms=right_out,
        )
        self._old = clip
        project.audio_clips[index] = left
        project.audio_clips.insert(index + 1, right)

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        project.audio_clips = [c for c in project.audio_clips if c.id != self.right_id]
        index, _ = find_audio_clip(project, self.clip_id)
        project.audio_clips[index] = self._old


class SetAudioClip(_ReplaceClip):
    """Change a clip's level or fades. ``None`` leaves a field as it is."""

    def __init__(
        self,
        clip_id: str,
        *,
        gain_db: float | None = None,
        fade_in_ms: int | None = None,
        fade_out_ms: int | None = None,
    ) -> None:
        self.clip_id = clip_id
        self.changes: dict[str, object] = {
            key: value
            for key, value in (
                ("gain_db", gain_db),
                ("fade_in_ms", fade_in_ms),
                ("fade_out_ms", fade_out_ms),
            )
            if value is not None
        }
        if not self.changes:
            raise CommandError("nothing to change")

    @property
    def label(self) -> str:
        return "Change audio clip"

    def changed(self, project: Project, clip: AudioClip) -> AudioClip:
        return _build_clip(clip, **self.changes)

class SetAudioClipFx(_ReplaceClip):
    """Set or clear an audio clip's FX chain (M8-4); None plays the file as it is.
    Several of these in one batch apply one chain to several clips in one undo step."""

    def __init__(self, clip_id: str, fx: ClipFx | None) -> None:
        if fx is not None:
            try:
                validate_clip_fx(fx)
            except FxChainError as exc:
                raise CommandError(str(exc)) from exc
        self.clip_id = clip_id
        self.fx = None if fx is None else fx.model_copy(deep=True)

    @property
    def label(self) -> str:
        return "Clear audio clip FX" if self.fx is None else "Change audio clip FX"

    def changed(self, project: Project, clip: AudioClip) -> AudioClip:
        if clip.fx == self.fx:
            raise NoChange("the clip already has these FX")
        return _build_clip(clip, fx=None if self.fx is None else self.fx.model_dump())

