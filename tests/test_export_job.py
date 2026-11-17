"""Export job (M6-7): the manager with a fake host and fake steps, and the endpoints."""

import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.export.errors import ExportCancelled, ExportError
from backend.export.job import (
    ExportManager,
    ExportRequest,
    estimate_left,
    list_files,
)
from backend.export.preflight import PreflightIssue, PreflightReport
from backend.project.session import Session


def report(errors: int = 0, warnings: int = 0) -> PreflightReport:
    issues = [PreflightIssue(severity="error", kind="e", message="broken") for _ in range(errors)]
    issues += [PreflightIssue(severity="warning", kind="w", message="careful") for _ in range(warnings)]
    return PreflightReport(ok=errors == 0, error_count=errors, warning_count=warnings, issues=issues)


class FakeHost:
    def __init__(self, preflight: PreflightReport | None = None) -> None:
        self.key: str | None = "proj"
        self.preflight = preflight or report()
        self.inputs_taken = 0

    def project_key(self) -> str | None:
        return self.key

    def export_preflight(self, tools_problem: str | None = None) -> PreflightReport:
        return self.preflight

    def export_inputs(self) -> Any:
        self.inputs_taken += 1
        return "inputs"

    def processed_take_path(self, take_id: str, stretch: float = 1.0) -> Path | None:
        return None

    def aligned_raw_take(self, take_id: str, stretch: float = 1.0) -> tuple[np.ndarray, int] | None:
        return None


class FakeResult:
    class render:
        frames = 600

    class fmt:
        fps = 60


def manager(host: FakeHost, run: Any, **kw: Any) -> ExportManager:
    return ExportManager(host, ffmpeg=lambda: Path("ff.exe"), tools_problem=lambda: None, run=run, **kw)


def writes_a_file(inputs: Any, folder: Path, **kw: Any) -> Any:
    folder.mkdir(parents=True)
    (folder / "final_1080p.mp4").write_bytes(b"12345")
    kw["report"]("render", 0.5)
    return FakeResult()


def test_estimate_left() -> None:
    assert estimate_left(10, 0.5) == pytest.approx(10)
    assert estimate_left(10, 0.25) == pytest.approx(30)
    assert estimate_left(10, 0.01) is None and estimate_left(10, 1.0) is None


def test_a_successful_export(tmp_path: Path) -> None:
    host = FakeHost()
    exports = manager(host, writes_a_file)
    started = exports.start(ExportRequest(), tmp_path / "exports")
    assert started.state in ("running", "done") and started.folder is not None
    done = exports.wait()
    assert done.state == "done" and done.fraction == 1.0 and done.message is None
    assert done.files[0].name == "final_1080p.mp4" and done.files[0].bytes == 5
    assert done.video_ms == 10_000 and host.inputs_taken == 1
    assert Path(done.folder or "").parent == tmp_path / "exports"


