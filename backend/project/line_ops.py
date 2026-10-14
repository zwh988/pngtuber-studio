"""Line bank edit operations the API accepts, and how each becomes a Command (M3-4).

Pure: no file or network access. Mirrors ``edit_ops.py`` for clips. A batch runs
as one undo step. ``line_id`` on ``add_line`` is optional; pass your own 12-char
hex id when a later op in the same batch has to refer to the new line.
"""

from collections.abc import Collection
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.project.commands import Command, CommandError
from backend.project.line_commands import (
    AddLine,
    RemoveLine,
    SetActiveTake,
    SetAllowOverlap,
    SetLineCfgWeight,
    SetLineEmotion,
    SetLineExaggeration,
    SetLineText,
    StarTake,
)


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddLineOp(_Op):
    op: Literal["add_line"] = "add_line"
    text: str = ""
    emotion: str = "neutral"
    position: int | None = None
    line_id: str | None = None


class RemoveLineOp(_Op):
    op: Literal["remove_line"] = "remove_line"
    line_id: str


class SetLineTextOp(_Op):
    op: Literal["set_line_text"] = "set_line_text"
    line_id: str
    text: str


class SetLineEmotionOp(_Op):
    op: Literal["set_line_emotion"] = "set_line_emotion"
    line_id: str
    emotion: str


class SetLineExaggerationOp(_Op):
    op: Literal["set_line_exaggeration"] = "set_line_exaggeration"
    line_id: str
    value: float | None  # null goes back to the emotion preset


class SetLineCfgWeightOp(_Op):
    op: Literal["set_line_cfg_weight"] = "set_line_cfg_weight"
    line_id: str
    value: float | None  # null goes back to the emotion preset


class SetAllowOverlapOp(_Op):
    op: Literal["set_allow_overlap"] = "set_allow_overlap"
    line_id: str
    value: bool


class SetActiveTakeOp(_Op):
    op: Literal["set_active_take"] = "set_active_take"
    line_id: str
    take_id: str | None  # null clears the active take


class StarTakeOp(_Op):
    op: Literal["star_take"] = "star_take"
    take_id: str
    starred: bool = True


LineEditOp = Annotated[
    AddLineOp
    | RemoveLineOp
    | SetLineTextOp
    | SetLineEmotionOp
    | SetLineExaggerationOp
    | SetLineCfgWeightOp
    | SetAllowOverlapOp
    | SetActiveTakeOp
    | StarTakeOp,
    Field(discriminator="op"),
]


class LineEditBatch(_Op):
    """Several ops applied as one undo step; all or nothing. Without a label a
    single op is a plain undo step named after the command."""

    label: str | None = Field(default=None, min_length=1)
    ops: list[LineEditOp] = Field(min_length=1)


def build_line_command(
    op: LineEditOp, *, known_emotions: Collection[str] | None = None
) -> Command:
    if isinstance(op, AddLineOp):
        return AddLine(
            op.text,
            op.emotion,
            line_id=op.line_id,
            position=op.position,
            known_emotions=known_emotions,
        )
    if isinstance(op, RemoveLineOp):
        return RemoveLine(op.line_id)
    if isinstance(op, SetLineTextOp):
        return SetLineText(op.line_id, op.text)
    if isinstance(op, SetLineEmotionOp):
        return SetLineEmotion(op.line_id, op.emotion, known_emotions=known_emotions)
    if isinstance(op, SetLineExaggerationOp):
        return SetLineExaggeration(op.line_id, op.value)
    if isinstance(op, SetLineCfgWeightOp):
        return SetLineCfgWeight(op.line_id, op.value)
    if isinstance(op, SetAllowOverlapOp):
        return SetAllowOverlap(op.line_id, op.value)
    if isinstance(op, SetActiveTakeOp):
        return SetActiveTake(op.line_id, op.take_id)
    if isinstance(op, StarTakeOp):
        return StarTake(op.take_id, op.starred)
    raise CommandError(f"unsupported edit {op!r}")
