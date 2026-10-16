"""The GPU worker's logic (M3-3), apart from stdio and from torch.

``WorkerLoop`` turns commands into events using an ``Engine``. It generates the
pieces of a job in order, checks for a cancel after each piece (M3 decision 2:
the piece in flight finishes, then the job stops and nothing is written), joins
the pieces with ``crossfade_join`` and writes the take atomically.

``request_cancel`` is safe to call from another thread while a job runs.
"""

import os
import threading
import traceback
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

import numpy as np
import soundfile

from backend.voice.chunking import crossfade_join
from backend.voice.engine import Engine, EngineInfo
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

Emit = Callable[[WorkerEvent], None]


def describe_error(exc: BaseException) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


class WorkerLoop:
    def __init__(self, engine: Engine, emit: Emit) -> None:
        self._engine = engine
        self._emit = emit
        self._info: EngineInfo | None = None
        self._device = "cuda"
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    def request_cancel(self, job_id: str) -> None:
        """Ask for ``job_id`` to stop after the piece in flight."""
        with self._lock:
            self._cancelled.add(job_id)

    def handle(self, command: WorkerCommand) -> bool:
        """Run one command. False means the worker should exit."""
        match command:
            case LoadCommand():
                return self._load(command)
            case GenerateCommand():
                self._generate(command)
            case CancelCommand():
                self.request_cancel(command.job_id)
            case UnloadCommand():
                self._unload()
            case ShutdownCommand():
                self._release()
                return False
        return True

    # ---- commands ----------------------------------------------------------

    def _load(self, command: LoadCommand) -> bool:
        if self._info is None:
            self._device = command.device
            try:
                self._info = self._engine.load(command.device)
            # Any load failure must become a fatal error event, not a dead pipe.
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                self._emit(
                    ErrorEvent(
                        message=f"could not load the model: {describe_error(exc)}",
                        fatal=True,
                    )
                )
                return False
            try:
                self._engine.warm_up()
            except Exception:  # noqa: BLE001 - warm-up is optional
                traceback.print_exc()  # a failed warm-up only slows the first job
        self._emit(
            ReadyEvent(
                model_version=self._info.model_version,
                sample_rate=self._info.sample_rate,
                device=self._device,
            )
        )
        return True

    def _unload(self) -> None:
        self._release()
        self._emit(UnloadedEvent())

    def _release(self) -> None:
        self._info = None
        try:
            self._engine.unload()
        except Exception:  # noqa: BLE001 - freeing the model is best effort
            traceback.print_exc()

    def _generate(self, command: GenerateCommand) -> None:
        job_id = command.job_id
        info = self._info
        if info is None:
            self._emit(ErrorEvent(job_id=job_id, message="the model is not loaded"))
            return
        count = len(command.chunks)
        pieces: list[np.ndarray] = []
        try:
            for index, (text, seed) in enumerate(
                zip(command.chunks, command.seeds, strict=True)
            ):
                samples = self._engine.synthesize(
                    text,
                    seed=seed,
                    reference_path=command.reference_path,
                    exaggeration=command.exaggeration,
                    cfg_weight=command.cfg_weight,
                )
                pieces.append(_checked(samples, index))
                self._emit(
                    ProgressEvent(
                        job_id=job_id, chunks_done=index + 1, chunk_count=count
                    )
                )
                if self._take_cancel(job_id):
                    self._emit(CancelledEvent(job_id=job_id))
                    return
            audio = (
                pieces[0] if count == 1 else crossfade_join(pieces, info.sample_rate)
            )
            _write_wav(Path(command.output_path), audio, info.sample_rate)
        # Whatever the engine raises ends this job only; the worker stays up.
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._emit(ErrorEvent(job_id=job_id, message=describe_error(exc)))
            return
        finally:
            self._take_cancel(job_id)  # forget a cancel that came too late
        self._emit(
            DoneEvent(
                job_id=job_id,
                output_path=command.output_path,
                sample_rate=info.sample_rate,
                duration_ms=round(audio.size * 1000 / info.sample_rate),
                chunk_count=count,
            )
        )

    def _take_cancel(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self._cancelled:
                self._cancelled.discard(job_id)
                return True
            return False


def _checked(samples: np.ndarray, index: int) -> np.ndarray:
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(f"piece {index} is not a non-empty mono array")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"piece {index} contains NaN or infinite values")
    return array


def _write_wav(dest: Path, samples: np.ndarray, sample_rate: int) -> None:
    """Mono float32 WAV, written to a temp file and moved into place, so a crash
    or cancel never leaves a half-written take under its real name."""
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        soundfile.write(str(tmp), samples, sample_rate, subtype="FLOAT", format="WAV")
        os.replace(tmp, dest)
    except BaseException:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