def test_options_reach_the_steps(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def capture(inputs: Any, folder: Path, **kw: Any) -> Any:
        seen.update(kw)
        return writes_a_file(inputs, folder, **kw)

    unloaded = []
    exports = manager(FakeHost(), capture, unload_voice=lambda: unloaded.append(1))
    exports.start(
        ExportRequest(include_overlay=True, include_raw_links=False, limit_seconds=1.5, unload_voice=True),
        tmp_path,
    )
    exports.wait()
    opts = seen["options"]
    assert (opts.include_overlay, opts.include_raw_links, opts.limit_ms) == (True, False, 1500)
    assert unloaded == [1] and seen["ffmpeg"] == Path("ff.exe")


def test_preflight_errors_block_and_warnings_need_confirming(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="1 error"):
        manager(FakeHost(report(errors=1)), writes_a_file).start(ExportRequest(), tmp_path)
    warned = manager(FakeHost(report(warnings=2)), writes_a_file)
    with pytest.raises(ExportError, match="2 warning"):
        warned.start(ExportRequest(), tmp_path)
    warned.start(ExportRequest(accept_warnings=True), tmp_path)
    assert warned.wait().state == "done"


def test_refusals(tmp_path: Path) -> None:
    with pytest.raises(ExportError, match="voice generation"):
        manager(FakeHost(), writes_a_file, voice_busy=lambda: True).start(ExportRequest(), tmp_path)
    closed = FakeHost()
    closed.key = None
    with pytest.raises(ExportError, match="no project"):
        manager(closed, writes_a_file).start(ExportRequest(), tmp_path)
    with pytest.raises(ExportError, match="folder not found"):
        manager(FakeHost(), writes_a_file).start(ExportRequest(folder=str(tmp_path / "nope")), tmp_path)
    with pytest.raises(ExportError, match="no export is running"):
        manager(FakeHost(), writes_a_file).cancel()


def test_cancel_marks_the_folder_incomplete(tmp_path: Path) -> None:
    gate = threading.Event()

    def slow(inputs: Any, folder: Path, **kw: Any) -> Any:
        folder.mkdir(parents=True)
        (folder / "voice_raw.wav").write_bytes(b"x")
        kw["report"]("render", 0.4)
        gate.set()
        while not kw["should_stop"]():
            threading.Event().wait(0.01)
        raise ExportCancelled("export cancelled")

    exports = manager(FakeHost(), slow)
    exports.start(ExportRequest(), tmp_path)
    assert gate.wait(5)
    with pytest.raises(ExportError, match="already running"):
        exports.start(ExportRequest(), tmp_path)
    running = exports.status()
    assert running.state == "running" and running.stage == "render" and running.fraction == 0.4
    exports.cancel()
    done = exports.wait()
    assert done.state == "cancelled" and done.message == "Export cancelled."
    assert done.folder is not None and done.folder.endswith(" (incomplete)")
    assert (Path(done.folder) / "voice_raw.wav").read_bytes() == b"x"  # nothing deleted


def test_a_failure_keeps_the_message_and_the_files(tmp_path: Path) -> None:
    def broken(inputs: Any, folder: Path, **kw: Any) -> Any:
        folder.mkdir(parents=True)
        raise ExportError("ffmpeg failed (exit code 1)")

    exports = manager(FakeHost(), broken)
    exports.start(ExportRequest(), tmp_path)
    done = exports.wait()
    assert done.state == "failed" and "ffmpeg failed" in (done.message or "")
    assert (done.folder or "").endswith(" (incomplete)")
    nothing = manager(FakeHost(), lambda inputs, folder, **kw: (_ for _ in ()).throw(ExportError("early")))
    nothing.start(ExportRequest(), tmp_path / "other")
    assert nothing.wait().folder is None  # nothing was written: no folder to show


def test_closing_the_project_stops_the_takes(tmp_path: Path) -> None:
    host = FakeHost()

    def uses_takes(inputs: Any, folder: Path, **kw: Any) -> Any:
        host.key = "another"
        kw["processed_for"](type("Cue", (), {"take_id": "t", "stretch": 1.0, "line_text": "hi"})())
        return FakeResult()

    exports = manager(host, uses_takes)
    exports.start(ExportRequest(), tmp_path)
    done = exports.wait()
    assert done.state == "failed" and "closed" in (done.message or "")


def test_list_files(tmp_path: Path) -> None:
    (tmp_path / "lines").mkdir()
    (tmp_path / "lines" / "a.wav").write_bytes(b"1")
    (tmp_path / "b.mp4").write_bytes(b"12")
    names = [(f.name, f.bytes, f.files) for f in list_files(tmp_path)]
    assert names == [("lines/", None, 1), ("b.mp4", 2, None)]
    assert list_files(tmp_path / "missing") == []


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def test_endpoints(tmp_path: Path) -> None:
    session = Session(probe=fake_probe)
    client = TestClient(create_app(session=session, export_tools=lambda: None, export_run=writes_a_file))
    idle = client.get("/api/export/status").json()
    assert idle["state"] == "idle" and idle["defaults"] is None
    assert client.post("/api/export/start", json={}).status_code == 400  # no project
    session.new_project(str(tmp_path), "Rack")
    defaults = client.get("/api/export/status").json()["defaults"]
    assert defaults["folder"] == str(tmp_path / "Rack" / "exports")
    assert (defaults["include_overlay"], defaults["include_raw_links"], defaults["height"]) == (False, True, 1080)
    refused = client.post("/api/export/start", json={"accept_warnings": True})
    assert refused.status_code == 400 and "no_clips" not in refused.json()["detail"]
    assert "error" in refused.json()["detail"]  # the empty project has no clips
    assert client.post("/api/export/cancel").status_code == 400
    assert client.post("/api/export/start", json={"limit_seconds": -1}).status_code == 422


def test_generation_is_refused_while_exporting(tmp_path: Path) -> None:
    gate, release = threading.Event(), threading.Event()

    def held(inputs: Any, folder: Path, **kw: Any) -> Any:
        gate.set()
        release.wait(5)
        return FakeResult()

    session = Session(probe=fake_probe)
    session.new_project(str(tmp_path), "Rack")
    app = create_app(session=session, export_tools=lambda: None, export_run=held)
    client = TestClient(app)
    # No clips: start the manager directly past the pre-flight with a fake host.
    exports_status = client.get("/api/export/status").json()
    assert exports_status["state"] == "idle"
    session_preflight = session.export_preflight
    session.export_preflight = lambda tools_problem=None: report()  # type: ignore[method-assign]
    try:
        assert client.post("/api/export/start", json={}).json()["state"] in ("running", "done")
        assert gate.wait(5)
        refused = client.post("/api/voice/generate", json={"line_id": "a" * 12})
        assert refused.status_code == 400 and "export is running" in refused.json()["detail"]
    finally:
        release.set()
        session.export_preflight = session_preflight  # type: ignore[method-assign]
    for _ in range(100):
        if client.get("/api/export/status").json()["state"] != "running":
            break
        threading.Event().wait(0.05)
    assert client.get("/api/export/status").json()["state"] == "done"
