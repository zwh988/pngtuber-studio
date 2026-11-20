"""FastAPI application: JSON API under ``/api`` plus the built frontend (M1-6)."""

from collections.abc import Callable, Sequence
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.audio.clipimport import AudioImportRequest, AudioImportResult
from backend.audio.fxstate import FxState
from backend.avatar.envelope import EnvelopeReport
from backend.avatar.scan import AvatarState
from backend.avatar.track import FrameTrack
from backend.export.errors import ExportError
from backend.export.job import (
    ExportDefaults,
    ExportManager,
    ExportRequest,
    ExportStatus,
    RunFn,
    open_folder,
)
from backend.export.pipeline import run_export
from backend.export.preflight import PreflightReport
from backend.export.tools import default_ffmpeg_path, encoder_problem
from backend.media.serve import range_response
from backend.oserrors import describe_error
from backend.project.edit_ops import (
    AddPlacementOp,
    EditBatch,
    EditOp,
    MovePlacementOp,
    RemoveClipOp,
    RemovePlacementOp,
    ReorderClipOp,
    RippleDeleteOp,
    SetPlacementStretchOp,
    SetSpeedOp,
    SplitClipOp,
    TrimClipOp,
)
from backend.project.footage import FootageError, default_ffprobe_path
from backend.project.fx_ops import FxEditBatch
from backend.project.laneimport import LaneImportRequest, LaneImportResult
from backend.project.line_ops import LineEditBatch
from backend.project.recent import RecentItem, default_recent_path
from backend.project.schema import SCHEMA_VERSION
from backend.project.session import Session, SessionError
from backend.project.store import ProjectError
from backend.project.summary import FootageReport, ProjectSummary
from backend.project.template import TemplateError
from backend.project.timeline import EditResult, TimelineState
from backend.project.usertemplates import TemplateInfo, TemplateList
from backend.settings import (
    AppSettings,
    PathItem,
    app_data_dir,
    default_user_templates_dir,
    folder_to_open,
    path_items,
)
from backend.voice.engine import chatterbox_model_version
from backend.voice.jobqueue import JobError, JobQueue
from backend.voice.jobs import JobItem, JobStatus
from backend.voice.linebank import LineBankState
from backend.voice.model import ModelManager, ModelStatus, hf_cache_dir
from backend.voice.peaks import PeaksError, PeaksReport, read_take_peaks
from backend.voice.profile import VoiceState
from backend.voice.stretchrender import StretchError, ensure_stretched
from backend.voice.subprocess_worker import SubprocessWorker, default_worker_log_path
from backend.voice.takes import StorageReport, TakeDeleteReport, TakeItem, TakeTrimInfo
from backend.voice.userpresets import (
    PresetEdit,
    PresetsState,
    default_user_presets_path,
)

APP_NAME = "PNGtuber Studio"

_API_ERRORS = (SessionError, ProjectError, TemplateError, FootageError, JobError, ExportError)

_MISSING_FRONTEND_HTML = (
    "<!doctype html><title>PNGtuber Studio</title>"
    "<body style='font-family:sans-serif;padding:2rem'>"
    "<h1>Frontend not built</h1>"
    "<p>Run <code>npm install</code> and <code>npm run build</code> "
    "in the <code>frontend</code> folder, then restart the app.</p></body>"
)


class AvatarFolderRequest(BaseModel):
    path: str | None


class NewProjectRequest(BaseModel):
    name: str
    parent: str
    template_id: str | None = None  # M7 S6: None or "default" = the built-in template


class SaveTemplateRequest(BaseModel):
    name: str
    replace: bool = False


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


class PresetsRequest(BaseModel):
    presets: list[PresetEdit]


class OpenPathRequest(BaseModel):
    key: str


def default_templates_dir() -> Path:
    """``<repo>/templates``."""
    return Path(__file__).resolve().parents[1] / "templates"


def default_logo_path() -> Path:
    """``<repo>/assets/logo-512.png``: the one logo file the page shows (sidebar,
    favicon). The window and shortcut use ``assets/app.ico`` (``main.py``)."""
    return Path(__file__).resolve().parents[1] / "assets" / "logo-512.png"


