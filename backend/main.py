"""App shell: a pywebview window with a splash, then uvicorn in a thread (M1-6).

Run from the repo root: ``uv run python -m backend.main`` (console), or
``.venv\\Scripts\\pythonw.exe -m backend.main`` (no console; the desktop shortcut).

Startup order: the window opens first on an inline splash (logo, "Starting..."),
then the boot thread does the heavy imports, starts the server and loads the app
into the same window. Under pythonw there is no console, so stdout and stderr go
to ``app.log`` and a startup failure shows in the splash or in a message box.
"""

import base64
import ctypes
import html
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

import webview
from webview.dom import DOMEventHandler

from backend.dropfiles import dropped_files, page_call

APP_NAME = "PNGtuber Studio"  # same as backend.app.APP_NAME (not imported: heavy)
ROOT = Path(__file__).resolve().parents[1]
APP_ICON = ROOT / "assets" / "app.ico"
APP_LOGO = ROOT / "assets" / "logo-512.png"
# Windows taskbar identity: without it the window groups under python.exe and
# the taskbar shows python.exe's icon instead of the window's.
APP_USER_MODEL_ID = "PNGtuberStudio.App"
SPLASH_BG = "#0e1014"  # frontend/src/theme.css --bg
LOG_NAME = "app.log"
SPLASH_LOAD_WAIT = 10.0  # seconds to wait for the splash page before swapping it

VIDEO_FILE_TYPES = (
    "Video files (*.mkv;*.mp4;*.mov;*.avi;*.webm;*.m4v;*.flv;*.ts)",
    "All files (*.*)",
)


def _dialog_mode(name: str, legacy_name: str) -> Any:
    """Newer pywebview has ``FileDialog.<name>``; older has ``<legacy_name>``."""
    file_dialog = getattr(webview, "FileDialog", None)
    if file_dialog is not None:
        return getattr(file_dialog, name)
    return getattr(webview, legacy_name)


class Api:
    """Methods callable from the page as ``window.pywebview.api.<name>()``.

    Keep this object free of attributes holding the window: pywebview walks
    the object and recursion on a window handle causes trouble.
    """

    def pick_folder(self) -> str | None:
        if not webview.windows:
            return None
        mode = _dialog_mode("FOLDER", "FOLDER_DIALOG")
        result = webview.windows[0].create_file_dialog(mode)
        return str(result[0]) if result else None

    def pick_file(self) -> str | None:
        if not webview.windows:
            return None
        mode = _dialog_mode("OPEN", "OPEN_DIALOG")
        result = webview.windows[0].create_file_dialog(
            mode, allow_multiple=False, file_types=VIDEO_FILE_TYPES
        )
        return str(result[0]) if result else None


