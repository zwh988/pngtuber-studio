"""Edit operations the API accepts, and how each becomes a Command (M2-S6c, M3-7).

Pure: no file or network access. Each op is a small validated request body;
``build_command`` turns it into the matching clip command. A batch of ops runs
as one undo step (``Session.edit`` wraps it in ``CommandStack.group``).

``right_clip_id`` (split, ripple-delete) is optional. Leave it out and the new
clip gets a generated id, visible in the returned timeline. Pass your own
12-char hex id when a later op in the same batch has to refer to the new clip.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.project.audio_commands import (
    AddAudioClip,
    AddAudioLane,
    MoveAudioClip,
    MoveAudioLane,
    RemoveAudioClip,
    RemoveAudioLane,
    SetAudioClip,
    SetAudioLane,
    SplitAudioClip,
    TrimAudioClip,
)
from backend.project.avatar_commands import (
    AddKeyframe,
    AddReaction,
    KeyLane,
    KeyLaneBy,
    MoveKeyframe,
    MoveReaction,
    RemoveKeyframe,
    RemoveReaction,
    SetAvatarSettings,
    SetKeyframeInterpolation,
    SetKeyframeValue,
    SetReaction,
)
from backend.project.clip_commands import AddClip, RemoveClip, ReorderClip, SetSpeed
from backend.project.commands import Command, CommandError
from backend.project.cut_commands import RippleDelete, SplitClip, TrimClip
from backend.project.export_commands import SetExportSettings
from backend.project.placement_commands import (
    AddPlacement,
    MovePlacement,
    RemovePlacement,
    SetPlacementStretch,
)
from backend.project.video_lane_commands import (
    AddLaneClip,
    AddVideoLane,
    MoveLaneClip,
    MoveVideoLane,
    RemoveLaneClip,
    RemoveVideoLane,
    SetLaneClip,
    SetVideoLane,
    SplitLaneClip,
    TrimLaneClip,
)


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddClipOp(_Op):
    op: Literal["add_clip"] = "add_clip"
    source_id: str
    position: int | None = None


class RemoveClipOp(_Op):
    op: Literal["remove_clip"] = "remove_clip"
    clip_id: str


class SetSpeedOp(_Op):
    op: Literal["set_speed"] = "set_speed"
    clip_id: str
    speed: float


class ReorderClipOp(_Op):
    op: Literal["reorder_clip"] = "reorder_clip"
    clip_id: str
    # Position after the move, counted among track-0 clips.
    new_position: int


class SplitClipOp(_Op):
    op: Literal["split_clip"] = "split_clip"
    timeline_ms: int
    right_clip_id: str | None = None


class TrimClipOp(_Op):
    op: Literal["trim_clip"] = "trim_clip"
    clip_id: str
    edge: Literal["in", "out"]
    # A SOURCE time (the editor converts the playhead first).
    source_ms: int


class RippleDeleteOp(_Op):
    op: Literal["ripple_delete"] = "ripple_delete"
    start_ms: int
    end_ms: int
    right_clip_id: str | None = None


class AddPlacementOp(_Op):
    op: Literal["add_placement"] = "add_placement"
    line_id: str
    # A TIMELINE time; the command turns it into an anchor (clip + source time).
    timeline_ms: int
    placement_id: str | None = None


class MovePlacementOp(_Op):
    op: Literal["move_placement"] = "move_placement"
    placement_id: str
    # A TIMELINE time: where the start of the placed line goes.
    timeline_ms: int


class RemovePlacementOp(_Op):
    op: Literal["remove_placement"] = "remove_placement"
    placement_id: str


class SetPlacementStretchOp(_Op):
    op: Literal["set_placement_stretch"] = "set_placement_stretch"
    placement_id: str
    # 1.0 (as recorded) to 1.25 (25 percent faster); rounded to 3 decimals.
    stretch: float


# --- avatar (M5-5): keys and reactions take timeline times, stored as anchors -----


class AddKeyframeOp(_Op):
    op: Literal["add_keyframe"] = "add_keyframe"
    lane_id: str
    timeline_ms: int
    value: float | str
    interpolation: Literal["hold", "smooth"] | None = None  # None: the lane's default
    keyframe_id: str | None = None


class KeyLaneOp(_Op):
    """Set a lane at a time: change the key already there, else add one."""

    op: Literal["key_lane"] = "key_lane"
    lane_id: str
    timeline_ms: int
    value: float | str
    keyframe_id: str | None = None


class KeyLaneByOp(_Op):
    """Key a numeric lane at a time to (its value there) x factor + delta."""

    op: Literal["key_lane_by"] = "key_lane_by"
    lane_id: str
    timeline_ms: int
    delta: float = 0.0
    factor: float = 1.0


class MoveKeyframeOp(_Op):
    op: Literal["move_keyframe"] = "move_keyframe"
    keyframe_id: str
    timeline_ms: int


class SetKeyframeValueOp(_Op):
    op: Literal["set_keyframe_value"] = "set_keyframe_value"
    keyframe_id: str
    value: float | str


class SetKeyframeInterpolationOp(_Op):
    op: Literal["set_keyframe_interpolation"] = "set_keyframe_interpolation"
    keyframe_id: str
    interpolation: Literal["hold", "smooth"]


class RemoveKeyframeOp(_Op):
    op: Literal["remove_keyframe"] = "remove_keyframe"
    keyframe_id: str


class AddReactionOp(_Op):
    op: Literal["add_reaction"] = "add_reaction"
    type: str
    timeline_ms: int
    intensity: float = 1.0
    duration_ms: int = 500
    reaction_id: str | None = None


class MoveReactionOp(_Op):
    op: Literal["move_reaction"] = "move_reaction"
    reaction_id: str
    timeline_ms: int


class SetReactionOp(_Op):
    op: Literal["set_reaction"] = "set_reaction"
    reaction_id: str
    type: str | None = None
    intensity: float | None = None
    duration_ms: int | None = None


class RemoveReactionOp(_Op):
    op: Literal["remove_reaction"] = "remove_reaction"
    reaction_id: str


class SetAvatarSettingsOp(_Op):
    op: Literal["set_avatar_settings"] = "set_avatar_settings"
    x: float | None = None
    y: float | None = None
    scale: float | None = None
    rotation_deg: float | None = None
    auto_key_expression: bool | None = None
    bounce: float | None = None
    float_amp: float | None = None
    float_speed: float | None = None
    float_angle_deg: float | None = None
    blink_rate: float | None = None
    mouth_sensitivity: float | None = None


class SetExportSettingsOp(_Op):
    """M7 S5: export defaults saved back to the project (one undo step)."""

    op: Literal["set_export_settings"] = "set_export_settings"
    height: int | None = None
    fps: Literal["match"] | float | None = None
    include_avatar_overlay: bool | None = None
    include_raw_video_link: bool | None = None
    unload_tts_before_export: bool | None = None


# ---- audio lanes and clips (M8-1, schema v5) --------------------------------


class AddAudioLaneOp(_Op):
    op: Literal["add_audio_lane"] = "add_audio_lane"
    name: str | None = None
    position: int | None = None
    lane_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")


class RemoveAudioLaneOp(_Op):
    op: Literal["remove_audio_lane"] = "remove_audio_lane"
    lane_id: str


class MoveAudioLaneOp(_Op):
    op: Literal["move_audio_lane"] = "move_audio_lane"
    lane_id: str
    new_position: int


class SetAudioLaneOp(_Op):
    op: Literal["set_audio_lane"] = "set_audio_lane"
    lane_id: str
    name: str | None = None
    gain_db: float | None = None
    mute: bool | None = None
    solo: bool | None = None


class AddAudioClipOp(_Op):
    op: Literal["add_audio_clip"] = "add_audio_clip"
    file_id: str
    lane_id: str
    timeline_ms: int
    in_ms: int = 0
    out_ms: int | None = None
    clip_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")


class RemoveAudioClipOp(_Op):
    op: Literal["remove_audio_clip"] = "remove_audio_clip"
    clip_id: str


class MoveAudioClipOp(_Op):
    op: Literal["move_audio_clip"] = "move_audio_clip"
    clip_id: str
    timeline_ms: int
    lane_id: str | None = None


class TrimAudioClipOp(_Op):
    op: Literal["trim_audio_clip"] = "trim_audio_clip"
    clip_id: str
    edge: Literal["start", "end"]
    timeline_ms: int


class SplitAudioClipOp(_Op):
    op: Literal["split_audio_clip"] = "split_audio_clip"
    clip_id: str
    timeline_ms: int
    right_clip_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")


class SetAudioClipOp(_Op):
    op: Literal["set_audio_clip"] = "set_audio_clip"
    clip_id: str
    gain_db: float | None = None
    fade_in_ms: int | None = None
    fade_out_ms: int | None = None


# ---- video lanes and lane clips (M8-2, schema v6) ----------------------------


class AddVideoLaneOp(_Op):
    op: Literal["add_video_lane"] = "add_video_lane"
    name: str | None = None
    position: int | None = None
    lane_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")


class RemoveVideoLaneOp(_Op):
    op: Literal["remove_video_lane"] = "remove_video_lane"
    lane_id: str


class MoveVideoLaneOp(_Op):
    op: Literal["move_video_lane"] = "move_video_lane"
    lane_id: str
    new_position: int


class SetVideoLaneOp(_Op):
    op: Literal["set_video_lane"] = "set_video_lane"
    lane_id: str
    name: str | None = None
    hidden: bool | None = None
    locked: bool | None = None


class AddLaneClipOp(_Op):
    op: Literal["add_lane_clip"] = "add_lane_clip"
    lane_id: str
    timeline_ms: int
    source_id: str | None = None
    image_id: str | None = None
    in_ms: int = 0
    out_ms: int | None = None
    length_ms: int = 5000
    clip_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")


class RemoveLaneClipOp(_Op):
    op: Literal["remove_lane_clip"] = "remove_lane_clip"
    clip_id: str


class MoveLaneClipOp(_Op):
    op: Literal["move_lane_clip"] = "move_lane_clip"
    clip_id: str
    timeline_ms: int
    lane_id: str | None = None


class TrimLaneClipOp(_Op):
    op: Literal["trim_lane_clip"] = "trim_lane_clip"
    clip_id: str
    edge: Literal["start", "end"]
    timeline_ms: int


class SplitLaneClipOp(_Op):
    op: Literal["split_lane_clip"] = "split_lane_clip"
    clip_id: str
    timeline_ms: int
    right_clip_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")


class SetLaneClipOp(_Op):
    op: Literal["set_lane_clip"] = "set_lane_clip"
    clip_id: str
    x: float | None = None
    y: float | None = None
    scale: float | None = None
    opacity: float | None = None
    gain_db: float | None = None
    mute: bool | None = None


EditOp = Annotated[
    AddClipOp
    | RemoveClipOp
    | SetSpeedOp
    | ReorderClipOp
    | SplitClipOp
    | TrimClipOp
    | RippleDeleteOp
    | AddPlacementOp
    | MovePlacementOp
    | RemovePlacementOp
    | SetPlacementStretchOp
    | AddKeyframeOp
    | KeyLaneOp
    | KeyLaneByOp
    | MoveKeyframeOp
    | SetKeyframeValueOp
    | SetKeyframeInterpolationOp
    | RemoveKeyframeOp
    | AddReactionOp
    | MoveReactionOp
    | SetReactionOp
    | RemoveReactionOp
    | SetAvatarSettingsOp
    | SetExportSettingsOp
    | AddAudioLaneOp
    | RemoveAudioLaneOp
    | MoveAudioLaneOp
    | SetAudioLaneOp
    | AddAudioClipOp
    | RemoveAudioClipOp
    | MoveAudioClipOp
    | TrimAudioClipOp
    | SplitAudioClipOp
    | SetAudioClipOp
    | AddVideoLaneOp
    | RemoveVideoLaneOp
    | MoveVideoLaneOp
    | SetVideoLaneOp
    | AddLaneClipOp
    | RemoveLaneClipOp
    | MoveLaneClipOp
    | TrimLaneClipOp
    | SplitLaneClipOp
    | SetLaneClipOp,
    Field(discriminator="op"),
]


class EditBatch(_Op):
    """Several ops applied as one undo step; all or nothing."""

    label: str = Field(min_length=1)
    ops: list[EditOp] = Field(min_length=1)


def build_command(op: EditOp) -> Command:
    if isinstance(op, AddClipOp):
        return AddClip(op.source_id, position=op.position)
    if isinstance(op, RemoveClipOp):
        return RemoveClip(op.clip_id)
    if isinstance(op, SetSpeedOp):
        return SetSpeed(op.clip_id, op.speed)
    if isinstance(op, ReorderClipOp):
        return ReorderClip(op.clip_id, op.new_position)
    if isinstance(op, SplitClipOp):
        return SplitClip(op.timeline_ms, right_clip_id=op.right_clip_id)
    if isinstance(op, TrimClipOp):
        return TrimClip(op.clip_id, op.edge, op.source_ms)
    if isinstance(op, RippleDeleteOp):
        return RippleDelete(op.start_ms, op.end_ms, right_clip_id=op.right_clip_id)
    if isinstance(op, AddPlacementOp):
        return AddPlacement(op.line_id, op.timeline_ms, placement_id=op.placement_id)
    if isinstance(op, MovePlacementOp):
        return MovePlacement(op.placement_id, op.timeline_ms)
    if isinstance(op, RemovePlacementOp):
        return RemovePlacement(op.placement_id)
    if isinstance(op, SetPlacementStretchOp):
        return SetPlacementStretch(op.placement_id, op.stretch)
    audio = _build_audio_command(op)
    if audio is not None:
        return audio
    video = _build_video_lane_command(op)
    if video is not None:
        return video
    return _build_avatar_command(op)


def _build_video_lane_command(op: EditOp) -> Command | None:
    if isinstance(op, AddVideoLaneOp):
        return AddVideoLane(op.name, position=op.position, lane_id=op.lane_id)
    if isinstance(op, RemoveVideoLaneOp):
        return RemoveVideoLane(op.lane_id)
    if isinstance(op, MoveVideoLaneOp):
        return MoveVideoLane(op.lane_id, op.new_position)
    if isinstance(op, SetVideoLaneOp):
        return SetVideoLane(op.lane_id, name=op.name, hidden=op.hidden, locked=op.locked)
    if isinstance(op, AddLaneClipOp):
        return AddLaneClip(
            op.lane_id,
            op.timeline_ms,
            source_id=op.source_id,
            image_id=op.image_id,
            in_ms=op.in_ms,
            out_ms=op.out_ms,
            length_ms=op.length_ms,
            clip_id=op.clip_id,
        )
    if isinstance(op, RemoveLaneClipOp):
        return RemoveLaneClip(op.clip_id)
    if isinstance(op, MoveLaneClipOp):
        return MoveLaneClip(op.clip_id, op.timeline_ms, op.lane_id)
    if isinstance(op, TrimLaneClipOp):
        return TrimLaneClip(op.clip_id, op.edge, op.timeline_ms)
    if isinstance(op, SplitLaneClipOp):
        return SplitLaneClip(op.clip_id, op.timeline_ms, op.right_clip_id)
    if isinstance(op, SetLaneClipOp):
        return SetLaneClip(
            op.clip_id,
            x=op.x,
            y=op.y,
            scale=op.scale,
            opacity=op.opacity,
            gain_db=op.gain_db,
            mute=op.mute,
        )
    return None


def _build_audio_command(op: EditOp) -> Command | None:
    if isinstance(op, AddAudioLaneOp):
        return AddAudioLane(op.name, position=op.position, lane_id=op.lane_id)
    if isinstance(op, RemoveAudioLaneOp):
        return RemoveAudioLane(op.lane_id)
    if isinstance(op, MoveAudioLaneOp):
        return MoveAudioLane(op.lane_id, op.new_position)
    if isinstance(op, SetAudioLaneOp):
        return SetAudioLane(
            op.lane_id, name=op.name, gain_db=op.gain_db, mute=op.mute, solo=op.solo
        )
    if isinstance(op, AddAudioClipOp):
        return AddAudioClip(
            op.file_id,
            op.lane_id,
            op.timeline_ms,
            in_ms=op.in_ms,
            out_ms=op.out_ms,
            clip_id=op.clip_id,
        )
    if isinstance(op, RemoveAudioClipOp):
        return RemoveAudioClip(op.clip_id)
    if isinstance(op, MoveAudioClipOp):
        return MoveAudioClip(op.clip_id, op.timeline_ms, op.lane_id)
    if isinstance(op, TrimAudioClipOp):
        return TrimAudioClip(op.clip_id, op.edge, op.timeline_ms)
    if isinstance(op, SplitAudioClipOp):
        return SplitAudioClip(op.clip_id, op.timeline_ms, op.right_clip_id)
    if isinstance(op, SetAudioClipOp):
        return SetAudioClip(
            op.clip_id, gain_db=op.gain_db, fade_in_ms=op.fade_in_ms, fade_out_ms=op.fade_out_ms
        )
    return None


def _build_avatar_command(op: EditOp) -> Command:
    if isinstance(op, AddKeyframeOp):
        return AddKeyframe(
            op.lane_id, op.timeline_ms, op.value, op.interpolation, keyframe_id=op.keyframe_id
        )
    if isinstance(op, KeyLaneOp):
        return KeyLane(op.lane_id, op.timeline_ms, op.value, keyframe_id=op.keyframe_id)
    if isinstance(op, KeyLaneByOp):
        return KeyLaneBy(op.lane_id, op.timeline_ms, delta=op.delta, factor=op.factor)
    if isinstance(op, MoveKeyframeOp):
        return MoveKeyframe(op.keyframe_id, op.timeline_ms)
    if isinstance(op, SetKeyframeValueOp):
        return SetKeyframeValue(op.keyframe_id, op.value)
    if isinstance(op, SetKeyframeInterpolationOp):
        return SetKeyframeInterpolation(op.keyframe_id, op.interpolation)
    if isinstance(op, RemoveKeyframeOp):
        return RemoveKeyframe(op.keyframe_id)
    if isinstance(op, AddReactionOp):
        return AddReaction(
            op.type, op.timeline_ms, op.intensity, op.duration_ms, reaction_id=op.reaction_id
        )
    if isinstance(op, MoveReactionOp):
        return MoveReaction(op.reaction_id, op.timeline_ms)
    if isinstance(op, SetReactionOp):
        return SetReaction(
            op.reaction_id, type_=op.type, intensity=op.intensity, duration_ms=op.duration_ms
        )
    if isinstance(op, RemoveReactionOp):
        return RemoveReaction(op.reaction_id)
    if isinstance(op, SetAvatarSettingsOp):
        return SetAvatarSettings(**op.model_dump(exclude={"op"}))
    if isinstance(op, SetExportSettingsOp):
        return SetExportSettings(**op.model_dump(exclude={"op"}))
    raise CommandError(f"unsupported edit {op!r}")
