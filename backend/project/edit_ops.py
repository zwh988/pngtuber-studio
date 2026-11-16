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
from backend.project.placement_commands import (
    AddPlacement,
    MovePlacement,
    RemovePlacement,
    SetPlacementStretch,
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
    | SetAvatarSettingsOp,
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
    return _build_avatar_command(op)


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
        return SetAvatarSettings(
            x=op.x,
            y=op.y,
            scale=op.scale,
            rotation_deg=op.rotation_deg,
            auto_key_expression=op.auto_key_expression,
        )
    raise CommandError(f"unsupported edit {op!r}")
