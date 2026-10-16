"""The generation queue (M3-3): one GPU job at a time, cancel, restart on crash.

``JobQueue.submit`` plans a line with the open project (``GenerationHost``) and
reuses an existing take when the raw key matches (rule 3: no GPU time, and the
worker is not even started). Otherwise it queues a job. One background thread runs
the jobs in order against a ``WorkerClient``; it is the only thread that touches
the worker, so a cancel from the API reaches the worker through the job's state.

A queued job plans again when its turn comes, so rapid rerolls get one seed after
another and a repeated request ends up reusing the take its twin just made. Every
host call carries the ``project_key`` seen at submit time, so a job can never write
into a project opened after it was requested.

Per job: start and load the worker if needed (the model then stays warm), send the
generate command, wait for ``done``, read the WAV and store the take. A fatal worker
error, or a worker that stops answering, restarts the worker once and retries the
job; a second failure ends it. A cancel before the job starts removes it; a cancel
while it runs is sent to the worker (it stops after the piece in flight, M3 decision
2) and a result that still arrives is discarded (no take is written).
"""

import logging
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import numpy as np
import soundfile

from backend.project.schema import new_id
from backend.project.session import SessionError
from backend.voice.generation import GenerationPlan
from backend.voice.jobs import (
    ACTIVE_STATES,
    TERMINAL_STATES,
    JobItem,
    JobKind,
    JobState,
    JobStatus,
    WorkerState,
    finished_to_forget,
)
from backend.voice.protocol import (
    CancelCommand,
    CancelledEvent,
    DoneEvent,
    ErrorEvent,
    LoadCommand,
    ProgressEvent,
    ReadyEvent,
    UnloadCommand,
    UnloadedEvent,
    WorkerEvent,
    build_generate_command,
)
from backend.voice.takes import AddTakeResult, NewTake
from backend.voice.worker_client import WorkerClient, WorkerError

_log = logging.getLogger(__name__)

UNLOAD_TIMEOUT_S = 60.0
CLOSE_JOIN_S = 20.0
RETRY_SUFFIX = "~2"  # worker job id of the second attempt, so stale events differ


class JobError(Exception):
    """A user-facing problem with the queue (unknown or finished job, closed)."""


class GenerationHost(Protocol):
    """What the queue needs from the open project (``Session`` provides it)."""

    def project_key(self) -> str | None:
        """Identifies the open project, or None when none is open."""

    def plan_generation(
        self,
        line_id: str,
        *,
        model_version: str,
        reroll: bool = False,
        project_key: str | None = None,
    ) -> GenerationPlan:
        """Plan one generation (no GPU, no writes)."""

    def reuse_take(
        self,
        new: NewTake,
        *,
        make_active: bool = True,
        project_key: str | None = None,
    ) -> AddTakeResult | None:
        """Reuse an existing take with the same raw key, or return None."""

    def add_take(
        self,
        new: NewTake,
        samples: np.ndarray,
        sample_rate: int,
        *,
        make_active: bool = True,
        project_key: str | None = None,
    ) -> AddTakeResult:
        """Store a generated take."""


@dataclass
class _Job:
    id: str
    kind: JobKind
    line_id: str | None
    reroll: bool
    project_key: str | None
    state: JobState = "queued"
    phase: str = "waiting"
    chunks_done: int = 0
    chunk_count: int = 0
    reused: bool = False
    take_id: str | None = None
    message: str | None = None
    cancel_requested: bool = False
    cancel_sent: bool = False


def _remove(path: Path) -> None:
    """Delete a temp file; a file that cannot be deleted is left for the OS."""
    with suppress(OSError):
        path.unlink(missing_ok=True)


class _Step(Enum):
    CONTINUE = "continue"  # keep waiting for events
    FINISHED = "finished"  # the job reached a final state
    CRASHED = "crashed"  # the worker died or stalled; maybe retry


