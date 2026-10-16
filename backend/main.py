"""App shell: uvicorn in a thread plus a pywebview window (M1-6).

Run from the repo root: ``uv run python -m backend.main``
"""

import socket
import threading
import time
from typing import Any

import uvicorn
import webview

from backend.app import APP_NAME, create_app
from backend.project.recent import default_recent_path
from backend.project.session import Session
from backend.voice.engine import chatterbox_model_version
from backend.voice.jobqueue import JobQueue
from backend.voice.subprocess_worker import SubprocessWorker, default_worker_log_path

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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    port = _free_port()
    session = Session(recent_path=default_recent_path())
    jobs = JobQueue(
        session,
        SubprocessWorker(log_path=default_worker_log_path()),
        model_version=chatterbox_model_version,
    )
    config = uvicorn.Config(
        create_app(session=session, jobs=jobs),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10.0
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("backend server failed to start")
        time.sleep(0.05)

    webview.create_window(
        APP_NAME,
        f"http://127.0.0.1:{port}/",
        width=1280,
        height=800,
        js_api=Api(),
    )
    webview.start()

    server.should_exit = True
    jobs.close()  # cancels a running job and stops the GPU worker
    thread.join(timeout=5.0)


if __name__ == "__main__":
    main()
