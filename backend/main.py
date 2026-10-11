"""App shell: uvicorn in a thread plus a pywebview window (M1-6).

Run from the repo root: ``uv run python -m backend.main``
"""

import socket
import threading
import time

import uvicorn
import webview

from backend.app import APP_NAME, create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> None:
    port = _free_port()
    config = uvicorn.Config(
        create_app(), host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10.0
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("backend server failed to start")
        time.sleep(0.05)

    webview.create_window(APP_NAME, f"http://127.0.0.1:{port}/", width=1280, height=800)
    webview.start()

    server.should_exit = True
    thread.join(timeout=5.0)


if __name__ == "__main__":
    main()
