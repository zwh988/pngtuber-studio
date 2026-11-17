"""One export at a time, on a background thread (M6-7).

``ExportManager.start`` checks the pre-flight (errors block; warnings need
``accept_warnings``), refuses while voice generation is busy (rule 7: one GPU job at a
time), picks a new folder and runs ``run_export`` on a thread. The UI polls ``status``
(stage, fraction, elapsed and an estimate of the time left) and can ``cancel``. A failed
or cancelled export's folder is renamed with " (incomplete)"; nothing is deleted.

The manager reaches the project only through the ``ExportHost`` protocol, so tests can
drive it with a fake host and a fake ``run`` function.
"""

import os
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

import numpy as np
from pydantic import BaseModel, Field

from backend.export.bundle import export_folder_name, mark_incomplete, unique_folder
from backend.export.errors import ExportCancelled, ExportError
from backend.export.pipeline import (
    ExportInputs,
    ExportOptions,
    ExportResult,
    run_export,
)
from backend.export.preflight import PreflightReport
from backend.export.voicetrack import VoiceCue

ExportState = Literal["idle", "running", "done", "failed", "cancelled"]
ETA_MIN_FRACTION = 0.03  # below this the estimate is too wild to show
EXPORTS_DIR = "exports"


class ExportRequest(BaseModel):
    """``POST /api/export/start``. ``folder`` is the parent folder (default: the
    project's ``exports``); the export gets its own dated folder inside it."""

    folder: str | None = None
    include_overlay: bool = False
    include_raw_links: bool = True
    unload_voice: bool = False
    limit_seconds: float | None = Field(default=None, gt=0)
    accept_warnings: bool = False


class ExportFile(BaseModel):
    name: str
    bytes: int | None = None  # None for a folder
    files: int | None = None  # files inside a folder


class ExportDefaults(BaseModel):
    """The project's export settings, shown as the screen's starting choices."""

    folder: str
    include_overlay: bool
    include_raw_links: bool
    unload_voice: bool
    height: int
    fps: str


class ExportStatus(BaseModel):
    """``GET /api/export/status``."""

    state: ExportState = "idle"
    stage: str = ""
    fraction: float = 0.0
    elapsed_s: float = 0.0
    eta_s: float | None = None
    folder: str | None = None
    message: str | None = None
    files: list[ExportFile] = Field(default_factory=list)
    video_ms: int | None = None  # length of the exported video
    defaults: ExportDefaults | None = None


class ExportHost(Protocol):
    def project_key(self) -> str | None: ...
    def export_preflight(self, tools_problem: str | None = None) -> PreflightReport: ...
    def export_inputs(self) -> ExportInputs: ...
    def processed_take_path(self, take_id: str, stretch: float = 1.0) -> Path | None: ...
    def aligned_raw_take(self, take_id: str, stretch: float = 1.0) -> tuple[np.ndarray, int] | None: ...


RunFn = Callable[..., ExportResult]


def estimate_left(elapsed_s: float, fraction: float) -> float | None:
    """Seconds left at the current pace; None until there is enough progress."""
    if fraction < ETA_MIN_FRACTION or fraction >= 1.0 or elapsed_s <= 0:
        return None
    return elapsed_s * (1 - fraction) / fraction


def list_files(folder: Path) -> list[ExportFile]:
    items: list[ExportFile] = []
    try:
        entries = sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return items
    for path in entries:
        if path.is_dir():
            items.append(ExportFile(name=path.name + "/", files=sum(1 for _ in path.iterdir())))
        else:
            items.append(ExportFile(name=path.name, bytes=path.stat().st_size))
    return items


def open_folder(folder: Path) -> None:
    """Show a folder in Explorer (Windows only; elsewhere nothing happens)."""
    if sys.platform == "win32":
        os.startfile(folder)