def default_static_dir() -> Path:
    """``<repo>/frontend/dist``."""
    return Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(
    static_dir: Path | None = None,
    session: Session | None = None,
    jobs: JobQueue | None = None,
    export_tools: Callable[[], str | None] | None = None,
    export_run: RunFn | None = None,
    model: ModelManager | None = None,
    open_path: Callable[[Path], None] | None = None,
) -> FastAPI:
    """``jobs`` is the voice generation queue. By default one is built around the
    real GPU worker; nothing starts until the first job is submitted. The caller
    that owns the app (``main.py``) closes it. ``export_tools`` and ``export_run``
    replace the NVENC probe and the export steps in tests. ``model`` is the voice
    model's files and first-run download (M7 S3); built by default only with the
    real queue, so tests that pass their own queue need no model on disk.
    ``open_path`` shows a folder in Explorer (Settings, M7 S5); tests replace it."""
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

    model_files = model if model is not None else (ModelManager() if jobs is None else None)

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
            return active.new_project(request.parent, request.name, request.template_id)
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

    check_tools = export_tools if export_tools is not None else encoder_problem

    def unload_voice() -> None:
        job = queue.submit_unload()
        queue.wait(job.id, timeout_s=120.0)

    exports = ExportManager(
        active,
        ffmpeg=default_ffmpeg_path,
        tools_problem=check_tools,
        voice_busy=lambda: queue.status().active,
        unload_voice=unload_voice,
        run=export_run if export_run is not None else run_export,
    )

    def export_defaults() -> ExportDefaults | None:
        try:
            return active.export_defaults()
        except SessionError:
            return None

    @app.get("/api/export/preflight")
    def get_export_preflight() -> PreflightReport:
        # M6-1: what blocks or needs confirming before an export (probes ffmpeg once).
        try:
            return active.export_preflight(tools_problem=check_tools())
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/export/status")
    def get_export_status() -> ExportStatus:
        # M6-7: polled by the export screen (progress, time left, result files).
        return exports.status(defaults=export_defaults())

    @app.post("/api/export/start")
    def start_export(request: ExportRequest) -> ExportStatus:
        defaults = export_defaults()
        if defaults is None:
            raise HTTPException(status_code=400, detail="no project is open")
        try:
            exports.start(request, Path(defaults.folder))
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return exports.status(defaults=defaults)

    @app.post("/api/export/cancel")
    def cancel_export() -> ExportStatus:
        try:
            exports.cancel()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return exports.status(defaults=export_defaults())

    @app.post("/api/export/open-folder")
    def open_export_folder() -> dict[str, str]:
        # Only the last export's folder, or the project's exports folder: never a path
        # from the request.
        status = exports.status()
        defaults = export_defaults()
        target = Path(status.folder) if status.folder else None
        if (target is None or not target.is_dir()) and defaults is not None:
            target = Path(defaults.folder)
        if target is None or not target.is_dir():
            raise HTTPException(status_code=404, detail="no export folder yet")
        open_folder(target)
        return {"folder": str(target)}

    @app.get("/api/avatar/track")
    def get_avatar_track() -> FrameTrack:
        # M5-6: what the preview canvas draws, sampled by the Python solver (rule 5).
        try:
            return active.avatar_track()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/avatar")
    def get_avatar() -> AvatarState:
        try:
            return active.avatar()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/avatar/folder")
    def set_avatar_folder(request: AvatarFolderRequest) -> AvatarState:
        # The path comes from the user's folder picker or typing; null clears it.
        try:
            return active.set_avatar_folder(request.path)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/fx")
    def get_fx() -> FxState:
        try:
            return active.fx()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/fx/edit")
    def edit_fx(batch: FxEditBatch) -> FxState:
        try:
            return active.edit_fx(batch.ops, batch.label)
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

    def refuse_while_exporting() -> None:
        # Rule 7: one GPU job at a time. NVENC and the voice model share the GPU.
        if exports.running:
            raise HTTPException(status_code=400, detail="an export is running: generate after it")

    def refuse_without_model() -> None:
        if model_files is not None and not model_files.ready():
            raise HTTPException(
                status_code=400,
                detail="the voice model is not downloaded yet: download it from the start page",
            )

    show_folder = open_path if open_path is not None else open_folder

    def settings_paths(presets_file: Path | None = None) -> list[PathItem]:
        presets_path = presets_file if presets_file is not None else default_user_presets_path()
        return path_items(
            [
                ("app_data", "App data (recent list, logs, edited presets)", app_data_dir(), True),
                ("recent", "Recent projects list", default_recent_path(), False),
                ("worker_log", "Voice worker log", default_worker_log_path(), False),
                ("presets", "Edited emotion presets", presets_path, False),
                ("ffmpeg", "ffmpeg (video export)", default_ffmpeg_path(), False),
                ("ffprobe", "ffprobe (reads footage)", default_ffprobe_path(), False),
                ("model", "Voice model (Hugging Face cache)", hf_cache_dir(), True),
                ("templates", "Built-in templates and presets", default_templates_dir(), True),
                ("user_templates", "Saved channel templates", default_user_templates_dir(), True),
            ]
        )

    @app.get("/api/settings")
    def get_settings() -> AppSettings:
        presets: PresetsState | None = None
        presets_error: str | None = None
        try:
            presets = active.presets_state()
        except _API_ERRORS as exc:
            presets_error = str(exc)
        return AppSettings(
            presets=presets,
            presets_error=presets_error,
            tools_problem=check_tools(),
            export=active.export_settings(),
            paths=settings_paths(Path(presets.path) if presets is not None else None),
        )

    @app.get("/api/templates")
    def get_templates() -> TemplateList:
        try:
            return active.templates()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/templates/save")
    def save_template(request: SaveTemplateRequest) -> TemplateInfo:
        try:
            return active.save_as_template(request.name, replace=request.replace)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/settings/presets")
    def save_presets(request: PresetsRequest) -> PresetsState:
        try:
            return active.save_presets(request.presets)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/settings/presets/reset")
    def reset_presets() -> PresetsState:
        try:
            return active.reset_presets()
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/settings/open")
    def open_settings_path(request: OpenPathRequest) -> dict[str, str]:
        item = next((p for p in settings_paths() if p.key == request.key), None)
        if item is None:
            raise HTTPException(status_code=400, detail=f"unknown path {request.key!r}")
        folder = folder_to_open(item)
        if not folder.is_dir():
            raise HTTPException(status_code=400, detail=f"{folder} does not exist yet")
        try:
            show_folder(folder)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=describe_error(exc)) from exc
        return {"folder": str(folder)}

    @app.get("/api/voice/model")
    def get_model() -> ModelStatus:
        if model_files is None:
            return ModelStatus(state="ready")
        return model_files.status()

    @app.post("/api/voice/model/download")
    def download_model() -> ModelStatus:
        if model_files is None:
            return ModelStatus(state="ready")
        return model_files.start_download()

    @app.post("/api/voice/generate")
    def generate_line(request: LineIdRequest) -> JobItem:
        refuse_while_exporting()
        refuse_without_model()
        try:
            return queue.submit(request.line_id)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/voice/reroll")
    def reroll_line(request: LineIdRequest) -> JobItem:
        refuse_while_exporting()
        refuse_without_model()
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

    @app.get("/media/avatar/{expression}/{state}")
    def get_avatar_sprite(expression: str, state: str, request: Request) -> Response:
        # M5-6: a downscaled sprite of the project's art, looked up by expression and
        # state ("oicm"...), never by a path from the URL.
        try:
            path = active.avatar_sprite_path(expression, state)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if path is None:
            raise HTTPException(status_code=404, detail="sprite not found")
        return range_response(path, request.headers.get("range"))

    @app.get("/media/take/{take_id}")
    def get_take_media(
        take_id: str,
        request: Request,
        stretch: float = 1.0,
        processed: bool = False,
    ) -> Response:
        # The file comes from the open project's take list, never from the URL.
        # ``stretch`` only picks a number. With ``processed=1`` the take is served
        # through the voice chain (trim, stretch, EQ, ..., loudness), rendered once
        # per key and kept. Clients add ``&v=<fx_version>`` so a chain change never
        # hits a cached copy; the server ignores it. Without ``processed`` the old
        # stretch-only copy (M3) is served, and ``stretch=1`` is the raw take.
        if processed:
            try:
                ready = active.processed_take_path(take_id, stretch)
            except _API_ERRORS as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if ready is None or not ready.is_file():
                raise HTTPException(status_code=404, detail="take file not found")
            return range_response(ready, request.headers.get("range"))
        path = active.take_path(take_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="take file not found")
        if stretch != 1.0:
            try:
                path = ensure_stretched(path, stretch)
            except StretchError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        return range_response(path, request.headers.get("range"))

    @app.get("/api/takes/{take_id}/peaks")
    def get_take_peaks(take_id: str, buckets: int = 400) -> PeaksReport:
        # Computed on demand from the take file; nothing is stored (M3 decision 12).
        path = active.take_path(take_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="take file not found")
        try:
            return read_take_peaks(path, take_id, buckets)
        except PeaksError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/takes/{take_id}/envelope")
    def get_take_envelope(take_id: str, stretch: float = 1.0) -> EnvelopeReport:
        # M5-2: the mouth's input. Measured from the processed take (CPU), cached.
        try:
            report = active.envelope(take_id, stretch)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if report is None:
            raise HTTPException(status_code=404, detail="take file not found")
        return report

    @app.get("/api/takes/{take_id}/trim")
    def get_take_trim(
        take_id: str,
        preview: bool = False,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> TakeTrimInfo:
        # M5-0 trimmer: the stored cuts, or (preview=1) the given ones, with the
        # automatic trim measured inside them. Read only.
        try:
            return active.take_trim(
                take_id, preview=preview, start_ms=start_ms, end_ms=end_ms
            )
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @app.post("/api/timeline/place")
    def place_line(op: AddPlacementOp) -> TimelineState:
        return run_edit([op])

    @app.post("/api/timeline/move-placement")
    def move_placement(op: MovePlacementOp) -> TimelineState:
        return run_edit([op])

    @app.post("/api/timeline/remove-placement")
    def remove_placement(op: RemovePlacementOp) -> TimelineState:
        return run_edit([op])

    @app.post("/api/timeline/stretch")
    def set_placement_stretch(op: SetPlacementStretchOp) -> TimelineState:
        return run_edit([op])

    @app.post("/api/timeline/batch")
    def edit_batch(batch: EditBatch) -> TimelineState:
        return run_edit(batch.ops, batch.label)

    # ---- audio lanes (M8-1) ----------------------------------------------------

    @app.post("/api/audio/import")
    def import_audio(request: AudioImportRequest) -> AudioImportResult:
        try:
            return active.import_audio(
                request.paths,
                request.lane_id,
                request.timeline_ms,
                new_lane=request.new_lane,
            )
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/lanes/import")
    def import_lane_media(request: LaneImportRequest) -> LaneImportResult:
        try:
            return active.import_lane_media(
                request.paths,
                request.lane_id,
                request.timeline_ms,
                new_lane=request.new_lane,
            )
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/media/image/{image_id}")
    def get_image_media(image_id: str, request: Request) -> Response:
        # An imported still for the video lanes (M8-2); the path comes from the project.
        path = active.image_path(image_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="image not found")
        return range_response(path, request.headers.get("range"))

    def decoded_audio(file_id: str) -> Path:
        try:
            path = active.audio_decoded_path(file_id)
        except _API_ERRORS as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="audio file not found")
        return path

    @app.get("/media/audio/{file_id}")
    def get_audio_media(file_id: str, request: Request) -> Response:
        # The decoded WAV of an imported file: what preview and export both play.
        return range_response(decoded_audio(file_id), request.headers.get("range"))

    @app.get("/api/audio/{file_id}/peaks")
    def get_audio_peaks(file_id: str, buckets: int = 400) -> PeaksReport:
        try:
            return read_take_peaks(decoded_audio(file_id), file_id, buckets)
        except PeaksError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/app/logo.png")
    def get_logo() -> FileResponse:
        # Read from assets/ on every request (no-cache), so a changed logo shows
        # after a restart without rebuilding the frontend.
        logo = default_logo_path()
        if not logo.is_file():
            raise HTTPException(status_code=404, detail="logo not found")
        return FileResponse(logo, media_type="image/png", headers={"Cache-Control": "no-cache"})

    folder = static_dir if static_dir is not None else default_static_dir()
    if (folder / "index.html").is_file():
        # Mounted last so it never shadows the /api routes.
        app.mount("/", StaticFiles(directory=folder, html=True), name="frontend")
    else:

        @app.get("/", response_class=HTMLResponse)
        def frontend_missing() -> str:
            return _MISSING_FRONTEND_HTML

    return app
