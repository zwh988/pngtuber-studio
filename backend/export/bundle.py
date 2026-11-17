"""The export bundle (M6-6): folder naming, raw video links, the avatar PNG sequence,
the project snapshot and ``export.json``.

Nothing outside the export folder is written, and footage is never copied or changed
(rule 2): ``video_raw/`` holds NTFS hard links (the same file under a second name, no
extra disk), and when a link is impossible (another drive, a file system without hard
links) ``video_raw/LINKS.txt`` gives the full path instead.
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.export.errors import ExportError
from backend.project.schema import Project

RAW_DIR = "video_raw"
LINKS_NAME = "LINKS.txt"
OVERLAY_DIR = "avatar_overlay"
OVERLAY_README = "README.txt"
SNAPSHOT_NAME = "project.json"
MANIFEST_NAME = "export.json"
INCOMPLETE_SUFFIX = " (incomplete)"


def export_folder_name(now: datetime) -> str:
    """``2026-11-17 1534``: sorts by time, safe on Windows."""
    return now.strftime("%Y-%m-%d %H%M")


def unique_folder(parent: Path, name: str) -> Path:
    """``parent/name``, or ``name (2)``, ``name (3)``... when taken. Not created."""
    candidate = parent / name
    n = 2
    while candidate.exists():
        candidate = parent / f"{name} ({n})"
        n += 1
    return candidate


def mark_incomplete(folder: Path) -> Path:
    """Rename a cancelled or failed export folder; nothing in it is deleted. Returns
    where it is now (the old path when the rename is impossible)."""
    target = unique_folder(folder.parent, folder.name + INCOMPLETE_SUFFIX)
    try:
        folder.rename(target)
    except OSError:
        return folder
    return target


# --- raw video links ------------------------------------------------------------------


@dataclass(frozen=True)
class RawLinks:
    linked: list[str] = field(default_factory=list)  # file names inside video_raw/
    listed: list[str] = field(default_factory=list)  # full paths written to LINKS.txt


def raw_link_names(paths: Sequence[Path]) -> list[str]:
    """A file name per footage path; a name used twice gets ``2_``, ``3_``... in front."""
    names: list[str] = []
    seen: set[str] = set()
    for path in paths:
        name = path.name
        n = 2
        while name.lower() in seen:
            name = f"{n}_{path.name}"
            n += 1
        seen.add(name.lower())
        names.append(name)
    return names


def _real_path(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def link_raw_videos(
    paths: Sequence[Path],
    out_dir: Path,
    link: Callable[[Path, Path], None] = os.link,
) -> RawLinks:
    """Hard-link each footage file into ``video_raw/``; list the ones that cannot be
    linked (with the reason) in ``LINKS.txt``. Never copies."""
    unique = list(dict.fromkeys(paths))
    if not unique:
        return RawLinks()
    folder = out_dir / RAW_DIR
    folder.mkdir(parents=True, exist_ok=True)
    linked: list[str] = []
    listed: list[str] = []
    notes: list[str] = []
    for path, name in zip(unique, raw_link_names(unique), strict=True):
        try:
            link(path, folder / name)
            linked.append(name)
        except OSError as exc:
            real = _real_path(path)  # through junctions and links: where the file really is
            listed.append(str(real))
            notes.append(f"{real}\n    (not linked: {exc.strerror or exc})")
    if notes:
        text = (
            "These recordings could not be hard-linked here (a hard link only works on the\n"
            "same drive). They were not copied; this is where they are:\n\n" + "\n".join(notes) + "\n"
        )
        (folder / LINKS_NAME).write_text(text, encoding="utf-8")
    return RawLinks(linked=linked, listed=listed)


# --- avatar PNG sequence --------------------------------------------------------------


def png_name(k: int) -> str:
    return f"frame_{k:06d}.png"


def write_overlay_readme(out_dir: Path, count: int, fps: int, width: int, height: int) -> Path:
    """``avatar_overlay/README.txt`` next to the PNGs (written by ffmpeg during the render,
    see ``runner.OVERLAY_ENCODE_ARGS``)."""
    folder = out_dir / OVERLAY_DIR
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / OVERLAY_README
    dest.write_text(
        "\n".join(
            [
                f"Transparent avatar overlay: {count} frames, {fps} fps, {width}x{height}, RGBA PNG.",
                f"Frame N starts at N / {fps} s of the exported video. In DaVinci Resolve, add this",
                f"folder to the Media Pool: the frames show up as one clip; set its frame rate to {fps}.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return dest


# --- snapshot and manifest ------------------------------------------------------------


def write_snapshot(project: Project, out_dir: Path) -> Path:
    """The project as it was exported (``project.json``, same format as the project's)."""
    dest = out_dir / SNAPSHOT_NAME
    dest.write_text(project.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return dest


def ffmpeg_version(ffmpeg: Path) -> str:
    """First line of ``ffmpeg -version`` ("unknown" when it cannot be read)."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(
            [str(ffmpeg), "-version"],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=flags,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    first = result.stdout.splitlines()[0] if result.stdout else ""
    return first.strip() or "unknown"


def file_list(out_dir: Path) -> list[dict[str, Any]]:
    """Top-level files with sizes and folders with their file count (for export.json)."""
    items: list[dict[str, Any]] = []
    for path in sorted(out_dir.iterdir(), key=lambda p: p.name.lower()):
        if path.name == MANIFEST_NAME:
            continue
        if path.is_dir():
            items.append({"name": path.name + "/", "files": sum(1 for _ in path.iterdir())})
        else:
            items.append({"name": path.name, "bytes": path.stat().st_size})
    return items


def write_manifest(out_dir: Path, info: Mapping[str, Any]) -> Path:
    """``export.json``: ``info`` plus the file list."""
    data = {**info, "files": file_list(out_dir)}
    dest = out_dir / MANIFEST_NAME
    dest.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    return dest


def ensure_new_folder(folder: Path) -> None:
    if folder.exists() and any(folder.iterdir()):
        raise ExportError(f"the export folder is not empty: {folder}")
    folder.mkdir(parents=True, exist_ok=True)
