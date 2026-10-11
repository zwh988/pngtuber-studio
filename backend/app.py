"""FastAPI application: JSON API under ``/api`` plus the built frontend (M1-6)."""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.project.footage import FootageError
from backend.project.recent import RecentItem
from backend.project.schema import SCHEMA_VERSION
from backend.project.session import Session, SessionError
from backend.project.store import ProjectError
from backend.project.summary import ProjectSummary
from backend.project.template import TemplateError

APP_NAME = "PNGtuber Studio"

_API_ERRORS = (SessionError, ProjectError, TemplateError, FootageError)

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


def default_static_dir() -> Path:
    """``<repo>/frontend/dist``."""
    return Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(
    static_dir: Path | None = None, session: Session | None = None
) -> FastAPI:
    app = FastAPI(title=APP_NAME)
    active = session if session is not None else Session()

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

    folder = static_dir if static_dir is not None else default_static_dir()
    if (folder / "index.html").is_file():
        # Mounted last so it never shadows the /api routes.
        app.mount("/", StaticFiles(directory=folder, html=True), name="frontend")
    else:

        @app.get("/", response_class=HTMLResponse)
        def frontend_missing() -> str:
            return _MISSING_FRONTEND_HTML

    return app
