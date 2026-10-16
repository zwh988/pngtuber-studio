"""Worker protocol (M3-3): JSON-lines messages between backend and GPU worker.

Pure: no I/O, no GPU. The backend writes one JSON object per line to the worker's
stdin (commands) and reads one per line from its stdout (events). Every message
has a ``type`` tag. Audio never travels over the pipe: the worker writes the
finished take to ``output_path`` and reports it in the ``done`` event.

The worker decides nothing about keys or seeds. It gets the text pieces and one
seed per piece (``chunk_seed``), generates them in order, and joins them (S4d).
Cancel takes effect between pieces (M3 decision 2).
"""

from typing import TYPE_CHECKING, Annotated, Literal, Self, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from backend.voice.chunking import chunk_seed

if TYPE_CHECKING:
    from backend.voice.generation import GenerationPlan


_T = TypeVar("_T")


class ProtocolError(ValueError):
    """A line is not a valid protocol message."""


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------
# Commands (backend to worker)
# --------------------------------------------------------------------------


class LoadCommand(_Message):
    """Load the model. The worker answers ``ready`` (or a fatal ``error``)."""

    type: Literal["load"] = "load"
    device: str = Field(default="cuda", min_length=1)


class GenerateCommand(_Message):
    """Generate one take: ``chunks[i]`` with seed ``seeds[i]``, joined, written
    to ``output_path`` as mono float32 WAV."""

    type: Literal["generate"] = "generate"
    job_id: str = Field(min_length=1)
    chunks: tuple[str, ...] = Field(min_length=1)
    seeds: tuple[int, ...] = Field(min_length=1)
    reference_path: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    exaggeration: float = Field(ge=0, allow_inf_nan=False)
    cfg_weight: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _check_pieces(self) -> Self:
        if len(self.chunks) != len(self.seeds):
            raise ValueError("chunks and seeds must have the same length")
        if any(not chunk.strip() for chunk in self.chunks):
            raise ValueError("chunks must not be blank")
        if any(seed < 0 for seed in self.seeds):
            raise ValueError("seeds must not be negative")
        return self


class CancelCommand(_Message):
    """Stop the named job after the piece in flight. Ignored for any other job."""

    type: Literal["cancel"] = "cancel"
    job_id: str = Field(min_length=1)


class UnloadCommand(_Message):
    """Free the model (and its VRAM). The worker answers ``unloaded``."""

    type: Literal["unload"] = "unload"


class ShutdownCommand(_Message):
    """Exit the worker process."""

    type: Literal["shutdown"] = "shutdown"


WorkerCommand = (
    LoadCommand | GenerateCommand | CancelCommand | UnloadCommand | ShutdownCommand
)


# --------------------------------------------------------------------------
# Events (worker to backend)
# --------------------------------------------------------------------------


class ReadyEvent(_Message):
    """The model is loaded. ``model_version`` goes into every raw cache key."""

    type: Literal["ready"] = "ready"
    model_version: str = Field(min_length=1)
    sample_rate: int = Field(gt=0)
    device: str = Field(min_length=1)


class ProgressEvent(_Message):
    """One more piece of the job is finished."""

    type: Literal["progress"] = "progress"
    job_id: str = Field(min_length=1)
    chunks_done: int = Field(ge=0)
    chunk_count: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_counts(self) -> Self:
        if self.chunks_done > self.chunk_count:
            raise ValueError("chunks_done must not exceed chunk_count")
        return self


class DoneEvent(_Message):
    """The job finished and the take audio is at ``output_path``."""

    type: Literal["done"] = "done"
    job_id: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    sample_rate: int = Field(gt=0)
    duration_ms: int = Field(ge=0)
    chunk_count: int = Field(ge=1)


class CancelledEvent(_Message):
    """The job stopped because of a cancel. No output file was written."""

    type: Literal["cancelled"] = "cancelled"
    job_id: str = Field(min_length=1)


class UnloadedEvent(_Message):
    type: Literal["unloaded"] = "unloaded"


class ErrorEvent(_Message):
    """Something failed. ``job_id`` is None for errors outside a job. ``fatal``
    means the worker is exiting and must be restarted."""

    type: Literal["error"] = "error"
    job_id: str | None = None
    message: str = Field(min_length=1)
    fatal: bool = False


WorkerEvent = (
    ReadyEvent
    | ProgressEvent
    | DoneEvent
    | CancelledEvent
    | UnloadedEvent
    | ErrorEvent
)

_COMMAND_ADAPTER: TypeAdapter[WorkerCommand] = TypeAdapter(
    Annotated[WorkerCommand, Field(discriminator="type")]
)
_EVENT_ADAPTER: TypeAdapter[WorkerEvent] = TypeAdapter(
    Annotated[WorkerEvent, Field(discriminator="type")]
)


# --------------------------------------------------------------------------
# Encoding and decoding
# --------------------------------------------------------------------------


def encode_message(message: WorkerCommand | WorkerEvent) -> str:
    """One JSON object on one line, newline-terminated. JSON escapes newlines
    inside strings, so a line is never split."""
    return message.model_dump_json() + "\n"


def decode_command(line: str) -> WorkerCommand:
    return _decode(_COMMAND_ADAPTER, line, "command")


def decode_event(line: str) -> WorkerEvent:
    return _decode(_EVENT_ADAPTER, line, "event")


def _decode(adapter: TypeAdapter[_T], line: str, kind: str) -> _T:
    text = line.strip()
    if not text:
        raise ProtocolError(f"empty {kind} line")
    try:
        return adapter.validate_json(text)
    except ValidationError as exc:
        raise ProtocolError(f"invalid {kind}: {_describe(exc)}") from exc


def _describe(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "invalid message"
    first = errors[0]
    where = ".".join(str(part) for part in first["loc"])
    message = str(first["msg"])
    return f"{where}: {message}" if where else message


# --------------------------------------------------------------------------
# From a generation plan to a command
# --------------------------------------------------------------------------


def build_generate_command(
    job_id: str, plan: "GenerationPlan", output_path: str
) -> GenerateCommand:
    """The worker command for a plan: chunk ``i`` uses ``chunk_seed(seed, i)``,
    so chunk 0 keeps the take seed."""
    seed = plan.new_take.seed
    return GenerateCommand(
        job_id=job_id,
        chunks=plan.chunks,
        seeds=tuple(chunk_seed(seed, index) for index in range(len(plan.chunks))),
        reference_path=plan.reference_path,
        output_path=output_path,
        exaggeration=plan.new_take.exaggeration,
        cfg_weight=plan.new_take.cfg_weight,
    )
