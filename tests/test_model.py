"""The voice model's files and the first-run download (M7 S3). No network: the
downloader is a fake, and the Hugging Face lookup reads a cache built in tmp_path."""

import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.project.session import Session
from backend.voice.engine import MODEL_MISSING_MESSAGE, ChatterboxEngine
from backend.voice.fakehost import FakeHost
from backend.voice.fakeworker import FakeWorker
from backend.voice.jobqueue import JobQueue
from backend.voice.model import (
    MODEL_BYTES,
    MODEL_FILES,
    MODEL_REPO,
    MODEL_REVISION,
    ModelManager,
    bytes_on_disk,
    describe_download_error,
    hf_lookup,
    model_folder,
    present_files,
)

NAMES = [f.name for f in MODEL_FILES]
SIZES = {f.name: f.size for f in MODEL_FILES}


class FakeCache:
    """Files in one folder; ``download`` writes a tiny file and reports the
    pinned size in a few steps. ``fail_on`` makes that file's download raise
    (once, unless ``fail_times`` says more)."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.downloaded: list[str] = []
        self.fail_on: str | None = None
        self.fail_times = 1
        self.gate: threading.Event | None = None  # holds the download until set
        self.reports: list[tuple[str, int]] = []

    def lookup(self, name: str) -> Path | None:
        path = self.folder / name
        return path if path.is_file() else None

    def download(self, name: str, report: Callable[[int], None]) -> None:
        size = SIZES[name]
        report(size // 2)
        self.reports.append((name, size // 2))
        if self.gate is not None:
            assert self.gate.wait(10)
        if name == self.fail_on and self.fail_times > 0:
            self.fail_times -= 1
            raise OSError("connection reset")
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / name).write_bytes(b"x")
        report(size)
        self.downloaded.append(name)

    def add(self, *names: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (self.folder / name).write_bytes(b"x")


@pytest.fixture
def cache(tmp_path: Path) -> FakeCache:
    return FakeCache(tmp_path / "snap")


@pytest.fixture
def manager(cache: FakeCache) -> ModelManager:
    return ModelManager(
        lookup=cache.lookup, download=cache.download, cache_dir_text="C:\\hf"
    )


# ---- pure ------------------------------------------------------------------


def test_the_pin_is_a_full_commit_and_the_files_have_sizes() -> None:
    assert len(MODEL_REVISION) == 40
    assert NAMES == [
        "ve.safetensors",
        "t3_cfg.safetensors",
        "s3gen.safetensors",
        "tokenizer.json",
        "conds.pt",
    ]
    assert MODEL_BYTES == sum(SIZES.values())
    assert 3_000_000_000 < MODEL_BYTES < 3_500_000_000


def test_model_folder_needs_every_file_in_one_folder(tmp_path: Path) -> None:
    all_here = {name: tmp_path / name for name in NAMES}
    assert model_folder(all_here) == tmp_path
    missing_one = dict(all_here)
    del missing_one["conds.pt"]
    assert model_folder(missing_one) is None
    split = dict(all_here)
    split["conds.pt"] = tmp_path / "other" / "conds.pt"
    assert model_folder(split) is None
    assert model_folder({}) is None


def test_present_files_keeps_only_found_ones(cache: FakeCache) -> None:
    cache.add("conds.pt", "tokenizer.json")
    assert sorted(present_files(cache.lookup)) == ["conds.pt", "tokenizer.json"]


def test_bytes_on_disk_counts_finished_files_and_caps_the_one_in_flight() -> None:
    present = {"ve.safetensors": Path("x")}
    assert bytes_on_disk(present, None, 0) == SIZES["ve.safetensors"]
    assert bytes_on_disk(present, "conds.pt", 1000) == SIZES["ve.safetensors"] + 1000
    assert bytes_on_disk(present, "conds.pt", 10**12) == (
        SIZES["ve.safetensors"] + SIZES["conds.pt"]
    )
    assert bytes_on_disk({}, "conds.pt", -5) == 0


def test_download_error_text_says_what_to_do() -> None:
    text = describe_download_error(OSError("connection reset\nmore detail"))
    assert "connection reset" in text
    assert "more detail" not in text
    assert "Retry" in text
    assert "kept" in text


# ---- the Hugging Face cache lookup (real function, cache in tmp_path) -------


def test_hf_lookup_finds_files_of_the_pinned_revision_only(tmp_path: Path) -> None:
    repo = tmp_path / ("models--" + MODEL_REPO.replace("/", "--"))
    pinned = repo / "snapshots" / MODEL_REVISION
    other = repo / "snapshots" / ("0" * 40)
    pinned.mkdir(parents=True)
    other.mkdir(parents=True)
    (pinned / "conds.pt").write_bytes(b"x")
    (other / "ve.safetensors").write_bytes(b"x")
    lookup = hf_lookup(tmp_path)
    assert lookup("conds.pt") == pinned / "conds.pt"
    assert lookup("ve.safetensors") is None  # only in another revision
    for name in NAMES:
        (pinned / name).write_bytes(b"x")
    assert model_folder(present_files(lookup)) == pinned


def test_hf_lookup_of_an_empty_cache_is_none(tmp_path: Path) -> None:
    assert present_files(hf_lookup(tmp_path)) == {}


# ---- the manager -----------------------------------------------------------


def test_status_when_nothing_is_on_disk(manager: ModelManager) -> None:
    status = manager.status()
    assert status.state == "missing"
    assert status.files_present == 0
    assert status.bytes_done == 0
    assert status.bytes_total == MODEL_BYTES
    assert status.cache_dir == "C:\\hf"
    assert status.revision == MODEL_REVISION
    assert not manager.ready()
    assert manager.folder() is None


def test_download_fetches_every_file_then_is_ready(
    manager: ModelManager, cache: FakeCache
) -> None:
    manager.start_download()
    manager.wait()
    assert cache.downloaded == NAMES
    status = manager.status()
    assert status.state == "ready"
    assert status.files_present == len(NAMES)
    assert status.bytes_done == MODEL_BYTES
    assert status.message is None
    assert manager.folder() == cache.folder


def test_files_already_on_disk_are_not_downloaded_again(
    manager: ModelManager, cache: FakeCache
) -> None:
    cache.add("ve.safetensors", "conds.pt")
    assert manager.status().bytes_done == SIZES["ve.safetensors"] + SIZES["conds.pt"]
    manager.start_download()
    manager.wait()
    assert cache.downloaded == ["t3_cfg.safetensors", "s3gen.safetensors", "tokenizer.json"]


def test_status_while_downloading_shows_the_file_in_flight(
    manager: ModelManager, cache: FakeCache
) -> None:
    cache.add("ve.safetensors")
    cache.gate = threading.Event()
    started = manager.start_download()
    assert started.state == "downloading"
    deadline_ok = False
    for _ in range(200):
        status = manager.status()
        if status.current_file == "t3_cfg.safetensors" and status.bytes_done > SIZES["ve.safetensors"]:
            deadline_ok = True
            break
        threading.Event().wait(0.01)
    assert deadline_ok
    assert status.state == "downloading"
    assert status.bytes_done == SIZES["ve.safetensors"] + SIZES["t3_cfg.safetensors"] // 2
    # a second press while it runs changes nothing
    assert manager.start_download().state == "downloading"
    cache.gate.set()
    manager.wait()
    assert manager.status().state == "ready"
    assert cache.downloaded.count("t3_cfg.safetensors") == 1


def test_a_failed_download_can_be_retried_and_keeps_finished_files(
    manager: ModelManager, cache: FakeCache
) -> None:
    cache.fail_on = "s3gen.safetensors"
    manager.start_download()
    manager.wait()
    failed = manager.status()
    assert failed.state == "failed"
    assert failed.message is not None and "connection reset" in failed.message
    assert failed.files_present == 2  # ve and t3_cfg are kept
    assert failed.current_file is None
    manager.start_download()
    manager.wait()
    assert manager.status().state == "ready"
    assert cache.downloaded == NAMES  # nothing fetched twice


def test_a_download_that_leaves_no_file_is_a_failure(cache: FakeCache) -> None:
    def no_file(name: str, report: Callable[[int], None]) -> None:
        report(1)

    manager = ModelManager(lookup=cache.lookup, download=no_file, cache_dir_text="x")
    manager.start_download()
    manager.wait()
    status = manager.status()
    assert status.state == "failed"
    assert status.message is not None and "ve.safetensors" in status.message


def test_start_when_ready_does_nothing(manager: ModelManager, cache: FakeCache) -> None:
    cache.add(*NAMES)
    assert manager.start_download().state == "ready"
    manager.wait()
    assert cache.downloaded == []


# ---- the engine loads from the folder, never from the network ---------------


def test_engine_without_the_model_fails_with_a_clear_message() -> None:
    engine = ChatterboxEngine(find_folder=lambda: None)
    with pytest.raises(RuntimeError, match="not downloaded"):
        engine.load("cpu")
    assert "start page" in MODEL_MISSING_MESSAGE


# ---- endpoints ---------------------------------------------------------------


@pytest.fixture
def queue() -> Iterator[JobQueue]:
    jobs = JobQueue(
        FakeHost({"short": ("Hello there.",)}),
        FakeWorker(step_delay_s=0.01),
        model_version=lambda: "fake-1",
        poll_s=0.01,
    )
    yield jobs
    jobs.close()


@pytest.fixture
def client(tmp_path: Path, queue: JobQueue, manager: ModelManager) -> TestClient:
    return TestClient(
        create_app(static_dir=tmp_path, session=Session(), jobs=queue, model=manager)
    )


def test_model_endpoint_reports_missing(client: TestClient) -> None:
    body = client.get("/api/voice/model").json()
    assert body["state"] == "missing"
    assert body["bytes_total"] == MODEL_BYTES
    assert body["cache_dir"] == "C:\\hf"


def test_generate_is_refused_until_the_model_is_downloaded(
    client: TestClient, manager: ModelManager
) -> None:
    refused = client.post("/api/voice/generate", json={"line_id": "short"})
    assert refused.status_code == 400
    assert "not downloaded" in refused.json()["detail"]
    assert client.post("/api/voice/reroll", json={"line_id": "short"}).status_code == 400
    assert client.post("/api/voice/model/download").json()["state"] in (
        "downloading",
        "ready",
    )
    manager.wait()
    assert client.get("/api/voice/model").json()["state"] == "ready"
    assert client.post("/api/voice/generate", json={"line_id": "short"}).status_code == 200


def test_an_app_given_only_a_test_queue_reports_ready(
    tmp_path: Path, queue: JobQueue
) -> None:
    client = TestClient(create_app(static_dir=tmp_path, session=Session(), jobs=queue))
    assert client.get("/api/voice/model").json()["state"] == "ready"
    assert client.post("/api/voice/model/download").json()["state"] == "ready"
