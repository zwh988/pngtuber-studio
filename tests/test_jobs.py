"""Job status models and the pure pruning rule (M3-3)."""

from backend.voice.jobs import KEEP_FINISHED, JobStatus, finished_to_forget


def test_the_oldest_finished_jobs_are_forgotten_first() -> None:
    order = ["a", "b", "c", "d", "e", "f"]
    assert finished_to_forget(order, {"a", "b", "c", "d"}, keep=2) == ["a", "b"]


def test_nothing_is_forgotten_within_the_limit() -> None:
    assert finished_to_forget(["a", "b"], {"a", "b"}, keep=2) == []
    assert finished_to_forget([], set(), keep=0) == []


def test_active_jobs_are_never_forgotten() -> None:
    order = ["a", "b", "c"]
    assert finished_to_forget(order, {"b"}, keep=0) == ["b"]
    assert finished_to_forget(order, set(), keep=0) == []


def test_the_default_limit_is_applied() -> None:
    order = [f"j{i}" for i in range(KEEP_FINISHED + 3)]
    assert finished_to_forget(order, set(order)) == order[:3]


def test_an_empty_status_is_idle_and_stopped() -> None:
    status = JobStatus()
    assert status.jobs == []
    assert status.active is False
    assert status.worker == "stopped"
    assert status.model_version is None
    assert status.worker_message is None
