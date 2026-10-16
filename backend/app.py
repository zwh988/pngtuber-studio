"""FastAPI application: JSON API under ``/api`` plus the built frontend (M1-6)."""

from collections.abc import Sequence
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.media.serve import range_response
from backend.project.edit_ops import (
    EditBatch,
    EditOp,
    RemoveClipOp,
    ReorderClipOp,
    RippleDeleteOp,
    SetSpeedOp,
    SplitClipOp,
    TrimClipOp,
)
from backend.project.footage import FootageError
from backend.project.line_ops import LineEditBatch
from backend.project.recent import RecentItem
from backend.project.schema import SCHEMA_VERSION
from backend.project.session import Session, SessionError
from backend.project.store import ProjectError
from backend.project.summary import FootageReport, ProjectSummary
from backend.project.template import TemplateError
from backend.project.timeline import EditResult, TimelineState
from backend.voice.engine import chatterbox_model_version
from backend.voice.jobqueue import JobError, JobQueue
from backend.voice.jobs import JobItem, JobStatus
from backend.voice.linebank import LineBankState
from backend.voice.profile import VoiceState
from backend.voice.subprocess_worker import SubprocessWorker, default_worker_log_path
from backend.voice.takes import StorageReport, TakeDeleteReport, TakeItem

APP_NAME = "PNGtuber Studio"

_API_ERRORS = (SessionError, ProjectError, TemplateError, FootageError, JobError)

_MISSING_FRONTEND_HTML = (
    "<!doctype html><title>PNGtuber Studio</title>"
    "<body style='font-family:sans-serif;padding:2rem'>"
    "<h1>Frontend not built</h1>"
    "<p>Run <code>npm install</code> and <code>npm run build</code> "
    "in the <code>frontend</code> folder, then restart the app.</p></body>"
)


class NewProjectRequest(BaseModel):
    name: str
    parent: str


class OpenProjectRequest(BaseModel):
    folder: str


class ForgetRecentRequest(BaseModel):
    folder: str


class RelinkRequest(BaseModel):
    source_id: str
    path: str


class AddClipRequest(BaseModel):
    source_id: str
    position: int | None = None


class VoiceReferenceRequest(BaseModel):
    path: str


class TakeIdRequest(BaseModel):
    take_id: str


class LineIdRequest(BaseModel):
    line_id: str


class JobIdRequest(BaseModel):
    job_id: str


