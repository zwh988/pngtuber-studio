"""Voice job endpoints (M3-3), with a fake host and a fake worker."""

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.session import Session
from backend.voice.fakehost import FakeHost
from backend.voice.fakeworker import FakeWorker
from backend.voice.jobqueue import JobQueue


@pytest.fixture
def queue() -> Iterator[JobQueue]:
    host = FakeHost(
        {"short": ("Hello there.",), "long": tuple(f"Piece {i}." for i in range(20))}
    )
    jobs = JobQueue(
        host,
        FakeWorker(step_delay_s=0.01),
        model_version=lambda: "fake-1",
        poll_s=0.01,
    )
    yield jobs
    jobs.close()


@pytest.fixture
def client(tmp_path: Path, queue: JobQueue) -> TestClient:
    return TestClient(create_app(static_dir=tmp_path, session=Session(), jobs=queue))


def poll_job(client: TestClient, job_id: str, *, until: set[str]) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = client.get("/api/voice/jobs").json()
        job = next(j for j in status["jobs"] if j["id"] == job_id)
        if job["state"] in until:
            return job
        time.sleep(0.01)
    pytest.fail("job did not reach the expected state")


def test_jobs_start_empty(client: TestClient) -> None:
    body = client.get("/api/voice/jobs").json()
    assert body["jobs"] == []
    assert body["active"] is False
    assert body["worker"] == "stopped"


def test_generate_then_poll_until_done(client: TestClient) -> None:
    response = client.post("/api/voice/generate", json={"line_id": "short"})
    assert response.status_code == 200
    job = response.json()
    assert job["state"] == "queued"
    assert job["kind"] == "generate"
    final = poll_job(client, job["id"], until={"done", "failed"})
    assert final["state"] == "done"
    assert final["take_id"]
    status = client.get("/api/voice/jobs").json()
    assert status["worker"] == "ready"
    assert status["model_version"] == "fake-1"


def test_generating_again_is_reported_as_reused(client: TestClient) -> None:
    first = client.post("/api/voice/generate", json={"line_id": "short"}).json()
    poll_job(client, first["id"], until={"done"})
    second = client.post("/api/voice/generate", json={"line_id": "short"}).json()
    assert second["state"] == "reused"
    assert second["reused"] is True
    assert second["take_id"]


def test_reroll(client: TestClient) -> None:
    first = client.post("/api/voice/generate", json={"line_id": "short"}).json()
    first_done = poll_job(client, first["id"], until={"done"})
    rerolled = client.post("/api/voice/reroll", json={"line_id": "short"}).json()
    assert rerolled["reroll"] is True
    final = poll_job(client, rerolled["id"], until={"done", "failed"})
    assert final["state"] == "done"
    assert final["take_id"]
    assert final["take_id"] != first_done["take_id"]


def test_an_unknown_line_is_a_400_with_the_reason(client: TestClient) -> None:
    response = client.post("/api/voice/generate", json={"line_id": "nope"})
    assert response.status_code == 400
    assert "unknown line" in response.json()["detail"]
    assert client.post("/api/voice/reroll", json={"line_id": "nope"}).status_code == 400


def test_cancel_a_running_job(client: TestClient) -> None:
    job = client.post("/api/voice/generate", json={"line_id": "long"}).json()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status = client.get("/api/voice/jobs").json()
        current = next(j for j in status["jobs"] if j["id"] == job["id"])
        if current["chunks_done"] >= 1:
            break
        time.sleep(0.01)
    response = client.post("/api/voice/jobs/cancel", json={"job_id": job["id"]})
    assert response.status_code == 200
    final = poll_job(client, job["id"], until={"cancelled", "done", "failed"})
    assert final["state"] == "cancelled"


def test_cancel_of_an_unknown_job_is_a_400(client: TestClient) -> None:
    response = client.post("/api/voice/jobs/cancel", json={"job_id": "nope"})
    assert response.status_code == 400


def test_unload_endpoint(client: TestClient) -> None:
    first = client.post("/api/voice/generate", json={"line_id": "short"}).json()
    poll_job(client, first["id"], until={"done"})
    unload = client.post("/api/voice/worker/unload").json()
    assert unload["kind"] == "unload"
    final = poll_job(client, unload["id"], until={"done", "failed"})
    assert final["state"] == "done"
    assert client.get("/api/voice/jobs").json()["worker"] == "unloaded"


def test_the_default_app_has_an_idle_real_queue(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=tmp_path, session=Session()))
    body = client.get("/api/voice/jobs").json()
    assert body["worker"] == "stopped"
    assert body["jobs"] == []
    response = client.post("/api/voice/generate", json={"line_id": "a" * 12})
    assert response.status_code == 400  # no project is open; no worker was started
