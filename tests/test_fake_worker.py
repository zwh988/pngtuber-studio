"""FakeWorker: the protocol as the job queue will see it (M3-3)."""

from pathlib import Path

import numpy as np
import pytest
import soundfile

from backend.voice.fakeworker import FakeWorker
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
    WorkerEvent,
)
from backend.voice.worker_client import WorkerClient, WorkerError


def drain(worker: FakeWorker, limit: int = 50) -> list[WorkerEvent]:
    events: list[WorkerEvent] = []
    for _ in range(limit):
        event = worker.next_event()
        if event is None:
            break
        events.append(event)
    return events


def generate(
    worker: FakeWorker,
    folder: Path,
    *,
    job_id: str = "j1",
    chunks: tuple[str, ...] = ("One.",),
    seeds: tuple[int, ...] | None = None,
) -> GenerateCommand:
    command = GenerateCommand(
        job_id=job_id,
        chunks=chunks,
        seeds=seeds if seeds is not None else tuple(range(1, len(chunks) + 1)),
        reference_path=str(folder / "ref.wav"),
        output_path=str(folder / "out" / f"{job_id}.wav"),
        exaggeration=0.5,
        cfg_weight=0.5,
    )
    worker.send(command)
    return command


@pytest.fixture
def worker() -> FakeWorker:
    fake = FakeWorker()
    fake.start()
    return fake


@pytest.fixture
def loaded(worker: FakeWorker) -> FakeWorker:
    worker.send(LoadCommand())
    drain(worker)
    return worker


def test_fake_worker_satisfies_the_client_interface() -> None:
    assert isinstance(FakeWorker(), WorkerClient)


def test_not_alive_until_started_and_send_is_refused() -> None:
    fake = FakeWorker()
    assert not fake.alive
    with pytest.raises(WorkerError):
        fake.send(LoadCommand())
    fake.start()
    assert fake.alive


def test_load_reports_the_model_version() -> None:
    fake = FakeWorker(model_version="chatterbox-test", sample_rate=22050)
    fake.start()
    fake.send(LoadCommand(device="cpu"))
    assert drain(fake) == [
        ReadyEvent(model_version="chatterbox-test", sample_rate=22050, device="cpu")
    ]
    assert fake.loaded


def test_no_event_when_idle() -> None:
    fake = FakeWorker()
    fake.start()
    assert fake.next_event() is None


def test_generate_before_load_is_an_error(
    worker: FakeWorker, tmp_path: Path
) -> None:
    generate(worker, tmp_path)
    events = drain(worker)
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].job_id == "j1"
    assert not events[0].fatal
    assert not worker.busy


