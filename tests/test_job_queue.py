"""JobQueue: one GPU job at a time, reuse, cancel, retry, unload (M3-3).

Real queue thread, a FakeWorker and an in-memory FakeHost; no GPU, no project.
"""

import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from backend.project.session import SessionError
from backend.voice.chunking import chunk_seed
from backend.voice.fakehost import BASE_SEED, FakeHost
from backend.voice.fakeworker import FakeWorker
from backend.voice.jobqueue import JobError, JobQueue
from backend.voice.jobs import JobItem
from backend.voice.protocol import (
    CancelCommand,
    GenerateCommand,
    LoadCommand,
    UnloadCommand,
    WorkerCommand,
)

LINES = {
    "short": ("Hello there.",),
    "three": ("One.", "Two.", "Three."),
    "long": tuple(f"Sentence number {i}." for i in range(20)),
}

WAIT_S = 30.0


class MuteLoadWorker(FakeWorker):
    """Never answers the load command."""

    def send(self, command: WorkerCommand) -> None:
        if isinstance(command, LoadCommand):
            self.received.append(command)
            return
        super().send(command)


class MuteGenerateWorker(FakeWorker):
    """Loads, then swallows generate commands (a hung GPU)."""

    def send(self, command: WorkerCommand) -> None:
        if isinstance(command, GenerateCommand):
            self.received.append(command)
            return
        super().send(command)


class DeafWorker(FakeWorker):
    """Ignores cancel commands, so a cancelled job still ends with ``done``."""

    def send(self, command: WorkerCommand) -> None:
        if isinstance(command, CancelCommand):
            self.received.append(command)
            return
        super().send(command)


def generates(worker: FakeWorker) -> list[GenerateCommand]:
    return [c for c in worker.received if isinstance(c, GenerateCommand)]


def loads(worker: FakeWorker) -> list[WorkerCommand]:
    return [c for c in worker.received if isinstance(c, LoadCommand)]


@pytest.fixture
def host() -> FakeHost:
    return FakeHost(dict(LINES))


@pytest.fixture
def make(host: FakeHost) -> Iterator[Callable[..., JobQueue]]:
    created: list[JobQueue] = []

    def factory(worker: FakeWorker | None = None, **kwargs: float) -> JobQueue:
        queue = JobQueue(
            host,
            worker if worker is not None else FakeWorker(),
            model_version=lambda: "fake-1",
            poll_s=0.01,
            **kwargs,
        )
        created.append(queue)
        return queue

    yield factory
    for queue in created:
        queue.close()


def wait_until(condition: Callable[[], bool], timeout_s: float = WAIT_S) -> None:
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            pytest.fail("condition not met in time")
        time.sleep(0.005)


def job_of(queue: JobQueue, job_id: str) -> JobItem:
    return next(job for job in queue.status().jobs if job.id == job_id)


# --------------------------------------------------------------------------
# Generate, reuse, reroll
# --------------------------------------------------------------------------


def test_generate_a_short_line(host: FakeHost, make: Callable[..., JobQueue]) -> None:
    worker = FakeWorker()
    queue = make(worker)
    job = queue.submit("short")
    assert job.state == "queued"
    assert job.kind == "generate"
    done = queue.wait(job.id, WAIT_S)
    assert done.state == "done"
    assert done.take_id is not None
    assert not done.reused
    assert len(host.saved) == 1
    new, samples, rate = host.saved[0]
    assert new.seed == BASE_SEED
    assert samples.ndim == 1
    assert samples.size > 0
    assert rate == 24000
    assert [type(c) for c in worker.received] == [LoadCommand, GenerateCommand]
    command = generates(worker)[0]
    assert command.chunks == ("Hello there.",)
    assert command.seeds == (BASE_SEED,)
    assert not Path(command.output_path).exists()  # the temp file is gone


