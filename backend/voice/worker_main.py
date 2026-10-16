"""GPU worker process entry point (M3-3).

Run as ``python -m backend.voice.worker_main`` from the repo root. Reads one JSON
command per line on stdin, writes one JSON event per line on stdout. Everything
else a library prints is sent to stderr (the backend points that at a log file):
the real stdout is duplicated first and fd 1 is then aimed at stderr, so even C
level prints cannot corrupt the protocol.

The command pipe is treated the same way: it is moved to a private descriptor and
fd 0 is pointed at NUL (``_claim_stdin``). On Windows a thread blocked reading a
pipe makes other calls on the same handle wait, and libraries do touch stdin while
they import, so a reader thread on fd 0 stalled the Chatterbox import for minutes.

``--engine tone`` swaps the model for sine tones (no GPU), for end-to-end tests.
"""

import argparse
import faulthandler
import os
import queue
import sys
import threading
from collections.abc import Sequence
from typing import IO

from backend.voice.engine import ChatterboxEngine, Engine, ToneEngine
from backend.voice.protocol import (
    CancelCommand,
    ErrorEvent,
    ProtocolError,
    ShutdownCommand,
    WorkerCommand,
    WorkerEvent,
    decode_command,
    encode_message,
)
from backend.voice.workerloop import WorkerLoop


class _Emitter:
    """Writes events to the protocol stream, one flushed line each."""

    def __init__(self, stream: IO[bytes]) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def __call__(self, event: WorkerEvent) -> None:
        data = encode_message(event).encode("utf-8")
        with self._lock:
            self._stream.write(data)
            self._stream.flush()


def _claim_stdout() -> IO[bytes]:
    """Keep the real stdout for protocol lines; send fd 1 and ``sys.stdout`` to
    stderr so stray prints cannot end up in the protocol."""
    sys.stdout.flush()
    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return os.fdopen(protocol_fd, "wb")


def _claim_stdin() -> IO[bytes]:
    """Keep the command pipe on a private descriptor no library knows about and
    point fd 0 (and so ``sys.stdin``) at NUL, so the blocking read in the reader
    thread cannot stall anything else."""
    command_fd = os.dup(0)
    null_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_fd, 0)
    os.close(null_fd)
    return os.fdopen(command_fd, "rb")


def _read_commands(
    stdin: IO[bytes],
    loop: WorkerLoop,
    commands: queue.Queue[WorkerCommand | None],
    emit: _Emitter,
) -> None:
    """Reader thread: a cancel takes effect at once, even while a job runs;
    every other command waits in the queue for the main thread."""
    for raw in iter(stdin.readline, b""):
        line = raw.decode("utf-8", errors="replace")
        if not line.strip():
            continue
        try:
            command = decode_command(line)
        except ProtocolError as exc:
            emit(ErrorEvent(message=f"bad command line: {exc}"))
            continue
        if isinstance(command, CancelCommand):
            loop.request_cancel(command.job_id)
        else:
            commands.put(command)
    commands.put(None)  # stdin closed: the backend is gone


def _enable_trace() -> None:
    """``PNGTUBER_WORKER_TRACE=<seconds>``: write every thread's stack to the log
    (stderr) that often, to find where a stuck worker is waiting."""
    raw = os.environ.get("PNGTUBER_WORKER_TRACE", "").strip()
    if not raw:
        return
    try:
        interval = float(raw)
    except ValueError:
        return
    if interval > 0:
        faulthandler.dump_traceback_later(interval, repeat=True, file=sys.stderr)


def _make_engine(args: argparse.Namespace) -> Engine:
    if args.engine == "tone":
        return ToneEngine(delay_s=args.tone_delay, noisy=args.tone_noisy)
    return ChatterboxEngine()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PNGtuber Studio GPU worker")
    parser.add_argument(
        "--engine", choices=("chatterbox", "tone"), default="chatterbox"
    )
    parser.add_argument("--tone-delay", type=float, default=0.0)
    parser.add_argument("--tone-noisy", action="store_true")
    args = parser.parse_args(argv)

    _enable_trace()
    stdin = _claim_stdin()
    emit = _Emitter(_claim_stdout())
    loop = WorkerLoop(_make_engine(args), emit)
    commands: queue.Queue[WorkerCommand | None] = queue.Queue()
    reader = threading.Thread(
        target=_read_commands, args=(stdin, loop, commands, emit), daemon=True
    )
    reader.start()
    try:
        while True:
            command = commands.get()
            if command is None:
                loop.handle(ShutdownCommand())
                return 0
            if not loop.handle(command):
                return 0
    except OSError:
        return 1  # the pipe to the backend broke


if __name__ == "__main__":
    raise SystemExit(main())
