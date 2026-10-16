"""In-process stand-in for the GPU worker (M3-3), for tests. No GPU, no threads.

It speaks the same protocol as the real worker and writes real WAV files (a
sine tone whose pitch depends on the seed, so takes are distinguishable and
repeatable). Work advances one piece per ``next_event`` call that finds the
event queue empty, so a test decides exactly when a cancel arrives:

* a ``cancel`` sent before a step reaches the worker while that piece is being
  generated; the piece finishes (``progress``), then the job ends with
  ``cancelled`` and no file is written. Cancel wins over ``done``, also on the
  last piece (M3 decision 2).

Failure switches: ``fail_load`` (fatal error on load), ``fail_chunk_index``
(non-fatal error when that piece starts), ``crash_on_chunk_index`` with
``crash_count`` (the worker dies that many times when that piece starts, and
works after a restart once the count is used up), ``crash()``.
``step_delay_s`` makes every ``next_event`` call wait, so a threaded test can act
while a job is running.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile

from backend.voice.protocol import (
    CancelCommand,
    CancelledEvent,
    DoneEvent,
    ErrorEvent,
    GenerateCommand,
    LoadCommand,
    ProgressEvent,
    ReadyEvent,
    ShutdownCommand,
    UnloadCommand,
    UnloadedEvent,
    WorkerCommand,
    WorkerEvent,
)
from backend.voice.worker_client import WorkerError


@dataclass
class _Job:
    command: GenerateCommand
    chunks_done: int = 0
    cancel_requested: bool = False
    pieces: list[np.ndarray] = field(default_factory=list)


class FakeWorker:
    def __init__(
        self,
        *,
        model_version: str = "fake-1",
        sample_rate: int = 24000,
        seconds_per_chunk: float = 0.5,
        fail_load: str | None = None,
        fail_chunk_index: int | None = None,
        crash_on_chunk_index: int | None = None,
        crash_count: int = 1,
        step_delay_s: float = 0.0,
    ) -> None:
        self._model_version = model_version
        self._sample_rate = sample_rate
        self._seconds_per_chunk = seconds_per_chunk
        self._fail_load = fail_load
        self._fail_chunk_index = fail_chunk_index
        self._crash_on_chunk_index = crash_on_chunk_index
        self._crashes_left = crash_count
        self._step_delay_s = step_delay_s
        self.received: list[WorkerCommand] = []  # every command, for assertions
        self._alive = False
        self._loaded = False
        self._events: deque[WorkerEvent] = deque()
        self._job: _Job | None = None

    # ---- WorkerClient ------------------------------------------------------

    @property
    def alive(self) -> bool:
        return self._alive

    def start(self) -> None:
        if self._alive:
            return
        self._alive = True
        self._loaded = False
        self._job = None
        self._events.clear()

    def send(self, command: WorkerCommand) -> None:
        if not self._alive:
            raise WorkerError("the worker is not running")
        self.received.append(command)
        match command:
            case LoadCommand():
                self._on_load(command)
            case GenerateCommand():
                self._on_generate(command)
            case CancelCommand():
                job = self._job
                if job is not None and job.command.job_id == command.job_id:
                    job.cancel_requested = True
            case UnloadCommand():
                self._on_unload()
            case ShutdownCommand():
                self._alive = False
                self._loaded = False
                self._job = None

    def next_event(self, timeout_s: float = 0.0) -> WorkerEvent | None:
        del timeout_s  # a fake waits only for ``step_delay_s``
        if self._step_delay_s > 0:
            time.sleep(self._step_delay_s)
        if not self._events:
            self._step()
        return self._events.popleft() if self._events else None

    def close(self) -> None:
        self._alive = False
        self._loaded = False
        self._job = None

    # ---- test helpers ------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def busy(self) -> bool:
        return self._job is not None

    def crash(self) -> None:
        """Die like a crashed process: a fatal error event, then not alive."""
        job = self._job
        self._job = None
        self._alive = False
        self._loaded = False
        self._events.append(
            ErrorEvent(
                job_id=job.command.job_id if job is not None else None,
                message="worker process exited unexpectedly",
                fatal=True,
            )
        )

    # ---- internals ---------------------------------------------------------

    def _on_load(self, command: LoadCommand) -> None:
        if self._fail_load is not None:
            self._events.append(ErrorEvent(message=self._fail_load, fatal=True))
            self._alive = False
            return
        self._loaded = True
        self._events.append(
            ReadyEvent(
                model_version=self._model_version,
                sample_rate=self._sample_rate,
                device=command.device,
            )
        )

    def _on_generate(self, command: GenerateCommand) -> None:
        if not self._loaded:
            self._error(command.job_id, "the model is not loaded")
        elif self._job is not None:
            self._error(command.job_id, "the worker is busy with another job")
        else:
            self._job = _Job(command)

    def _on_unload(self) -> None:
        if self._job is not None:
            self._error(None, "cannot unload while a job is running")
            return
        self._loaded = False
        self._events.append(UnloadedEvent())

    def _error(self, job_id: str | None, message: str) -> None:
        self._events.append(ErrorEvent(job_id=job_id, message=message))

    def _step(self) -> None:
        """Generate the next piece of the running job."""
        job = self._job
        if job is None:
            return
        command = job.command
        index = job.chunks_done
        if self._crash_on_chunk_index == index and self._crashes_left > 0:
            self._crashes_left -= 1
            self.crash()
            return
        if self._fail_chunk_index == index:
            self._error(command.job_id, f"fake failure on piece {index}")
            self._job = None
            return
        job.pieces.append(self._tone(command.seeds[index]))
        job.chunks_done += 1
        count = len(command.chunks)
        self._events.append(
            ProgressEvent(
                job_id=command.job_id, chunks_done=job.chunks_done, chunk_count=count
            )
        )
        if job.cancel_requested:
            self._events.append(CancelledEvent(job_id=command.job_id))
            self._job = None
        elif job.chunks_done == count:
            self._finish(job)

    def _finish(self, job: _Job) -> None:
        command = job.command
        self._job = None
        samples = np.concatenate(job.pieces).astype(np.float32)
        path = Path(command.output_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            soundfile.write(
                str(path), samples, self._sample_rate, subtype="FLOAT", format="WAV"
            )
        except (OSError, RuntimeError) as exc:
            self._error(command.job_id, f"cannot write {path}: {exc}")
            return
        self._events.append(
            DoneEvent(
                job_id=command.job_id,
                output_path=command.output_path,
                sample_rate=self._sample_rate,
                duration_ms=round(samples.size * 1000 / self._sample_rate),
                chunk_count=len(command.chunks),
            )
        )

    def _tone(self, seed: int) -> np.ndarray:
        count = max(1, round(self._seconds_per_chunk * self._sample_rate))
        frequency = 220 + seed % 200
        t = np.arange(count) / self._sample_rate
        return (0.1 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)
