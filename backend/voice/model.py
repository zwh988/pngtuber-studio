"""The voice model's files: are they on disk, and the first-run download (M7 S3).

The model is Chatterbox from Hugging Face, pinned to one revision so a new upload
can never change the voice behind the app's back (rule 3). The files live in the
standard Hugging Face cache (``%USERPROFILE%\\.cache\\huggingface\\hub`` unless
``HF_HOME`` or ``HF_HUB_CACHE`` says otherwise), where earlier versions of the app
put them too, so nothing is downloaded twice.

This is the only place in the app that touches the network (rule 8), and only when
the user presses Download. Looking files up reads the cache and never connects.
The GPU worker loads the model from the folder ``model_dir`` finds and always runs
with ``HF_HUB_OFFLINE=1``.

``ModelManager`` runs the download on one background thread, file by file, and
reports progress for the status endpoint. A download that stops can be retried;
Hugging Face resumes a partly downloaded file.
"""

import io
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

_log = logging.getLogger(__name__)

MODEL_REPO = "ResembleAI/chatterbox"
# Hugging Face "main" on 2026-11-17, the revision the app has used since 2026-10-10.
MODEL_REVISION = "5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int  # bytes at MODEL_REVISION


# What ``ChatterboxTTS.from_local`` reads (chatterbox-tts 0.1.7).
MODEL_FILES: tuple[ModelFile, ...] = (
    ModelFile("ve.safetensors", 5_695_784),
    ModelFile("t3_cfg.safetensors", 2_129_653_744),
    ModelFile("s3gen.safetensors", 1_056_484_620),
    ModelFile("tokenizer.json", 25_470),
    ModelFile("conds.pt", 107_374),
)
MODEL_BYTES = sum(f.size for f in MODEL_FILES)

ModelState = Literal["missing", "downloading", "ready", "failed"]

# filename -> path of that file in the cache, or None when it is not there
Lookup = Callable[[str], Path | None]
# (filename, report) -> None; ``report(n)`` gives the bytes of that file done so far
Downloader = Callable[[str, Callable[[int], None]], None]


class ModelStatus(BaseModel):
    state: ModelState
    repo: str = MODEL_REPO
    revision: str = MODEL_REVISION
    files_total: int = len(MODEL_FILES)
    files_present: int = 0
    bytes_total: int = MODEL_BYTES
    bytes_done: int = 0  # bytes of the model on disk, including the file in flight
    current_file: str | None = None
    cache_dir: str = ""  # where the files go, for the first-run screen
    message: str | None = None  # why the last download stopped


# ---- pure ---------------------------------------------------------------


def present_files(lookup: Lookup) -> dict[str, Path]:
    """The model files already on disk, by name."""
    found: dict[str, Path] = {}
    for f in MODEL_FILES:
        path = lookup(f.name)
        if path is not None:
            found[f.name] = path
    return found


def model_folder(found: Mapping[str, Path]) -> Path | None:
    """The folder that holds every model file, or None when one is missing or
    they are not side by side (``from_local`` takes one folder)."""
    if len(found) != len(MODEL_FILES) or any(f.name not in found for f in MODEL_FILES):
        return None
    parents = {found[f.name].parent for f in MODEL_FILES}
    return parents.pop() if len(parents) == 1 else None


def bytes_on_disk(
    present: Mapping[str, object], current: str | None, current_done: int
) -> int:
    """Finished files at their full size plus the file in flight (capped)."""
    total = 0
    for f in MODEL_FILES:
        if f.name in present:
            total += f.size
        elif f.name == current:
            total += max(0, min(current_done, f.size))
    return total


