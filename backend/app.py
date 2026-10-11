"""FastAPI application: JSON API under ``/api`` plus the built frontend (M1-6)."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.project.schema import SCHEMA_VERSION

APP_NAME = "PNGtuber Studio"

_MISSING_FRONTEND_HTML = (
    "<!doctype html><title>PNGtuber Studio</title>"
    "<body style='font-family:sans-serif;padding:2rem'>"
    "<h1>Frontend not built</h1>"
    "<p>Run <code>npm install</code> and <code>npm run build</code> "
    "in the <code>frontend</code> folder, then restart the app.</p></body>"
)


def default_static_dir() -> Path:
    """``<repo>/frontend/dist``."""
    return Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(static_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title=APP_NAME)

    @app.get("/api/hello")
    def hello() -> dict[str, str | int]:
        return {
            "app": APP_NAME,
            "status": "ok",
            "schema_version": SCHEMA_VERSION,
        }

    folder = static_dir if static_dir is not None else default_static_dir()
    if (folder / "index.html").is_file():
        # Mounted last so it never shadows the /api routes.
        app.mount("/", StaticFiles(directory=folder, html=True), name="frontend")
    else:

        @app.get("/", response_class=HTMLResponse)
        def frontend_missing() -> str:
            return _MISSING_FRONTEND_HTML

    return app
