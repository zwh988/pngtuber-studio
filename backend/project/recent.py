"""Recent projects list, stored per user outside any project (M1-6).

The list functions are pure. ``load_recent`` / ``save_recent`` are the I/O edge.
Default location: ``%APPDATA%\\PNGtuberStudio\\recent.json``.
"""

import json
import os
import tempfile
from pathlib import Path, PureWindowsPath

from pydantic import BaseModel, ValidationError

MAX_RECENT = 10
RECENT_FILE_VERSION = 1


class RecentEntry(BaseModel):
    name: str
    folder: str
    last_opened: str  # ISO 8601 timestamp


class RecentItem(RecentEntry):
    """A recent entry plus whether its ``project.json`` still exists."""

    exists: bool


def folder_key(folder: str) -> str:
    """Identity of a folder for de-duplication (Windows: case-insensitive)."""
    return str(PureWindowsPath(folder.strip())).casefold()


def add_recent(
    entries: list[RecentEntry],
    name: str,
    folder: str,
    opened_at: str,
    limit: int = MAX_RECENT,
) -> list[RecentEntry]:
    """Return a new list with this project first; older duplicates are dropped."""
    key = folder_key(folder)
    kept = [entry for entry in entries if folder_key(entry.folder) != key]
    fresh = RecentEntry(name=name, folder=folder, last_opened=opened_at)
    return [fresh, *kept][:limit]


def remove_recent(entries: list[RecentEntry], folder: str) -> list[RecentEntry]:
    key = folder_key(folder)
    return [entry for entry in entries if folder_key(entry.folder) != key]


def parse_recent(data: object) -> list[RecentEntry]:
    """Tolerant parse: anything malformed is skipped, never raised."""
    if not isinstance(data, dict):
        return []
    items = data.get("recent")
    if not isinstance(items, list):
        return []
    result: list[RecentEntry] = []
    for item in items:
        try:
            result.append(RecentEntry.model_validate(item))
        except ValidationError:
            continue
    return result


def default_recent_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "PNGtuberStudio" / "recent.json"


def load_recent(path: Path) -> list[RecentEntry]:
    """Missing or corrupt files give an empty list."""
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError):
        return []
    return parse_recent(data)


def save_recent(path: Path, entries: list[RecentEntry]) -> None:
    """Atomic write: temp file in the same folder, flush, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "version": RECENT_FILE_VERSION,
            "recent": [entry.model_dump() for entry in entries],
        },
        indent=2,
    )
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix="recent.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