def describe_download_error(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    first = text.splitlines()[0]
    if len(first) > 300:
        first = first[:300] + "..."
    return (
        f"The download stopped ({first}). Check the internet connection and press "
        "Retry; the files already downloaded are kept."
    )


# ---- Hugging Face (I/O) --------------------------------------------------


def hf_cache_dir() -> Path:
    from huggingface_hub import constants

    return Path(constants.HF_HUB_CACHE)


def hf_lookup(cache_dir: Path | None = None) -> Lookup:
    """Looks a file up in the Hugging Face cache at the pinned revision. Never
    connects to the network."""

    def lookup(name: str) -> Path | None:
        from huggingface_hub import try_to_load_from_cache

        found: Any = try_to_load_from_cache(
            MODEL_REPO, name, cache_dir=cache_dir, revision=MODEL_REVISION
        )
        if isinstance(found, str):
            path = Path(found)
            if path.is_file():
                return path
        return None

    return lookup


def hf_downloader(cache_dir: Path | None = None) -> Downloader:
    """Downloads one file of the pinned revision into the Hugging Face cache,
    reporting bytes through a tqdm subclass (both the plain and the Xet path
    drive it)."""

    def download(name: str, report: Callable[[int], None]) -> None:
        from huggingface_hub import hf_hub_download
        from tqdm.std import tqdm

        class _Progress(tqdm):  # type: ignore[type-arg]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                kwargs["disable"] = False  # a disabled bar does not count
                kwargs["file"] = io.StringIO()  # draw nowhere
                super().__init__(*args, **kwargs)

            def update(self, n: float | None = 1) -> bool | None:
                result = super().update(n)
                report(int(self.n))
                return result

        hf_hub_download(
            MODEL_REPO,
            name,
            revision=MODEL_REVISION,
            cache_dir=cache_dir,
            tqdm_class=_Progress,
        )

    return download


# ---- the manager ---------------------------------------------------------


class ModelManager:
    """Model status for the UI and the one download thread."""

    def __init__(
        self,
        *,
        lookup: Lookup | None = None,
        download: Downloader | None = None,
        cache_dir_text: str | None = None,
    ) -> None:
        self._lookup = lookup if lookup is not None else hf_lookup()
        self._download = download if download is not None else hf_downloader()
        self._cache_dir_text = cache_dir_text
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._current: str | None = None
        self._current_done = 0
        self._message: str | None = None
        self._failed = False

    def _cache_dir(self) -> str:
        if self._cache_dir_text is None:
            try:
                self._cache_dir_text = str(hf_cache_dir())
            except Exception:  # noqa: BLE001 - only a label for the UI
                self._cache_dir_text = ""
        return self._cache_dir_text

    @property
    def downloading(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def folder(self) -> Path | None:
        """The folder the worker loads, or None while a file is missing."""
        return model_folder(present_files(self._lookup))

    def ready(self) -> bool:
        return self.folder() is not None

    def status(self) -> ModelStatus:
        found = present_files(self._lookup)
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            current = self._current if running else None
            done = bytes_on_disk(found, current, self._current_done)
            message = self._message
            failed = self._failed
        if model_folder(found) is not None:
            state: ModelState = "ready"
        elif running:
            state = "downloading"
        elif failed:
            state = "failed"
        else:
            state = "missing"
        return ModelStatus(
            state=state,
            files_present=len(found),
            bytes_done=done,
            current_file=current,
            cache_dir=self._cache_dir(),
            message=message if state == "failed" else None,
        )

    def start_download(self) -> ModelStatus:
        """Start (or retry) the download. Does nothing when the model is ready
        or a download is already running."""
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
        if not running and not self.ready():
            with self._lock:
                self._failed = False
                self._message = None
                self._current = None
                self._current_done = 0
                self._thread = threading.Thread(
                    target=self._run, name="model-download", daemon=True
                )
                self._thread.start()
        return self.status()

    def wait(self, timeout_s: float = 30.0) -> None:
        """Tests: wait for the download thread to end."""
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout_s)

    def _report(self, done: int) -> None:
        with self._lock:
            self._current_done = done

    def _run(self) -> None:
        try:
            for f in MODEL_FILES:
                if self._lookup(f.name) is not None:
                    continue
                with self._lock:
                    self._current = f.name
                    self._current_done = 0
                self._download(f.name, self._report)
                if self._lookup(f.name) is None:
                    raise RuntimeError(
                        f"{f.name} is not in the cache after its download"
                    )
        except Exception as exc:  # noqa: BLE001 - every failure is shown with Retry
            _log.warning("voice model download stopped: %s", exc)
            with self._lock:
                self._failed = True
                self._message = describe_download_error(exc)
        finally:
            with self._lock:
                self._current = None
                self._current_done = 0