def test_a_long_line_goes_to_the_worker_in_pieces(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker()
    queue = make(worker)
    job = queue.submit("three")
    done = queue.wait(job.id, WAIT_S)
    assert done.state == "done"
    assert done.chunk_count == 3
    assert done.chunks_done == 3
    command = generates(worker)[0]
    assert command.chunks == LINES["three"]
    assert command.seeds == tuple(chunk_seed(BASE_SEED, i) for i in range(3))


def test_the_same_request_again_reuses_the_take_without_the_gpu(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker()
    queue = make(worker)
    first = queue.wait(queue.submit("short").id, WAIT_S)
    second = queue.submit("short")
    assert second.state == "reused"
    assert second.reused
    assert second.take_id == first.take_id
    assert len(generates(worker)) == 1
    assert len(host.saved) == 1


def test_reuse_does_not_start_the_worker(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    queue = make(FakeWorker())
    queue.wait(queue.submit("short").id, WAIT_S)
    worker = FakeWorker()
    other = make(worker)
    again = other.submit("short")
    assert again.state == "reused"
    assert not worker.alive
    assert worker.received == []


def test_reroll_makes_a_new_take_with_a_new_seed(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    queue = make(FakeWorker())
    first = queue.wait(queue.submit("short").id, WAIT_S)
    second = queue.wait(queue.submit("short", reroll=True).id, WAIT_S)
    assert second.state == "done"
    assert second.reroll
    assert second.take_id != first.take_id
    assert [new.seed for new, _, _ in host.saved] == [BASE_SEED, BASE_SEED + 1]


def test_the_worker_is_loaded_once_for_several_jobs(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker()
    queue = make(worker)
    for _ in range(3):
        queue.wait(queue.submit("short", reroll=True).id, WAIT_S)
    assert len(loads(worker)) == 1
    assert len(generates(worker)) == 3


def test_an_unknown_line_is_refused_at_once(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    queue = make(FakeWorker())
    with pytest.raises(SessionError):
        queue.submit("nope")
    assert queue.status().jobs == []


# --------------------------------------------------------------------------
# One at a time, in order
# --------------------------------------------------------------------------


def test_jobs_run_one_at_a_time_in_order(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker(step_delay_s=0.01)
    queue = make(worker)
    ids = [queue.submit("three", reroll=True).id for _ in range(3)]
    most_running = 0
    while True:
        jobs = queue.status().jobs
        most_running = max(
            most_running, sum(1 for j in jobs if j.state in ("running", "cancelling"))
        )
        if all(j.state == "done" for j in jobs) and len(jobs) == 3:
            break
        time.sleep(0.005)
    assert most_running == 1
    # Each job plans when its turn comes, so the seeds follow one another.
    assert [new.seed for new, _, _ in host.saved] == [
        BASE_SEED,
        BASE_SEED + 1,
        BASE_SEED + 2,
    ]
    assert [j.id for j in queue.status().jobs] == ids


def test_a_second_request_for_the_same_line_ends_up_reused(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker(step_delay_s=0.01)
    queue = make(worker)
    first = queue.submit("three")
    second = queue.submit("three")  # not reusable yet: the first is still queued
    assert second.state == "queued"
    queue.wait(first.id, WAIT_S)
    result = queue.wait(second.id, WAIT_S)
    assert result.state == "reused"
    assert len(generates(worker)) == 1


# --------------------------------------------------------------------------
# Cancel
# --------------------------------------------------------------------------


def test_cancel_a_queued_job(host: FakeHost, make: Callable[..., JobQueue]) -> None:
    worker = FakeWorker(step_delay_s=0.02)
    queue = make(worker)
    first = queue.submit("long")
    second = queue.submit("short", reroll=True)
    status = queue.cancel(second.id)
    assert next(j for j in status.jobs if j.id == second.id).state == "cancelled"
    queue.cancel(first.id)
    queue.wait(first.id, WAIT_S)
    assert all(g.job_id != second.id for g in generates(worker))


def test_cancel_a_running_job_between_pieces(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker(step_delay_s=0.02)
    queue = make(worker)
    job = queue.submit("long")
    wait_until(lambda: job_of(queue, job.id).chunks_done >= 1)
    status = queue.cancel(job.id)
    assert next(j for j in status.jobs if j.id == job.id).state in (
        "cancelling",
        "cancelled",
    )
    result = queue.wait(job.id, WAIT_S)
    assert result.state == "cancelled"
    assert result.take_id is None
    assert host.saved == []
    assert any(isinstance(c, CancelCommand) for c in worker.received)
    assert not worker.busy
    # The worker is free again.
    again = queue.wait(queue.submit("short").id, WAIT_S)
    assert again.state == "done"


def test_a_result_that_arrives_after_a_cancel_is_discarded(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = DeafWorker(step_delay_s=0.02)
    queue = make(worker)
    job = queue.submit("long")
    wait_until(lambda: job_of(queue, job.id).phase == "generating")
    queue.cancel(job.id)
    result = queue.wait(job.id, WAIT_S)
    assert result.state == "cancelled"
    assert host.saved == []
    assert not Path(generates(worker)[0].output_path).exists()


def test_cancel_errors(host: FakeHost, make: Callable[..., JobQueue]) -> None:
    queue = make(FakeWorker())
    with pytest.raises(JobError):
        queue.cancel("does-not-exist")
    done = queue.wait(queue.submit("short").id, WAIT_S)
    with pytest.raises(JobError):
        queue.cancel(done.id)


# --------------------------------------------------------------------------
# Failures and restarts
# --------------------------------------------------------------------------


def test_one_crash_restarts_the_worker_and_the_job_succeeds(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker(crash_on_chunk_index=1, crash_count=1)
    queue = make(worker)
    result = queue.wait(queue.submit("three").id, WAIT_S)
    assert result.state == "done"
    assert len(loads(worker)) == 2
    assert len(generates(worker)) == 2
    assert len(host.saved) == 1


def test_a_second_crash_fails_the_job_and_the_next_job_still_works(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker(crash_on_chunk_index=1, crash_count=2)
    queue = make(worker)
    result = queue.wait(queue.submit("three").id, WAIT_S)
    assert result.state == "failed"
    assert result.message is not None
    assert "exited" in result.message
    assert host.saved == []
    assert queue.status().worker == "failed"
    # One piece only, so the scripted crash at piece 1 does not trigger.
    after = queue.wait(queue.submit("short").id, WAIT_S)
    assert after.state == "done"
    assert queue.status().worker == "ready"


def test_a_job_error_from_the_worker_fails_the_job_without_a_retry(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker(fail_chunk_index=0)
    queue = make(worker)
    result = queue.wait(queue.submit("short").id, WAIT_S)
    assert result.state == "failed"
    assert result.message is not None
    assert "fake failure" in result.message
    assert len(generates(worker)) == 1
    assert host.saved == []


def test_a_failed_model_load_fails_the_job(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    queue = make(FakeWorker(fail_load="CUDA out of memory"))
    result = queue.wait(queue.submit("short").id, WAIT_S)
    assert result.state == "failed"
    assert result.message is not None
    assert "CUDA out of memory" in result.message
    status = queue.status()
    assert status.worker == "failed"
    assert status.worker_message is not None
    assert "CUDA out of memory" in status.worker_message


def test_a_load_that_never_finishes_times_out(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    queue = make(MuteLoadWorker(), load_timeout_s=0.3)
    result = queue.wait(queue.submit("short").id, WAIT_S)
    assert result.state == "failed"
    assert result.message is not None
    assert "loading" in result.message


def test_a_worker_that_stops_answering_is_restarted_once_then_fails(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = MuteGenerateWorker()
    queue = make(worker, stall_timeout_s=0.3)
    result = queue.wait(queue.submit("short").id, WAIT_S)
    assert result.state == "failed"
    assert result.message is not None
    assert "responding" in result.message
    assert len(generates(worker)) == 2
    assert host.saved == []


def test_a_model_version_mismatch_fails_the_job(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    queue = make(FakeWorker(model_version="something-else"))
    result = queue.wait(queue.submit("short").id, WAIT_S)
    assert result.state == "failed"
    assert result.message is not None
    assert "something-else" in result.message
    assert host.saved == []


def test_a_project_switch_fails_the_job_and_writes_nothing(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    queue = make(FakeWorker(step_delay_s=0.02))
    job = queue.submit("long")
    host.project = "project-2"
    result = queue.wait(job.id, WAIT_S)
    assert result.state == "failed"
    assert result.message is not None
    assert "project changed" in result.message
    assert host.saved == []


# --------------------------------------------------------------------------
# Unload, status, close
# --------------------------------------------------------------------------


def test_unload_frees_the_model_and_the_next_job_loads_again(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker()
    queue = make(worker)
    queue.wait(queue.submit("short").id, WAIT_S)
    unload = queue.wait(queue.submit_unload().id, WAIT_S)
    assert unload.state == "done"
    assert unload.kind == "unload"
    assert any(isinstance(c, UnloadCommand) for c in worker.received)
    assert queue.status().worker == "unloaded"
    queue.wait(queue.submit("short", reroll=True).id, WAIT_S)
    assert len(loads(worker)) == 2


def test_unload_with_nothing_started_does_not_start_the_worker(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker()
    queue = make(worker)
    unload = queue.wait(queue.submit_unload().id, WAIT_S)
    assert unload.state == "done"
    assert not worker.alive
    assert worker.received == []


def test_status_follows_the_worker(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    queue = make(FakeWorker())
    first = queue.status()
    assert first.worker == "stopped"
    assert not first.active
    assert first.model_version is None
    queue.wait(queue.submit("short").id, WAIT_S)
    second = queue.status()
    assert second.worker == "ready"
    assert not second.active
    assert second.model_version == "fake-1"


def test_close_cancels_everything_and_stops_the_worker(
    host: FakeHost, make: Callable[..., JobQueue]
) -> None:
    worker = FakeWorker(step_delay_s=0.02)
    queue = make(worker)
    first = queue.submit("long")
    second = queue.submit("short", reroll=True)
    wait_until(lambda: job_of(queue, first.id).chunks_done >= 1)
    queue.close()
    assert job_of(queue, first.id).state == "cancelled"
    assert job_of(queue, second.id).state == "cancelled"
    assert not worker.alive
    assert host.saved == []
    with pytest.raises(JobError):
        queue.submit("short")
    queue.close()  # twice is fine