class ExportManager:
    def __init__(
        self,
        host: ExportHost,
        *,
        ffmpeg: Callable[[], Path],
        tools_problem: Callable[[], str | None],
        voice_busy: Callable[[], bool] = lambda: False,
        unload_voice: Callable[[], None] = lambda: None,
        run: RunFn = run_export,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._host = host
        self._ffmpeg = ffmpeg
        self._tools_problem = tools_problem
        self._voice_busy = voice_busy
        self._unload_voice = unload_voice
        self._run = run
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._status = ExportStatus()
        self._started_at = 0.0

    @property
    def running(self) -> bool:
        with self._lock:
            return self._status.state == "running"

    def status(self, defaults: ExportDefaults | None = None) -> ExportStatus:
        with self._lock:
            status = self._status.model_copy(deep=True)
            if status.state == "running":
                elapsed = self._clock() - self._started_at
                status.elapsed_s = round(elapsed, 1)
                eta = estimate_left(elapsed, status.fraction)
                status.eta_s = None if eta is None else round(eta, 1)
        status.defaults = defaults
        return status

    def start(self, request: ExportRequest, default_parent: Path) -> ExportStatus:
        with self._lock:
            if self._status.state == "running":
                raise ExportError("an export is already running")
        if self._voice_busy():
            raise ExportError("voice generation is running: wait for it to finish, then export")
        key = self._host.project_key()
        if key is None:
            raise ExportError("no project is open")
        report = self._host.export_preflight(tools_problem=self._tools_problem())
        if not report.ok:
            first = next(i for i in report.issues if i.severity == "error")
            raise ExportError(f"the pre-flight found {report.error_count} error(s): {first.message}")
        if report.warning_count and not request.accept_warnings:
            raise ExportError(
                f"the pre-flight has {report.warning_count} warning(s): confirm them to export anyway"
            )
        parent = Path(request.folder) if request.folder else default_parent
        if request.folder and not parent.is_dir():
            raise ExportError(f"folder not found: {parent}")
        folder = unique_folder(parent, export_folder_name(datetime.now()))
        options = ExportOptions(
            include_overlay=request.include_overlay,
            include_raw_links=request.include_raw_links,
            limit_ms=None if request.limit_seconds is None else round(request.limit_seconds * 1000),
        )
        with self._lock:
            if self._status.state == "running":
                raise ExportError("an export is already running")
            self._stop.clear()
            self._started_at = self._clock()
            self._status = ExportStatus(state="running", stage="prepare", folder=str(folder))
            self._thread = threading.Thread(
                target=self._work,
                args=(key, folder, options, request.unload_voice),
                name="export",
                daemon=True,
            )
            self._thread.start()
        return self.status()

    def cancel(self) -> ExportStatus:
        """Ask the running export to stop (it stops within a second or two)."""
        with self._lock:
            if self._status.state != "running":
                raise ExportError("no export is running")
        self._stop.set()
        return self.status()

    def wait(self, timeout_s: float = 60.0) -> ExportStatus:
        thread = self._thread
        if thread is not None:
            thread.join(timeout_s)
        return self.status()

    # --- the thread -------------------------------------------------------------------

    def _report(self, stage: str, fraction: float) -> None:
        with self._lock:
            self._status.stage = stage
            self._status.fraction = max(self._status.fraction, min(max(fraction, 0.0), 1.0))

    def _check_project(self, key: str) -> None:
        if self._host.project_key() != key:
            raise ExportError("the project was closed during the export")

    def _work(self, key: str, folder: Path, options: ExportOptions, unload: bool) -> None:
        host = self._host

        def processed_for(cue: VoiceCue) -> Path:
            self._check_project(key)
            path = host.processed_take_path(cue.take_id, cue.stretch)
            if path is None:
                raise ExportError(f'the take of "{cue.line_text}" has no file')
            return path

        def raw_for(cue: VoiceCue) -> tuple[np.ndarray, int]:
            self._check_project(key)
            found = host.aligned_raw_take(cue.take_id, cue.stretch)
            if found is None:
                raise ExportError(f'the take of "{cue.line_text}" has no file')
            return found

        state: ExportState = "done"
        message: str | None = None
        result: ExportResult | None = None
        try:
            if unload:
                self._report("unload", 0.0)
                self._unload_voice()
            self._check_project(key)
            inputs = host.export_inputs()
            result = self._run(
                inputs,
                folder,
                ffmpeg=self._ffmpeg(),
                processed_for=processed_for,
                raw_for=raw_for,
                options=options,
                should_stop=self._stop.is_set,
                report=self._report,
            )
        except ExportCancelled:
            state, message = "cancelled", "Export cancelled."
        except Exception as exc:  # noqa: BLE001 - every failure is shown to the user
            state, message = "failed", str(exc) or type(exc).__name__
        if state != "done" and folder.exists():
            folder = mark_incomplete(folder)
        elapsed = self._clock() - self._started_at
        with self._lock:
            self._status = ExportStatus(
                state=state,
                stage="done" if state == "done" else self._status.stage,
                fraction=1.0 if state == "done" else self._status.fraction,
                elapsed_s=round(elapsed, 1),
                folder=str(folder) if folder.exists() else None,
                message=message,
                files=list_files(folder) if folder.exists() else [],
                video_ms=None if result is None else round(result.render.frames * 1000 / float(result.fmt.fps)),
            )
