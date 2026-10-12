"""Edit operations the API accepts, and how each becomes a Command (M2-S6c).

Pure: no file or network access. Each op is a small validated request body;
``build_command`` turns it into the matching clip command. A batch of ops runs
as one undo step (``Session.edit`` wraps it in ``CommandStack.group``).

``right_clip_id`` (split, ripple-delete) is optional. Leave it out and the new
clip gets a generated id, visible in the returned timeline. Pass your own
12-char hex id when a later op in the same batch has to refer to the new clip.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.project.clip_commands import AddClip, RemoveClip, ReorderClip, SetSpeed
from backend.project.commands import Command, CommandError
from backend.project.cut_commands import RippleDelete, SplitClip, TrimClip


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


EditOp = Annotated[
    AddClipOp
    | RemoveClipOp
    | SetSpeedOp
    | ReorderClipOp
    | SplitClipOp
    | TrimClipOp
    | RippleDeleteOp,
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
    raise CommandError(f"unsupported edit {op!r}")