def test_single_chunk_job_emits_progress_then_done(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    command = generate(loaded, tmp_path)
    events = drain(loaded)
    assert events[0] == ProgressEvent(job_id="j1", chunks_done=1, chunk_count=1)
    done = events[1]
    assert isinstance(done, DoneEvent)
    assert done.output_path == command.output_path
    assert done.chunk_count == 1
    assert len(events) == 2
    assert not loaded.busy


def test_done_file_is_a_mono_wav_that_matches_the_event(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    command = generate(loaded, tmp_path, chunks=("One.", "Two."))
    done = drain(loaded)[-1]
    assert isinstance(done, DoneEvent)
    samples, rate = soundfile.read(command.output_path, dtype="float32")
    assert rate == done.sample_rate == 24000
    assert samples.ndim == 1
    assert round(samples.size * 1000 / rate) == done.duration_ms
    assert done.duration_ms == 1000  # two pieces of 0.5 s


def test_multi_chunk_progress_counts_up(loaded: FakeWorker, tmp_path: Path) -> None:
    generate(loaded, tmp_path, chunks=("A.", "B.", "C."))
    events = drain(loaded)
    progress = [e for e in events if isinstance(e, ProgressEvent)]
    assert [e.chunks_done for e in progress] == [1, 2, 3]
    assert all(e.chunk_count == 3 for e in progress)
    assert isinstance(events[-1], DoneEvent)
    assert events[-1].chunk_count == 3


def test_same_seeds_give_same_audio_and_other_seeds_differ(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    first = generate(loaded, tmp_path, job_id="a", seeds=(5,))
    drain(loaded)
    second = generate(loaded, tmp_path, job_id="b", seeds=(5,))
    drain(loaded)
    other = generate(loaded, tmp_path, job_id="c", seeds=(6,))
    drain(loaded)
    a, _ = soundfile.read(first.output_path, dtype="float32")
    b, _ = soundfile.read(second.output_path, dtype="float32")
    c, _ = soundfile.read(other.output_path, dtype="float32")
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_cancel_between_pieces_stops_after_the_piece_in_flight(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    command = generate(loaded, tmp_path, chunks=("A.", "B.", "C."))
    assert loaded.next_event() == ProgressEvent(
        job_id="j1", chunks_done=1, chunk_count=3
    )
    loaded.send(CancelCommand(job_id="j1"))
    assert drain(loaded) == [
        ProgressEvent(job_id="j1", chunks_done=2, chunk_count=3),
        CancelledEvent(job_id="j1"),
    ]
    assert not Path(command.output_path).exists()
    assert not loaded.busy


def test_cancel_of_a_single_piece_job_discards_the_result(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    command = generate(loaded, tmp_path)
    loaded.send(CancelCommand(job_id="j1"))
    assert drain(loaded) == [
        ProgressEvent(job_id="j1", chunks_done=1, chunk_count=1),
        CancelledEvent(job_id="j1"),
    ]
    assert not Path(command.output_path).exists()


def test_worker_is_free_after_a_cancel(loaded: FakeWorker, tmp_path: Path) -> None:
    generate(loaded, tmp_path, job_id="a")
    loaded.send(CancelCommand(job_id="a"))
    drain(loaded)
    generate(loaded, tmp_path, job_id="b")
    assert isinstance(drain(loaded)[-1], DoneEvent)


def test_cancel_for_another_job_is_ignored(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    generate(loaded, tmp_path, job_id="a")
    loaded.send(CancelCommand(job_id="zzz"))
    assert isinstance(drain(loaded)[-1], DoneEvent)


def test_cancel_with_no_job_does_nothing(loaded: FakeWorker) -> None:
    loaded.send(CancelCommand(job_id="a"))
    assert drain(loaded) == []


def test_second_generate_while_busy_is_an_error_and_the_first_continues(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    generate(loaded, tmp_path, job_id="a", chunks=("A.", "B."))
    generate(loaded, tmp_path, job_id="b")
    events = drain(loaded)
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert [e.job_id for e in errors] == ["b"]
    dones = [e for e in events if isinstance(e, DoneEvent)]
    assert [e.job_id for e in dones] == ["a"]


def test_unload_then_generate_fails_until_loaded_again(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    loaded.send(UnloadCommand())
    assert drain(loaded) == [UnloadedEvent()]
    assert not loaded.loaded
    generate(loaded, tmp_path)
    assert isinstance(drain(loaded)[0], ErrorEvent)
    loaded.send(LoadCommand())
    assert isinstance(drain(loaded)[0], ReadyEvent)
    generate(loaded, tmp_path, job_id="j2")
    assert isinstance(drain(loaded)[-1], DoneEvent)


def test_unload_while_a_job_runs_is_an_error_and_the_job_finishes(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    generate(loaded, tmp_path)
    loaded.send(UnloadCommand())
    events = drain(loaded)
    assert any(isinstance(e, ErrorEvent) for e in events)
    assert isinstance(events[-1], DoneEvent)
    assert loaded.loaded


def test_failed_load_is_fatal() -> None:
    fake = FakeWorker(fail_load="CUDA out of memory")
    fake.start()
    fake.send(LoadCommand())
    events = drain(fake)
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].fatal
    assert "CUDA out of memory" in events[0].message
    assert not fake.alive


def test_a_failing_piece_ends_the_job_but_not_the_worker(tmp_path: Path) -> None:
    fake = FakeWorker(fail_chunk_index=1)
    fake.start()
    fake.send(LoadCommand())
    drain(fake)
    command = generate(fake, tmp_path, chunks=("A.", "B."))
    events = drain(fake)
    assert isinstance(events[0], ProgressEvent)
    assert isinstance(events[1], ErrorEvent)
    assert events[1].job_id == "j1"
    assert not events[1].fatal
    assert not Path(command.output_path).exists()
    assert fake.alive
    assert not fake.busy


def test_shutdown_stops_the_worker(loaded: FakeWorker) -> None:
    loaded.send(ShutdownCommand())
    assert not loaded.alive
    with pytest.raises(WorkerError):
        loaded.send(UnloadCommand())


def test_crash_during_a_job_is_a_fatal_error_for_that_job(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    generate(loaded, tmp_path, job_id="a", chunks=("A.", "B."))
    loaded.crash()
    events = drain(loaded)
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert events[0].fatal
    assert events[0].job_id == "a"
    assert not loaded.alive


def test_restart_after_a_crash_needs_a_new_load(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    loaded.crash()
    drain(loaded)
    loaded.start()
    assert loaded.alive
    assert not loaded.loaded
    generate(loaded, tmp_path)
    assert isinstance(drain(loaded)[0], ErrorEvent)


def test_received_records_every_command_in_order(
    loaded: FakeWorker, tmp_path: Path
) -> None:
    command = generate(loaded, tmp_path)
    cancel = CancelCommand(job_id="j1")
    loaded.send(cancel)
    assert loaded.received == [LoadCommand(), command, cancel]


def test_close_is_safe_twice(worker: FakeWorker) -> None:
    worker.close()
    worker.close()
    assert not worker.alive
