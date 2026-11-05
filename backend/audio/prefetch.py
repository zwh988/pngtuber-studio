"""Background rendering of processed takes (M4-1, S3d).

When the chain, a placement or a take changes, every processed file the placed lines
play is rendered ahead of time on one worker thread, so playback and the "processing
N of M" count catch up without the user waiting for a first play. Rendering is CPU
only and about 25 ms per spoken line once the libraries are loaded (rule 7 concerns
the GPU, so this does not queue behind voice generation).

- ``plan_jobs`` is pure: it lists what the open project plays.
- ``Prefetcher`` keeps one pending list. A new request replaces it (the newest wins);
  a job already being rendered finishes, since it is small and its file is useful.
- A failed render is remembered (``error``) until the next request, never retried in
  a loop, and never stops the worker.
- When the list is drained the optional ``on_idle`` callback runs once (clean-up).
"""

import importlib
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.audio.chainspec import FxChainError, processing_spec
from backend.audio.processed import TrimCache, ensure_processed, processed_path
from backend.audio.render import ProcessError
from backend.audio.wanted import played_takes
from backend.project.schema import Project
from backend.voice.takes import TakeError
from backend.voice.takestore import TakeStore

# What a render can raise that is the take's or the chain's problem, not a bug in
# the worker: it is recorded and the worker moves on.
_RENDER_ERRORS = (ProcessError, OSError, ValueError, RuntimeError, ArithmeticError)


@dataclass(frozen=True)
class RenderJob:
    raw_path: Path
    raw_key: str
    stretch: float
    spec: dict[str, Any]
    dest: Path  # where the processed file goes (its name is what clean-up keeps)


RenderFn = Callable[[RenderJob], None]


def plan_jobs(folder: Path, project: Project) -> list[RenderJob]:
    """The processed files the open project plays, in placement order.

    Empty when the voice chain cannot be used. No file access: whether a file
    exists is for the caller to check.
    """
    try:
        spec = processing_spec(project.fx_chain)
    except FxChainError:
        return []
    store = TakeStore(folder)
    jobs: list[RenderJob] = []
    for played in played_takes(project):
        try:
            raw_path = store.path(played.raw_file)
            dest = processed_path(raw_path, played.raw_key, played.stretch, spec)
        except (TakeError, ProcessError):
            continue
        jobs.append(RenderJob(raw_path, played.raw_key, played.stretch, spec, dest))
    return jobs


class Prefetcher:
    def __init__(
        self,
        cache: TrimCache | None = None,
        *,
        on_idle: Callable[[], None] | None = None,
        render: RenderFn | None = None,
    ) -> None:
        self._cache = cache
        self._on_idle = on_idle
        self._render: RenderFn = render if render is not None else self._render_job
        self._cond = threading.Condition()
        self._pending: list[RenderJob] = []
        self._wake = False  # something was requested and on_idle has not run since
        self._active = False  # the worker is rendering or running on_idle
        self._closed = False
        self._errors: dict[str, str] = {}
        self._thread: threading.Thread | None = None

    # ---- called from anywhere ------------------------------------------------

    def request(self, jobs: Sequence[RenderJob]) -> None:
        """Replace the pending list with ``jobs`` (an empty list is fine: it still
        starts and warms the worker). Returns at once."""
        with self._cond:
            if self._closed:
                return
            self._pending = list(jobs)
            self._errors.clear()
            self._wake = True
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="fx-prefetch", daemon=True
                )
                self._thread.start()
            self._cond.notify_all()

    def error(self) -> str | None:
        """The first render problem since the last request, if any."""
        with self._cond:
            return next(iter(self._errors.values()), None)

    def join(self, timeout: float = 10.0) -> bool:
        """Wait until nothing is pending or running. False if ``timeout`` ran out."""
        with self._cond:
            return self._cond.wait_for(self._is_idle, timeout)

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._pending = []
            self._cond.notify_all()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

    # ---- the worker ------------------------------------------------------------

    def _is_idle(self) -> bool:
        return self._thread is None or not (
            self._pending or self._wake or self._active
        )

    def _run(self) -> None:
        self._warm()
        while True:
            with self._cond:
                while not self._closed and not self._pending and not self._wake:
                    self._cond.wait()
                if self._closed:
                    return
                job = self._pending.pop(0) if self._pending else None
                if job is None:
                    self._wake = False
                self._active = True
            try:
                if job is not None:
                    self._do(job)
                else:
                    self._idle()
            finally:
                with self._cond:
                    self._active = False
                    self._cond.notify_all()

    @staticmethod
    def _warm() -> None:
        # Loading the audio libraries is most of a first render (about 0.9 s against
        # 25 ms). A missing one is reported by the first real render.
        for name in ("pedalboard", "pyloudnorm"):
            try:
                importlib.import_module(name)
            except ImportError:
                continue

    def _do(self, job: RenderJob) -> None:
        try:
            self._render(job)
        except _RENDER_ERRORS as exc:
            with self._cond:
                self._errors.setdefault(job.dest.name, str(exc))

    def _idle(self) -> None:
        if self._on_idle is None:
            return
        try:
            self._on_idle()
        except OSError:
            return

    def _render_job(self, job: RenderJob) -> None:
        if not job.raw_path.is_file():
            return  # a take whose file is gone cannot be rendered; not an error here
        ensure_processed(
            job.raw_path, job.raw_key, job.stretch, job.spec, cache=self._cache
        )
