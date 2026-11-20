"""Files dropped from Explorer onto a video lane (M8-2).

- Images (PNG, JPG) are copied into the project's ``images/`` folder; dropping the
  same file again (same name and size) reuses the copy (decision 6, 2026-11-20).
- A video already inside ``footage/`` is used where it is (rule 2). A video from
  anywhere else is copied into ``footage/`` once (the user-asked exception to rule
  2), then probed and used like any recording. A copy with the same name and size
  already in ``footage/`` is used instead of copying again.

Pure parts: ``IMAGE_EXTENSIONS``, ``media_kind``, ``same_file_in``.
I/O parts: ``read_image_size``, ``import_image``, ``import_video``.
"""

import os
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from backend.audio.clipimport import copy_name
from backend.project.footage import (
    FOOTAGE_DIR,
    VIDEO_EXTENSIONS,
    ProbeError,
    parse_probe,
)
from backend.project.relink import to_footage_relpath
from backend.project.schema import ImageFile, Source, new_id
from backend.project.timeline import TimelineState

IMAGES_DIR = "images"
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg"})

Probe = Callable[[Path], dict[str, Any]]


class LaneImportError(Exception):
    """A dropped file cannot be used; the message is for the user."""


class LaneImportRequest(BaseModel):
    """Files dropped on a video lane (full paths from the pywebview drop handler)."""

    paths: list[str] = Field(min_length=1, max_length=50)
    # The lane under the drop point; None: the lowest lane (one is made when none).
    lane_id: str | None = None
    timeline_ms: int = Field(ge=0)
    # True: dropped on "+ Video lane", so the files go on a new lane on top.
    new_lane: bool = False


class ImportedLaneMedia(BaseModel):
    name: str
    kind: Literal["image", "video"]
    clip_id: str
    lane_id: str
    lane_name: str
    timeline_ms: int
    # A video copied into footage/ by this drop (the editor says so).
    copied_to_footage: bool = False


class LaneImportResult(BaseModel):
    imported: list[ImportedLaneMedia] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    timeline: TimelineState


# --------------------------------------------------------------------------
# Pure
# --------------------------------------------------------------------------


def media_kind(name: str) -> Literal["image", "video"] | None:
    suffix = PurePosixPath(name.replace("\\", "/")).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return None


def same_file_in(
    names_and_sizes: Sequence[tuple[str, int]], name: str, size: int
) -> str | None:
    """The first listed name equal to ``name`` (case-insensitive) with ``size`` bytes."""
    key = name.casefold()
    for candidate, candidate_size in names_and_sizes:
        if candidate.casefold() == key and candidate_size == size:
            return candidate
    return None


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------


def read_image_size(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.size
    except (OSError, UnidentifiedImageError) as exc:
        raise LaneImportError(f"{path.name}: not a readable image ({exc})") from exc


def _copy(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        shutil.copyfile(source, tmp)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _listing(folder: Path) -> list[tuple[str, int]]:
    if not folder.is_dir():
        return []
    return [(p.name, p.stat().st_size) for p in folder.iterdir() if p.is_file()]


def import_image(
    project_folder: Path, source: Path, known: Sequence[ImageFile]
) -> tuple[ImageFile, bool]:
    """Bring one dropped image into ``images/``. Returns the ``ImageFile`` and whether
    it was already in the project (True: nothing to register)."""
    name = source.name
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise LaneImportError(f"{name}: cannot read the file: {exc}") from exc
    for image in known:
        if image.name.casefold() == name.casefold() and image.size_bytes == size:
            return image, True
    folder = project_folder / IMAGES_DIR
    taken = {PurePosixPath(i.path).name.casefold() for i in known}
    left = same_file_in(
        [(n, s) for n, s in _listing(folder) if n.casefold() not in taken], name, size
    )
    copied = False
    if left is not None:
        dest = folder / left  # left by an undone import
    else:
        dest = folder / copy_name(name, [n for n, _ in _listing(folder)] + list(taken))
        try:
            _copy(source, dest)
        except OSError as exc:
            raise LaneImportError(
                f"{name}: cannot copy it into the project: {exc}"
            ) from exc
        copied = True
    try:
        width, height = read_image_size(dest)
    except LaneImportError:
        if copied:
            dest.unlink(missing_ok=True)
        raise
    image = ImageFile(
        id=new_id(),
        path=f"{IMAGES_DIR}/{dest.name}",
        name=name,
        size_bytes=size,
        width=width,
        height=height,
    )
    return image, False


def import_video(
    project_folder: Path,
    source: Path,
    known: Sequence[Source],
    *,
    probe: Probe,
) -> tuple[Source, bool, bool]:
    """Bring one dropped video into the project.

    Returns (source, is_new, copied): ``is_new`` means the ``Source`` still has to be
    added with ``AddSource``; ``copied`` means this call copied the file into
    ``footage/``.
    """
    name = source.name
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise LaneImportError(f"{name}: cannot read the file: {exc}") from exc
    footage = project_folder / FOOTAGE_DIR
    copied = False
    try:
        rel = to_footage_relpath(project_folder.resolve(), source.resolve())
    except ValueError:
        rel = None
    if rel is None:
        found = same_file_in(_listing(footage), name, size)
        if found is not None:
            rel = f"{FOOTAGE_DIR}/{found}"
        else:
            dest = footage / copy_name(name, [n for n, _ in _listing(footage)])
            try:
                _copy(source, dest)
            except OSError as exc:
                raise LaneImportError(
                    f"{name}: cannot copy it into the footage folder: {exc}"
                ) from exc
            rel = f"{FOOTAGE_DIR}/{dest.name}"
            copied = True
    for known_source in known:
        if not known_source.external and known_source.path.casefold() == rel.casefold():
            return known_source, False, copied
    try:
        new_source = parse_probe(probe(project_folder / rel), rel)
    except (ProbeError, OSError) as exc:
        if copied:
            (project_folder / rel).unlink(missing_ok=True)
        raise LaneImportError(str(exc)) from exc
    except Exception as exc:  # ffprobe missing
        if copied:
            (project_folder / rel).unlink(missing_ok=True)
        raise LaneImportError(str(exc)) from exc
    return new_source, True, copied