def default_static_dir() -> Path:
    """``<repo>/frontend/dist``."""
    return Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(
    static_dir: Path | None = None,
    session: Session | None = None,
    jobs: JobQueue | None = None,
) -> FastAPI:
    """``jobs`` is the voice generation queue. By default one is built around the
    real GPU worker; nothing starts until the first job is submitted. The caller
    that owns the app (``main.py``) closes it."""
    app = FastAPI(title=APP_NAME)
    active = session if session is not None else Session()
    queue = (
        jobs
        if jobs is not None
        else JobQueue(
            active,
            SubprocessWorker(log_path=default_worker_log_path()),
            model_version=chatterbox_model_version,
        )
    )

    @app.get("/api/hello")
    def hello() -> dict[str, str | int]:
        return {
            "app": APP_NAME,
            "status": "ok",
            "schema_version": SCHEMA_VERSION,
        }

    @app.get("/api/project")
    def get_project() -> ProjectSummary | None:
        return active.current()

    @app.post("/api/project/new")
    def new_project(request: NewProjectRequest) -> ProjectSummary:
        try:
            return active.new_project(request.parent, request.name)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/project/open")
    def open_project(request: OpenProjectRequest) -> ProjectSummary:
        try:
            return active.open_project(request.folder)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/footage")
    def get_footage() -> FootageReport:
        try:
            return active.footage()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/footage/rescan")
    def rescan_footage() -> FootageReport:
        try:
            return active.rescan_footage()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/footage/relink")
    def relink_footage(request: RelinkRequest) -> FootageReport:
        try:
            return active.relink_source(request.source_id, request.path)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/timeline")
    def get_timeline() -> TimelineState:
        try:
            return active.timeline()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/timeline/clips")
    def add_clip(request: AddClipRequest) -> TimelineState:
        try:
            return active.add_clip(request.source_id, request.position)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/timeline/undo")
    def undo_edit() -> EditResult:
        try:
            return active.undo()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/timeline/redo")
    def redo_edit() -> EditResult:
        try:
            return active.redo()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/voice")
    def get_voice() -> VoiceState:
        try:
            return active.voice()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/voice/reference")
    def set_voice_reference(request: VoiceReferenceRequest) -> VoiceState:
        try:
            return active.set_voice_reference(request.path)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/lines")
    def get_lines() -> LineBankState:
        try:
            return active.lines()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/lines/edit")
    def edit_lines(batch: LineEditBatch) -> LineBankState:
        try:
            return active.edit_lines(batch.ops, batch.label)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/lines/{line_id}/takes")
    def get_line_takes(line_id: str) -> list[TakeItem]:
        try:
            return active.takes(line_id)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/takes/delete")
    def delete_take(request: TakeIdRequest) -> TakeDeleteReport:
        try:
            return active.delete_take(request.take_id)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/lines/delete")
    def delete_line(request: LineIdRequest) -> TakeDeleteReport:
        try:
            return active.delete_line(request.line_id)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/voice/generate")
    def generate_line(request: LineIdRequest) -> JobItem:
        try:
            return queue.submit(request.line_id)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/voice/reroll")
    def reroll_line(request: LineIdRequest) -> JobItem:
        try:
            return queue.submit(request.line_id, reroll=True)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/voice/jobs")
    def get_jobs() -> JobStatus:
        return queue.status()

    @app.post("/api/voice/jobs/cancel")
    def cancel_job(request: JobIdRequest) -> JobStatus:
        try:
            return queue.cancel(request.job_id)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/voice/worker/unload")
    def unload_worker() -> JobItem:
        try:
            return queue.submit_unload()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/storage")
    def get_storage() -> StorageReport:
        try:
            return active.storage()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/recent")
    def get_recent() -> list[RecentItem]:
        return active.recent()

    @app.post("/api/recent/remove")
    def remove_recent(request: ForgetRecentRequest) -> list[RecentItem]:
        try:
            active.forget_recent(request.folder)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return active.recent()

    @app.get("/media/source/{source_id}")
    def get_source_media(source_id: str, request: Request) -> Response:
        # The file comes from the open project's source list, never from the URL.
        path = active.source_path(source_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="footage file not found")
        return range_response(path, request.headers.get("range"))

    @app.get("/media/take/{take_id}")
    def get_take_media(take_id: str, request: Request) -> Response:
        # The file comes from the open project's take list, never from the URL.
        path = active.take_path(take_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="take file not found")
        return range_response(path, request.headers.get("range"))

    def run_edit(ops: Sequence[EditOp], label: str | None = None) -> TimelineState:
        try:
            return active.edit(ops, label)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/timeline/split")
    def split_clip(op: SplitClipOp) -> TimelineState:
        return run_edit([op])

    @app.post("/api/timeline/ripple-delete")
    def ripple_delete(op: RippleDeleteOp) -> TimelineState:
        return run_edit([op])

    @app.post("/api/timeline/trim")
    def trim_clip(op: TrimClipOp) -> TimelineState:
        return run_edit([op])

    @app.post("/api/timeline/reorder")
    def reorder_clip(op: ReorderClipOp) -> TimelineState:
        return run_edit([op])

    @app.post("/api/timeline/speed")
    def set_speed(op: SetSpeedOp) -> TimelineState:
        return run_edit([op])

    @app.post("/api/timeline/remove")
    def remove_clip(op: RemoveClipOp) -> TimelineState:
        return run_edit([op])

    @app.post("/api/timeline/batch")
    def edit_batch(batch: EditBatch) -> TimelineState:
        return run_edit(batch.ops, batch.label)

    folder = static_dir if static_dir is not None else default_static_dir()
    if (folder / "index.html").is_file():
        # Mounted last so it never shadows the /api routes.
        app.mount("/", StaticFiles(directory=folder, html=True), name="frontend")
    else:

        @app.get("/", response_class=HTMLResponse)
        def frontend_missing() -> str:
            return _MISSING_FRONTEND_HTML

    return app