def _watch_file_drops(window: webview.Window) -> None:
    """Hand files dropped from Explorer to the page with their full paths (M8-1).

    Registered on every page load. ``prevent_default`` keeps WebView2 from opening
    a dropped file; propagation goes on, so the page's own drop listeners run too.
    """

    def on_drop(event: dict[str, Any]) -> None:
        message = dropped_files(event)
        if message is not None:
            window.evaluate_js(page_call(message))

    window.dom.document.events.drop += DOMEventHandler(on_drop, True, False)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _set_app_user_model_id() -> None:
    """Give the process its own taskbar identity (Windows only; no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


# ---- Logging without a console ----


def log_path() -> Path:
    """``%APPDATA%\\PNGtuberStudio\\app.log``. Same folder as
    ``backend.settings.app_data_dir()``, worked out here because importing
    settings pulls in pydantic and the schema before the splash shows."""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "PNGtuberStudio" / LOG_NAME


def ensure_stdio(path: Path) -> None:
    """Under pythonw ``sys.stdout``/``sys.stderr`` are None; anything that prints
    (uvicorn's log handlers, download progress bars) would then fail. Point the
    missing ones at the log file (or at devnull if it cannot be opened)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = open(path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def log_exception(path: Path, title: str) -> None:
    """Write the current exception's traceback to stderr (the console, or the
    log under pythonw) and, when stderr is a console, also append it to the log."""
    text = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {title}\n{traceback.format_exc()}\n"
    try:
        sys.stderr.write(text)
        sys.stderr.flush()
    except (AttributeError, OSError, ValueError):
        pass
    if getattr(sys.stderr, "name", None) == str(path):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        pass


def _message_box(text: str) -> None:
    """A native error box, for failures before or without the window."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10)  # MB_ICONERROR
    except (AttributeError, OSError):
        pass


# ---- Splash ----


def _logo_data_uri() -> str:
    try:
        data = APP_LOGO.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def splash_html(message: str = "Starting PNGtuber Studio…", error: str = "") -> str:
    """The page shown while the backend starts, or why it did not."""
    logo = _logo_data_uri()
    img = f'<img src="{logo}" alt="">' if logo else ""
    detail = f"<pre>{html.escape(error)}</pre>" if error else ""
    state = "error" if error else "busy"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{APP_NAME}</title>
<style>
html, body {{ margin: 0; height: 100%; background: {SPLASH_BG}; color: #a6adba;
  font: 14px/1.5 "Segoe UI", system-ui, sans-serif; }}
body {{ display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 20px; overflow: hidden; user-select: none; }}
img {{ width: 256px; height: 256px; }}
p {{ margin: 0; max-width: 80vw; text-align: center; overflow-wrap: anywhere; }}
.error p {{ color: #e7e9ee; }}
pre {{ max-width: 80vw; max-height: 30vh; overflow: auto; margin: 0; padding: 12px;
  background: #15181e; border: 1px solid #272c36; border-radius: 6px; color: #a6adba;
  font: 12px/1.4 Consolas, monospace; white-space: pre-wrap; user-select: text; }}
</style></head>
<body class="{state}">{img}<p>{html.escape(message)}</p>{detail}</body></html>"""


# ---- Backend ----


class Backend:
    """What the boot thread started, so the main thread can stop it on exit."""

    def __init__(self) -> None:
        self.server: Any = None
        self.thread: threading.Thread | None = None
        self.jobs: Any = None
        self.session: Any = None
        self.closing = threading.Event()  # the window was closed
        self.done = threading.Event()  # the boot thread finished

    def start(self) -> str:
        """Heavy imports, session, job queue and server. Returns the app's URL."""
        import uvicorn

        from backend.app import create_app
        from backend.project.recent import default_recent_path
        from backend.project.session import Session
        from backend.settings import default_user_templates_dir
        from backend.voice.engine import chatterbox_model_version
        from backend.voice.jobqueue import JobQueue
        from backend.voice.model import ModelManager
        from backend.voice.subprocess_worker import (
            SubprocessWorker,
            default_worker_log_path,
        )
        from backend.voice.userpresets import default_user_presets_path

        port = _free_port()
        self.session = Session(
            recent_path=default_recent_path(),
            user_presets_path=default_user_presets_path(),  # M7 S5: presets edited in Settings
            user_templates_dir=default_user_templates_dir(),  # M7 S6: saved channel templates
        )
        # Renders the processed takes in the background (CPU only) after every change.
        self.session.enable_prefetch()
        self.jobs = JobQueue(
            self.session,
            SubprocessWorker(log_path=default_worker_log_path()),
            model_version=chatterbox_model_version,
        )
        config = uvicorn.Config(
            create_app(session=self.session, jobs=self.jobs, model=ModelManager()),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()

        deadline = time.monotonic() + 10.0
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the backend server did not start")
            time.sleep(0.05)
        return f"http://127.0.0.1:{port}/"

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.jobs is not None:
            self.jobs.close()  # cancels a running job and stops the GPU worker
        if self.session is not None:
            self.session.shutdown_prefetch()
        if self.thread is not None:
            self.thread.join(timeout=5.0)


def _boot(window: Any, backend: Backend, logfile: Path) -> None:
    """Runs on pywebview's thread once the splash window exists.

    Each page swap first waits for the splash to finish loading: a swap sent
    while WebView2 is still starting is lost and the splash stays up.
    """
    try:
        url = backend.start()
        window.events.loaded.wait(SPLASH_LOAD_WAIT)
        if not backend.closing.is_set():
            window.load_url(url)
    except Exception as exc:  # noqa: BLE001 - every startup failure is shown
        log_exception(logfile, "PNGtuber Studio failed to start")
        if not backend.closing.is_set():
            try:
                window.events.loaded.wait(SPLASH_LOAD_WAIT)
                window.load_html(
                    splash_html(
                        f"PNGtuber Studio could not start. Details are in {logfile}",
                        f"{type(exc).__name__}: {exc}",
                    )
                )
            except Exception:  # noqa: BLE001 - window gone: fall back to a message box
                _message_box(f"PNGtuber Studio could not start.\n\nDetails: {logfile}")
    finally:
        backend.done.set()


def main() -> None:
    logfile = log_path()
    ensure_stdio(logfile)
    _set_app_user_model_id()
    backend = Backend()
    window = webview.create_window(
        APP_NAME,
        html=splash_html(),
        width=1280,
        height=800,
        background_color=SPLASH_BG,
        js_api=Api(),
    )
    if window is not None:
        window.events.loaded += lambda: _watch_file_drops(window)
    # pywebview's docs say "GTK/QT only", but its WinForms backend uses this icon
    # for the window (and so the taskbar); without it, python.exe's icon shows.
    webview.start(
        _boot,
        (window, backend, logfile),
        icon=str(APP_ICON) if APP_ICON.is_file() else None,
    )

    # Window closed. If the boot thread is still importing, let it finish so
    # whatever it started is stopped too.
    backend.closing.set()
    backend.done.wait(timeout=60.0)
    backend.stop()


def run() -> None:
    """Entry point: any startup failure reaches the user even without a console."""
    logfile = log_path()
    try:
        main()
    except Exception:  # noqa: BLE001 - shown in a message box without a console
        ensure_stdio(logfile)
        log_exception(logfile, "PNGtuber Studio stopped with an error")
        _message_box(
            f"PNGtuber Studio stopped with an error.\n\nDetails are in:\n{logfile}"
        )
        sys.exit(1)


if __name__ == "__main__":
    run()
