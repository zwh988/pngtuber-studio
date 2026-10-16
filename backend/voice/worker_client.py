"""The backend's view of the GPU worker (M3-3).

``WorkerClient`` is the interface the job queue (S4c) talks to. The real client
(S4b) wraps a subprocess; ``FakeWorker`` (``fakeworker.py``) runs in-process for
tests. Both speak the messages in ``protocol.py``.
"""

from typing import Protocol, runtime_checkable

from backend.voice.protocol import WorkerCommand, WorkerEvent


class WorkerError(Exception):
    """The worker cannot be reached (not started, exited, pipe closed)."""


@runtime_checkable
class WorkerClient(Protocol):
    @property
    def alive(self) -> bool:
        """True while the worker can take commands."""

    def start(self) -> None:
        """Start the worker if it is not running. Does not load the model."""

    def send(self, command: WorkerCommand) -> None:
        """Queue a command. Never waits for GPU work. Raises ``WorkerError`` when
        the worker is not running."""

    def next_event(self, timeout_s: float = 0.0) -> WorkerEvent | None:
        """The next event in order, waiting up to ``timeout_s``; None if there is
        none. Events already queued are still returned after the worker exits."""

    def close(self) -> None:
        """Stop the worker and release its resources. Safe to call twice."""