class JobQueue:
    def __init__(
        self,
        host: GenerationHost,
        worker: WorkerClient,
        *,
        model_version: Callable[[], str],
        work_dir: Path | None = None,
        device: str = "cuda",
        load_timeout_s: float = 900.0,
        stall_timeout_s: float = 300.0,
        poll_s: float = 0.1,
    ) -> None:
        self._host = host
        self._worker = worker
        self._model_version = model_version
        self._work_dir = (
            work_dir
            if work_dir is not None
            else Path(tempfile.gettempdir()) / "PNGtuberStudio-jobs"
        )
        self._device = device
        self._load_timeout_s = load_timeout_s
        self._stall_timeout_s = stall_timeout_s
        self._poll_s = poll_s
        self._cond = threading.Condition()
        self._jobs: dict[str, _Job] = {}
        self._order: list[str] = []  # every known job id, oldest first
        self._pending: deque[str] = deque()  # queued job ids
        self._closing = False
        self._thread: threading.Thread | None = None
        self._worker_state: WorkerState = "stopped"
        self._worker_message: str | None = None
        self._loaded_version: str | None = None
        self._crash_message = ""

    # ---- API (any thread) --------------------------------------------------

    def submit(self, line_id: str, *, reroll: bool = False) -> JobItem:
        """Generate (or reroll) a line. An existing take with the same key is
        reused at once; otherwise a job is queued. Raises ``SessionError`` when
        the line cannot be planned (unknown line, no voice reference, ...)."""
        self._require_open()
        key = self._host.project_key()
        plan = self._host.plan_generation(
            line_id,
            model_version=self._model_version(),
            reroll=reroll,
            project_key=key,
        )
        reused = self._host.reuse_take(plan.new_take, project_key=key)
        with self._cond:
            self._require_open()
            job = _Job(
                id=new_id(),
                kind="generate",
                line_id=line_id,
                reroll=reroll,
                project_key=key,
                chunk_count=len(plan.chunks),
            )
            if reused is not None:
                job.state = "reused"
                job.phase = "finished"
                job.reused = True
                job.take_id = reused.take.id
                job.chunks_done = job.chunk_count
            self._register(job)
            if reused is None:
                self._pending.append(job.id)
            item = self._item(job)  # a snapshot before the thread can touch it
            self._cond.notify_all()
        if reused is None:
            self._ensure_thread()
        return item

    def submit_unload(self) -> JobItem:
        """Free the model's VRAM once the jobs before this one are done."""
        self._require_open()
        with self._cond:
            self._require_open()
            job = _Job(
                id=new_id(), kind="unload", line_id=None, reroll=False, project_key=None
            )
            self._register(job)
            self._pending.append(job.id)
            item = self._item(job)
            self._cond.notify_all()
        self._ensure_thread()
        return item

    def cancel(self, job_id: str) -> JobStatus:
        """Cancel a job: a queued one is dropped, a running one stops after the
        piece in flight. Raises ``JobError`` for an unknown or finished job."""
        with self._cond:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError(f"unknown job id {job_id!r}")
            if job.state in TERMINAL_STATES:
                raise JobError("that job is already finished")
            self._cancel_locked(job)
            return self._status_locked()

    def status(self) -> JobStatus:
        with self._cond:
            return self._status_locked()

    def wait(self, job_id: str, timeout_s: float = 30.0) -> JobItem:
        """Wait until the job is over (or the timeout passes) and return it."""
        with self._cond:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobError(f"unknown job id {job_id!r}")
            self._cond.wait_for(
                lambda: job.state in TERMINAL_STATES, timeout=timeout_s
            )
            return self._item(job)

    def close(self) -> None:
        """Cancel everything, stop the thread and the GPU worker."""
        with self._cond:
            self._closing = True
            for job in list(self._jobs.values()):
                if job.state in ACTIVE_STATES:
                    self._cancel_locked(job)
            self._cond.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=CLOSE_JOIN_S)
        self._worker.close()
        with self._cond:
            self._worker_state = "stopped"
            self._loaded_version = None

    # ---- bookkeeping (call with the lock held unless noted) ----------------

    def _require_open(self) -> None:
        if self._closing:
            raise JobError("the generation queue is closed")

    def _register(self, job: _Job) -> None:
        self._jobs[job.id] = job
        self._order.append(job.id)
        finished = {j.id for j in self._jobs.values() if j.state in TERMINAL_STATES}
        for job_id in finished_to_forget(self._order, finished):
            del self._jobs[job_id]
            self._order.remove(job_id)

    def _item(self, job: _Job) -> JobItem:
        return JobItem(
            id=job.id,
            kind=job.kind,
            line_id=job.line_id,
            reroll=job.reroll,
            state=job.state,
            phase=job.phase,
            chunks_done=job.chunks_done,
            chunk_count=job.chunk_count,
            reused=job.reused,
            take_id=job.take_id,
            message=job.message,
        )

    def _status_locked(self) -> JobStatus:
        state = self._worker_state
        if state in ("ready", "loading") and not self._worker.alive:
            state = "stopped"
        return JobStatus(
            jobs=[self._item(self._jobs[job_id]) for job_id in self._order],
            active=any(j.state in ACTIVE_STATES for j in self._jobs.values()),
            worker=state,
            model_version=self._loaded_version if state == "ready" else None,
            worker_message=self._worker_message,
        )

    def _cancel_locked(self, job: _Job) -> None:
        if job.state == "queued":
            with suppress(ValueError):
                self._pending.remove(job.id)
            job.state = "cancelled"
            job.phase = "finished"
        elif job.state == "running" and job.kind == "generate":
            job.cancel_requested = True
            job.state = "cancelling"
        # A running unload is quick and cannot be cancelled.
        self._cond.notify_all()

    def _set_worker(
        self,
        state: WorkerState,
        *,
        message: str | None = None,
        version: str | None = None,
    ) -> None:
        with self._cond:
            self._worker_state = state
            self._worker_message = message
            self._loaded_version = version if state == "ready" else None

    def _set_phase(self, job: _Job, phase: str) -> None:
        with self._cond:
            job.phase = phase

    def _finish(
        self,
        job: _Job,
        state: JobState,
        *,
        take_id: str | None = None,
        message: str | None = None,
        reused: bool = False,
    ) -> None:
        with self._cond:
            job.state = state
            job.phase = "finished"
            job.take_id = take_id
            job.message = message
            job.reused = reused
            if state in ("done", "reused") and job.kind == "generate":
                job.chunks_done = job.chunk_count
            self._cond.notify_all()

    # ---- the queue thread --------------------------------------------------

    def _ensure_thread(self) -> None:
        with self._cond:
            if self._closing:
                return
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._thread_main, name="generation-queue", daemon=True
            )
            self._thread.start()

    def _thread_main(self) -> None:
        while True:
            with self._cond:
                while not self._closing and not self._pending:
                    self._cond.wait()
                if self._closing:
                    return
                job = self._jobs.get(self._pending.popleft())
            if job is None:
                continue
            try:
                self._process(job)
            # An unexpected bug fails this job; the queue thread must keep running.
            except Exception as exc:  # noqa: BLE001
                _log.exception("generation queue: unexpected error")
                self._finish(job, "failed", message=f"internal error: {exc}")

    def _process(self, job: _Job) -> None:
        with self._cond:
            if job.state != "queued":
                return  # cancelled while it waited
            job.state = "running"
        if job.kind == "unload":
            self._process_unload(job)
            return
        line_id = job.line_id
        if line_id is None:
            self._finish(job, "failed", message="the job has no line")
            return
        try:
            plan = self._host.plan_generation(
                line_id,
                model_version=self._model_version(),
                reroll=job.reroll,
                project_key=job.project_key,
            )
            reused = self._host.reuse_take(plan.new_take, project_key=job.project_key)
        except SessionError as exc:
            self._finish(job, "failed", message=str(exc))
            return
        with self._cond:
            job.chunk_count = len(plan.chunks)
        if reused is not None:  # a job before this one made the same take
            self._finish(job, "reused", take_id=reused.take.id, reused=True)
            return
        for attempt in (1, 2):
            if self._attempt(job, plan, attempt) is not _Step.CRASHED:
                return
            if job.cancel_requested or self._closing:
                self._finish(job, "cancelled")  # never restart for a cancelled job
                return
            _log.warning(
                "voice worker failed (attempt %d): %s", attempt, self._crash_message
            )
        self._finish(
            job,
            "failed",
            message=f"the voice worker failed twice: {self._crash_message}",
        )

    def _attempt(self, job: _Job, plan: GenerationPlan, attempt: int) -> _Step:
        crash = self._ensure_ready(job)
        if crash is not None:
            self._crash_message = crash
            return _Step.CRASHED
        if job.cancel_requested:
            self._finish(job, "cancelled")
            return _Step.FINISHED
        planned = plan.new_take.model_version
        loaded = self._loaded_version
        if loaded != planned:
            self._finish(
                job,
                "failed",
                message=f"the worker's model ({loaded}) is not the planned ({planned})",
            )
            return _Step.FINISHED
        worker_job_id = job.id if attempt == 1 else f"{job.id}{RETRY_SUFFIX}"
        output = self._work_dir / f"{worker_job_id}.wav"
        try:
            self._work_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            message = f"cannot create {self._work_dir}: {exc}"
            self._finish(job, "failed", message=message)
            return _Step.FINISHED
        try:
            self._worker.send(build_generate_command(worker_job_id, plan, str(output)))
            self._set_phase(job, "generating")
            return self._wait_for_result(job, plan, worker_job_id, output)
        except WorkerError as exc:
            self._crash_message = str(exc)
            self._mark_dead(self._crash_message)
            return _Step.CRASHED
        finally:
            _remove(output)  # safety net for the paths that never reach _complete

    def _wait_for_result(
        self, job: _Job, plan: GenerationPlan, worker_job_id: str, output: Path
    ) -> _Step:
        last_sign_of_life = time.monotonic()
        while True:
            self._send_cancel_if_requested(job, worker_job_id)
            event = self._worker.next_event(self._poll_s)
            if event is None:
                if not self._worker.alive:
                    return self._crashed("the voice worker stopped unexpectedly")
                if time.monotonic() - last_sign_of_life > self._stall_timeout_s:
                    return self._crashed("the voice worker stopped responding")
                continue
            last_sign_of_life = time.monotonic()
            step = self._on_event(job, plan, worker_job_id, output, event)
            if step is not _Step.CONTINUE:
                return step

    def _crashed(self, message: str) -> _Step:
        self._crash_message = message
        self._mark_dead(message)
        return _Step.CRASHED

    def _send_cancel_if_requested(self, job: _Job, worker_job_id: str) -> None:
        with self._cond:
            wanted = job.cancel_requested and not job.cancel_sent
            if wanted:
                job.cancel_sent = True
        if wanted:
            self._worker.send(CancelCommand(job_id=worker_job_id))

    def _on_event(
        self,
        job: _Job,
        plan: GenerationPlan,
        worker_job_id: str,
        output: Path,
        event: WorkerEvent,
    ) -> _Step:
        if isinstance(event, ErrorEvent) and event.fatal:
            return self._crashed(event.message)
        if getattr(event, "job_id", None) != worker_job_id:
            return _Step.CONTINUE  # stale or unrelated
        if isinstance(event, ProgressEvent):
            with self._cond:
                job.chunks_done = event.chunks_done
            return _Step.CONTINUE
        if isinstance(event, CancelledEvent):
            self._finish(job, "cancelled")
            return _Step.FINISHED
        if isinstance(event, ErrorEvent):
            self._finish(job, "failed", message=event.message)
            return _Step.FINISHED
        if isinstance(event, DoneEvent):
            self._complete(job, plan, event, output)
            return _Step.FINISHED
        return _Step.CONTINUE

    def _complete(
        self, job: _Job, plan: GenerationPlan, done: DoneEvent, output: Path
    ) -> None:
        # The temp file goes before the job reaches a final state, so nobody who
        # sees the job over can still find its audio on disk.
        if job.cancel_requested:  # the result arrived after the cancel: discard
            _remove(output)
            self._finish(job, "cancelled")
            return
        self._set_phase(job, "storing")
        try:
            samples, rate = soundfile.read(str(output), dtype="float32")
            _remove(output)  # the audio is in memory now
            if rate != done.sample_rate:
                raise ValueError(f"sample rate {rate} is not {done.sample_rate}")
            result = self._host.add_take(
                plan.new_take, samples, rate, project_key=job.project_key
            )
        except (OSError, RuntimeError, ValueError, SessionError) as exc:
            _remove(output)
            self._finish(job, "failed", message=f"could not store the take: {exc}")
            return
        self._finish(
            job,
            "reused" if result.reused else "done",
            take_id=result.take.id,
            reused=result.reused,
        )

    # ---- the worker's state ------------------------------------------------

    def _drain_stale(self) -> None:
        """Drop events nobody is waiting for (for example from a dead worker)."""
        while self._worker.next_event(0.0) is not None:
            pass

    def _mark_dead(self, message: str) -> None:
        self._set_worker("failed", message=message)
        with suppress(Exception):
            self._worker.close()

    def _ensure_ready(self, job: _Job) -> str | None:
        """Start the worker and load the model if needed. None when it is ready,
        otherwise a message describing the failure."""
        self._drain_stale()
        with self._cond:
            ready = self._worker_state == "ready"
        if ready and self._worker.alive:
            return None
        self._set_phase(job, "loading")
        try:
            if not self._worker.alive:
                self._set_worker("stopped")
                self._worker.start()
            self._set_worker("loading")
            self._worker.send(LoadCommand(device=self._device))
        except WorkerError as exc:
            self._set_worker("failed", message=str(exc))
            return str(exc)
        deadline = time.monotonic() + self._load_timeout_s
        while True:
            event = self._worker.next_event(self._poll_s)
            if isinstance(event, ReadyEvent):
                self._set_worker("ready", version=event.model_version)
                return None
            if isinstance(event, ErrorEvent) and event.fatal:
                self._mark_dead(event.message)
                return event.message
            if event is None:
                if not self._worker.alive:
                    message = "the voice worker stopped while loading the model"
                    self._mark_dead(message)
                    return message
                if time.monotonic() > deadline:
                    message = "timed out loading the model"
                    self._mark_dead(message)
                    return message

    def _process_unload(self, job: _Job) -> None:
        self._set_phase(job, "unloading")
        with self._cond:
            ready = self._worker_state == "ready"
        if not (ready and self._worker.alive):
            self._finish(job, "done")  # nothing is loaded
            return
        self._drain_stale()
        try:
            self._worker.send(UnloadCommand())
        except WorkerError as exc:
            self._mark_dead(str(exc))
            self._finish(job, "failed", message=str(exc))
            return
        deadline = time.monotonic() + UNLOAD_TIMEOUT_S
        while time.monotonic() < deadline:
            event = self._worker.next_event(self._poll_s)
            if isinstance(event, UnloadedEvent):
                self._set_worker("unloaded")
                self._finish(job, "done")
                return
            if isinstance(event, ErrorEvent) and event.fatal:
                self._mark_dead(event.message)
                self._finish(job, "failed", message=event.message)
                return
            if event is None and not self._worker.alive:
                message = "the voice worker stopped while unloading"
                self._mark_dead(message)
                self._finish(job, "failed", message=message)
                return
        self._mark_dead("timed out unloading the model")
        self._finish(job, "failed", message="timed out unloading the model")
