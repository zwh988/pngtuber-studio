"""Voice chain edits the API accepts, and how each becomes a Command (M4-1, S3c).

Pure: no file or network access. A batch of ops runs as one undo step
(``Session.edit_fx`` wraps it in ``CommandStack.group``).
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.project.commands import Command, CommandError
from backend.project.fx_commands import SetFxChain, SetGameAudioDb
from backend.project.schema import FxChain


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetFxChainOp(_Op):
    op: Literal["set_fx_chain"] = "set_fx_chain"
    # The whole chain, as the Voice FX tab holds it (a preset is sent the same way).
    chain: FxChain


class SetGameAudioDbOp(_Op):
    op: Literal["set_game_audio_db"] = "set_game_audio_db"
    db: float


FxEditOp = Annotated[SetFxChainOp | SetGameAudioDbOp, Field(discriminator="op")]


class FxEditBatch(_Op):
    """Voice chain edits applied together. One op without a label is a plain undo
    step; several ops (or a label) undo together, all or nothing."""

    ops: list[FxEditOp] = Field(min_length=1)
    label: str | None = Field(default=None, min_length=1)


def build_fx_command(op: FxEditOp) -> Command:
    if isinstance(op, SetFxChainOp):
        return SetFxChain(op.chain)
    if isinstance(op, SetGameAudioDbOp):
        return SetGameAudioDb(op.db)
    raise CommandError(f"unsupported edit {op!r}")
