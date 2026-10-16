"""The real ``WorkerClient`` (M3-3): runs the GPU worker as a subprocess.

Commands go to the worker's stdin and events come back on its stdout, one JSON
line each (``protocol.py``). A reader thread turns stdout lines into events. The
worker's stderr (library output, tracebacks) goes to a log file. If the process
dies, the reader queues a fatal ``ErrorEvent`` naming the job that was running,
so the queue (S4c) can fail that job and restart the worker once.
"""

import logging
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Sequence
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import IO

from backend.voice.protocol import (
    ErrorEvent,
    GenerateCommand,
    ProtocolError,
    ShutdownCommand,
    WorkerCommand,
    WorkerEvent,
    decode_event,
    encode_message,
)
from backend.voice.worker_client import WorkerError

_log = logging.getLogger(__name__)

LOG_ROTATE_BYTES = 5 * 1024 * 1024
STOP_TIMEOUT_S = 5.0


def repo_root() -> Path:
    """``<repo>``: this file is ``<repo>/backend/voice/subprocess_worker.py``."""
    return Path(__file__).resolve().parents[2]


def default_worker_command() -> list[str]:
    return [sys.executable, "-m", "backend.voice.worker_main"]


def default_worker_log_path() -> Path:
    """``%APPDATA%\\PNGtuberStudio\\worker.log`` (the home folder if APPDATA is
    not set)."""
    base = os.environ.get("APPDATA")
    return (Path(base) if base else Path.home()) / "PNGtuberStudio" / "worker.log"


class SubprocessWorker:
    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        cwd: Path | None = None,
        log_path: Path | None = None,
    ) -> None:
        self._command = (
            list(command) if command is not None else default_worker_command()
        )
        self._cwd = cwd if cwd is not None else repo_root()
        self._log_path = log_path
        self._events: queue.Queue[WorkerEvent] = queue.Queue()
        self._lock = threading.Lock()  # start and close never overlap
        self._state_lock = threading.Lock()  # guards _process and _dead
        self._write_lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._active_job: str | None = None
        self._closing = False
        self._dead = True
        self.bad_line_count = 0  # lines from the worker that were not events

    # ---- WorkerClient ------------------------------------------------------

    @property
    def alive(self) -> bool:
        """False once the process is gone. When a crash makes this False, the
        fatal ``ErrorEvent`` is already queued (both happen under one lock), so a
        caller that sees ``alive`` False can drain the final event."""
        with self._state_lock:
            return self._process is not None and not self._dead

    def start(self) -> None:
        with self._lock:
            if self.alive:
                return
            self._closing = False
            env = dict(os.environ)
            env.update(PYTHONUNBUFFERED="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
            with ExitStack() as stack:
                log = self._open_log(stack)
                try:
                    process = subprocess.Popen(
                        self._command,
                        cwd=self._cwd,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=log if log is not None else subprocess.DEVNULL,
                        env=env,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except OSError as exc:
                    raise WorkerError(f"cannot start the voice worker: {exc}") from exc
            # The log handle is closed here; the child keeps its own copy.
            self._active_job = None
            with self._state_lock:
                self._process = process
                self._dead = False
            self._reader = threading.Thread(
                target=self._pump, args=(process,), daemon=True
            )
            self._reader.start()

    def send(self, command: WorkerCommand) -> None:
        process = self._process
        if process is None or not self.alive or process.stdin is None:
            raise WorkerError("the voice worker is not running")
        if isinstance(command, GenerateCommand):
            self._active_job = command.job_id
        data = encode_message(command).encode("utf-8")
        with self._write_lock:
            try:
                process.stdin.write(data)
                process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise WorkerError(f"cannot reach the voice worker: {exc}") from exc

    def next_event(self, timeout_s: float = 0.0) -> WorkerEvent | None:
        try:
            if timeout_s <= 0:
                return self._events.get_nowait()
            return self._events.get(timeout=timeout_s)
        except queue.Empty:
            return None

    def close(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return
            self._closing = True
            try:
                if process.poll() is None:
                    self.send(ShutdownCommand())
            except WorkerError:
                pass  # already gone
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except OSError:
                pass
            try:
                process.wait(timeout=STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=STOP_TIMEOUT_S)
            reader = self._reader
            if reader is not None:
                reader.join(timeout=STOP_TIMEOUT_S)
            if process.stdout is not None:
                process.stdout.close()
            with self._state_lock:
                self._dead = True
                self._process = None
            self._reader = None

    # ---- internals ---------------------------------------------------------

    def _pump(self, process: subprocess.Popen[bytes]) -> None:
        """Reader thread: stdout lines become events; end of output means the
        process is gone."""
        stdout = process.stdout
        if stdout is not None:
            for raw in iter(stdout.readline, b""):
                line = raw.decode("utf-8", errors="replace")
                if not line.strip():
                    continue
                try:
                    event = decode_event(line)
                except ProtocolError as exc:
                    self.bad_line_count += 1
                    _log.warning("unreadable line from the voice worker: %s", exc)
                    continue
                if self._job_ended(event):
                    self._active_job = None
                self._events.put(event)
        code = process.wait()
        crash: ErrorEvent | None = None
        if not self._closing:
            crash = ErrorEvent(
                job_id=self._active_job,
                message=(
                    f"the voice worker exited unexpectedly (exit code {code}); "
                    "see the worker log"
                ),
                fatal=True,
            )
        self._active_job = None
        with self._state_lock:
            if crash is not None:
                self._events.put(crash)
            if self._process is process:
                self._dead = True

    def _job_ended(self, event: WorkerEvent) -> bool:
        job_id = getattr(event, "job_id", None)
        if job_id is None or job_id != self._active_job:
            return False
        return event.type in ("done", "cancelled", "error")

    def _open_log(self, stack: ExitStack) -> IO[bytes] | None:
        """Open the worker log for appending (closed when ``stack`` exits). A
        log that cannot be opened must never stop the worker."""
        if self._log_path is None:
            return None
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            if (
                self._log_path.is_file()
                and self._log_path.stat().st_size > LOG_ROTATE_BYTES
            ):
                os.replace(self._log_path, self._log_path.with_name("worker.log.1"))
            handle = stack.enter_context(self._log_path.open("ab"))
            stamp = datetime.now().isoformat(timespec="seconds")
            handle.write(f"--- voice worker start {stamp} ---\n".encode())
            handle.flush()
        except OSError:
            return None
        return handle
