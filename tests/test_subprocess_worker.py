"""SubprocessWorker end to end with the tone engine: no GPU, a real process (M3-3)."""

import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
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
    WorkerEvent,
)
from backend.voice.subprocess_worker import SubprocessWorker, default_worker_command
from backend.voice.worker_client import WorkerClient, WorkerError

TIMEOUT_S = 40.0


def tone_command(*extra: str) -> list[str]:
    return [*default_worker_command(), "--engine", "tone", *extra]


def wait_for(
    worker: SubprocessWorker, found: Callable[[WorkerEvent], bool]
) -> list[WorkerEvent]:
    """Events up to and including the first one for which ``found`` is true."""
    events: list[WorkerEvent] = []
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        event = worker.next_event(0.2)
        if event is None:
            continue
        events.append(event)
        if found(event):
            return events
    pytest.fail(f"timed out; events so far: {events}")


def make_generate(
    folder: Path, *, job_id: str = "j1", chunks: tuple[str, ...] = ("Hello there.",)
) -> GenerateCommand:
    return GenerateCommand(
        job_id=job_id,
        chunks=chunks,
        seeds=tuple(range(1, len(chunks) + 1)),
        reference_path=str(folder / "ref.wav"),
        output_path=str(folder / "out" / f"{job_id}.wav"),
        exaggeration=0.5,
        cfg_weight=0.5,
    )


@pytest.fixture
def make_worker(tmp_path: Path) -> Iterator[Callable[..., SubprocessWorker]]:
    created: list[SubprocessWorker] = []

    def factory(*extra: str, command: list[str] | None = None) -> SubprocessWorker:
        worker = SubprocessWorker(
            command=command if command is not None else tone_command(*extra),
            log_path=tmp_path / "logs" / "worker.log",
        )
        created.append(worker)
        return worker

    yield factory
    for worker in created:
        worker.close()


def test_satisfies_the_client_interface() -> None:
    assert isinstance(SubprocessWorker(), WorkerClient)


def test_not_alive_before_start_and_send_is_refused() -> None:
    worker = SubprocessWorker(command=tone_command())
    assert not worker.alive
    with pytest.raises(WorkerError):
        worker.send(LoadCommand())


def test_load_then_generate_end_to_end(
    make_worker: Callable[..., SubprocessWorker], tmp_path: Path
) -> None:
    worker = make_worker()
    worker.start()
    assert worker.alive
    worker.send(LoadCommand())
    ready = wait_for(worker, lambda e: isinstance(e, ReadyEvent))[-1]
    assert isinstance(ready, ReadyEvent)
    assert ready.model_version.startswith("tone-engine")
    command = make_generate(tmp_path, chunks=("First piece.", "Second piece."))
    worker.send(command)
    events = wait_for(worker, lambda e: isinstance(e, DoneEvent))
    progress = [e for e in events if isinstance(e, ProgressEvent)]
    assert [e.chunks_done for e in progress] == [1, 2]
    done = events[-1]
    assert isinstance(done, DoneEvent)
    samples, rate = soundfile.read(command.output_path, dtype="float32")
    assert rate == done.sample_rate
    assert samples.ndim == 1
    assert round(samples.size * 1000 / rate) == done.duration_ms


def test_cancel_reaches_a_running_job(
    make_worker: Callable[..., SubprocessWorker], tmp_path: Path
) -> None:
    worker = make_worker("--tone-delay", "0.3")
    worker.start()
    worker.send(LoadCommand())
    wait_for(worker, lambda e: isinstance(e, ReadyEvent))
    command = make_generate(tmp_path, chunks=("A.", "B.", "C.", "D."))
    worker.send(command)
    wait_for(worker, lambda e: isinstance(e, ProgressEvent))
    worker.send(CancelCommand(job_id="j1"))
    events = wait_for(
        worker, lambda e: isinstance(e, CancelledEvent | DoneEvent | ErrorEvent)
    )
    assert isinstance(events[-1], CancelledEvent)
    assert not Path(command.output_path).exists()


def test_stray_prints_do_not_corrupt_the_protocol(
    make_worker: Callable[..., SubprocessWorker], tmp_path: Path
) -> None:
    worker = make_worker("--tone-noisy")
    worker.start()
    worker.send(LoadCommand())
    wait_for(worker, lambda e: isinstance(e, ReadyEvent))
    worker.send(make_generate(tmp_path))
    wait_for(worker, lambda e: isinstance(e, DoneEvent))
    assert worker.bad_line_count == 0
    worker.close()
    log = (tmp_path / "logs" / "worker.log").read_text(encoding="utf-8")
    assert "tone engine: loading" in log
    assert "--- voice worker start" in log


def test_close_stops_the_process_and_is_safe_twice(
    make_worker: Callable[..., SubprocessWorker],
) -> None:
    worker = make_worker()
    worker.start()
    worker.send(LoadCommand())
    wait_for(worker, lambda e: isinstance(e, ReadyEvent))
    worker.close()
    assert not worker.alive
    worker.close()
    with pytest.raises(WorkerError):
        worker.send(LoadCommand())


def test_start_after_close_runs_a_new_process(
    make_worker: Callable[..., SubprocessWorker],
) -> None:
    worker = make_worker()
    worker.start()
    worker.close()
    worker.start()
    assert worker.alive
    worker.send(LoadCommand())
    wait_for(worker, lambda e: isinstance(e, ReadyEvent))


def test_a_crash_is_a_fatal_error_naming_the_running_job(
    make_worker: Callable[..., SubprocessWorker], tmp_path: Path
) -> None:
    script = "import sys; sys.stdin.readline(); sys.exit(3)"
    worker = make_worker(command=[sys.executable, "-c", script])
    worker.start()
    worker.send(make_generate(tmp_path, job_id="doomed"))
    events = wait_for(worker, lambda e: isinstance(e, ErrorEvent))
    error = events[-1]
    assert isinstance(error, ErrorEvent)
    assert error.fatal
    assert error.job_id == "doomed"
    assert "3" in error.message
    assert not worker.alive


def test_restart_after_a_crash(
    make_worker: Callable[..., SubprocessWorker],
) -> None:
    worker = make_worker(command=[sys.executable, "-c", "import sys; sys.exit(1)"])
    worker.start()
    wait_for(worker, lambda e: isinstance(e, ErrorEvent))
    assert not worker.alive
    worker.start()  # a new process (it exits at once again)
    wait_for(worker, lambda e: isinstance(e, ErrorEvent))


def test_a_command_that_cannot_start_is_a_worker_error() -> None:
    worker = SubprocessWorker(command=["this-program-does-not-exist-xyz"])
    with pytest.raises(WorkerError):
        worker.start()
    assert not worker.alive
