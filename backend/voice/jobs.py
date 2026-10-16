"""Job and worker status models for the generation queue (M3-3). Pure.

The status endpoint returns a ``JobStatus`` the UI polls about every 500 ms while
something is active (M3 decision 4).
"""

from collections.abc import Collection, Sequence
from typing import Literal

from pydantic import BaseModel, Field

JobKind = Literal["generate", "unload"]
JobState = Literal[
    "queued", "running", "cancelling", "done", "cancelled", "failed", "reused"
]
WorkerState = Literal["stopped", "loading", "ready", "unloaded", "failed"]

ACTIVE_STATES: frozenset[str] = frozenset({"queued", "running", "cancelling"})
TERMINAL_STATES: frozenset[str] = frozenset({"done", "cancelled", "failed", "reused"})
KEEP_FINISHED = 30  # finished jobs the status keeps, newest last


class JobItem(BaseModel):
    id: str
    kind: JobKind
    line_id: str | None = None  # None for an unload
    reroll: bool = False
    state: JobState
    # What the job is doing now: waiting, loading, generating, storing, unloading.
    phase: str = "waiting"
    chunks_done: int = 0
    chunk_count: int = 0
    # True when no GPU time was spent: an existing take was reused (rule 3).
    reused: bool = False
    take_id: str | None = None
    message: str | None = None  # why a job failed


class JobStatus(BaseModel):
    jobs: list[JobItem] = Field(default_factory=list)  # oldest first
    active: bool = False  # a job is queued or running
    worker: WorkerState = "stopped"
    model_version: str | None = None  # set while the model is loaded
    worker_message: str | None = None  # why the last start or load failed


def finished_to_forget(
    order: Sequence[str], finished: Collection[str], keep: int = KEEP_FINISHED
) -> list[str]:
    """Ids of the oldest finished jobs beyond the newest ``keep``.

    ``order`` is every known job id, oldest first; ``finished`` the ones that
    are over. Active jobs are never forgotten.
    """
    finished_set = set(finished)
    over = [job_id for job_id in order if job_id in finished_set]
    extra = len(over) - keep
    return over[:extra] if extra > 0 else []
