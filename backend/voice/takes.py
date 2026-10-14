"""Takes: pure logic for the take store (M3-4). No file or audio access.

Rule 1: takes are never auto-deleted; ``remove_takes`` runs only when the user
asks (storage manager). Rule 3: the raw key decides reuse, see ``keys.py``.
The Session does the file work through ``takestore.py``.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError

from backend.project.schema import Line, Project, Take
from backend.voice.keys import normalize_text

RAW_DIR = "media/takes_raw"

_HEX = frozenset("0123456789abcdef")


class TakeError(ValueError):
    """A take could not be created, found or removed."""


def raw_take_relpath(take_id: str) -> str:
    return f"{RAW_DIR}/{take_id}.wav"


@dataclass(frozen=True)
class NewTake:
    """Everything a generated take needs, except the audio itself."""

    line_id: str
    seed: int
    text: str
    exaggeration: float
    cfg_weight: float
    voice_profile_id: str
    model_version: str
    raw_key: str
    take_id: str | None = None  # None: a random id is picked


# --------------------------------------------------------------------------
# Finding and building
# --------------------------------------------------------------------------


def find_take_by_key(
    project: Project, raw_key: str, *, prefer_line_id: str | None = None
) -> Take | None:
    """A take with this raw key. A take of ``prefer_line_id`` wins over others."""
    first: Take | None = None
    for take in project.takes:
        if take.raw_key != raw_key:
            continue
        if prefer_line_id is not None and take.line_id == prefer_line_id:
            return take
        if first is None:
            first = take
    return first


def build_take(new: NewTake, take_id: str, raw_file: str, duration_ms: int) -> Take:
    """Validate and build the Take record (text is stored whitespace-normalized,
    which is what the raw key was computed from)."""
    text = normalize_text(new.text)
    if not text:
        raise TakeError("take text must not be empty")
    if len(new.raw_key) != 64 or not set(new.raw_key) <= _HEX:
        raise TakeError("raw_key must be 64 lowercase hex characters")
    try:
        return Take(
            id=take_id,
            line_id=new.line_id,
            seed=new.seed,
            text=text,
            exaggeration=new.exaggeration,
            cfg_weight=new.cfg_weight,
            voice_profile_id=new.voice_profile_id,
            model_version=new.model_version,
            raw_key=new.raw_key,
            raw_file=raw_file,
            duration_ms=duration_ms,
        )
    except ValidationError as exc:
        errors = exc.errors()
        detail = errors[0]["msg"] if errors else str(exc)
        where = ".".join(str(part) for part in errors[0]["loc"]) if errors else ""
        raise TakeError(f"invalid take ({where}): {detail}") from exc


# --------------------------------------------------------------------------
# Models the API returns
# --------------------------------------------------------------------------


class TakeItem(BaseModel):
    id: str
    line_id: str
    seed: int
    text: str
    exaggeration: float
    cfg_weight: float
    duration_ms: int
    starred: bool
    active: bool
    created: datetime
    raw_file: str
    file_exists: bool


class AddTakeResult(BaseModel):
    take: TakeItem
    # True when no audio was generated or written: an existing take was reused.
    reused: bool


def build_take_item(take: Take, line: Line, file_exists: bool) -> TakeItem:
    return TakeItem(
        id=take.id,
        line_id=take.line_id,
        seed=take.seed,
        text=take.text,
        exaggeration=take.exaggeration,
        cfg_weight=take.cfg_weight,
        duration_ms=take.duration_ms,
        starred=take.starred,
        active=line.active_take_id == take.id,
        created=take.created,
        raw_file=take.raw_file,
        file_exists=file_exists,
    )


# --------------------------------------------------------------------------
# Removing takes (storage manager)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TakeRemoval:
    take_ids: tuple[str, ...]
    # Project-relative files nothing else uses any more; the caller deletes them.
    files: tuple[str, ...]
    cleared_active_line_ids: tuple[str, ...]
    cleared_override_placement_ids: tuple[str, ...]


def remove_takes(project: Project, take_ids: Collection[str]) -> TakeRemoval:
    """Remove takes from the project (not from disk).

    Validates every id first, so an unknown id changes nothing. A line whose
    active take goes loses its active take; a placement whose take override goes
    falls back to the line's active take. Neither is orphaned or dropped.
    """
    wanted = set(take_ids)
    known = {take.id for take in project.takes}
    unknown = sorted(wanted - known)
    if unknown:
        raise TakeError(f"unknown take id {unknown[0]!r}")
    if not wanted:
        return TakeRemoval((), (), (), ())

    removed = [take for take in project.takes if take.id in wanted]
    kept = [take for take in project.takes if take.id not in wanted]
    still_used = {take.raw_file for take in kept}
    files = tuple(
        dict.fromkeys(
            take.raw_file for take in removed if take.raw_file not in still_used
        )
    )

    cleared_lines: list[str] = []
    for line in project.lines:
        if line.active_take_id in wanted:
            line.active_take_id = None
            cleared_lines.append(line.id)
    cleared_placements: list[str] = []
    for placement in project.placements:
        if placement.take_override_id in wanted:
            placement.take_override_id = None
            cleared_placements.append(placement.id)

    project.takes[:] = kept
    return TakeRemoval(
        take_ids=tuple(take.id for take in removed),
        files=files,
        cleared_active_line_ids=tuple(cleared_lines),
        cleared_override_placement_ids=tuple(cleared_placements),
    )


def remove_line_and_takes(project: Project, line_id: str) -> TakeRemoval:
    """Remove a line and all its takes (not from disk). Refused while the line
    is placed, so no placement is left pointing at a missing line."""
    index = next(
        (i for i, line in enumerate(project.lines) if line.id == line_id), None
    )
    if index is None:
        raise TakeError(f"unknown line id {line_id!r}")
    placed = sum(1 for p in project.placements if p.line_id == line_id)
    if placed:
        raise TakeError(
            f"cannot delete this line: {placed} placement(s) still use it "
            "(remove the placements first)"
        )
    removal = remove_takes(
        project, [take.id for take in project.takes if take.line_id == line_id]
    )
    del project.lines[index]
    return replace(
        removal,
        cleared_active_line_ids=tuple(
            x for x in removal.cleared_active_line_ids if x != line_id
        ),
    )


class TakeDeleteReport(BaseModel):
    removed_take_count: int
    removed_line: bool
    freed_bytes: int
    # Files that could not be deleted (for example still open); the takes are
    # gone from the project, the files show up as unreferenced in the storage report.
    failed_files: list[str] = Field(default_factory=list)
    cleared_active_line_ids: list[str] = Field(default_factory=list)
    cleared_override_placement_ids: list[str] = Field(default_factory=list)


def build_delete_report(
    removal: TakeRemoval,
    *,
    removed_line: bool,
    freed_bytes: int,
    failed_files: Collection[str],
) -> TakeDeleteReport:
    return TakeDeleteReport(
        removed_take_count=len(removal.take_ids),
        removed_line=removed_line,
        freed_bytes=freed_bytes,
        failed_files=list(failed_files),
        cleared_active_line_ids=list(removal.cleared_active_line_ids),
        cleared_override_placement_ids=list(removal.cleared_override_placement_ids),
    )


# --------------------------------------------------------------------------
# Storage manager report
# --------------------------------------------------------------------------


class TakeStorage(BaseModel):
    take_id: str
    seed: int
    duration_ms: int
    size_bytes: int
    file_exists: bool
    starred: bool
    active: bool


class LineStorage(BaseModel):
    line_id: str
    text: str
    take_count: int
    size_bytes: int
    takes: list[TakeStorage]


class UnreferencedFile(BaseModel):
    path: str
    size_bytes: int


class StorageReport(BaseModel):
    lines: list[LineStorage] = Field(default_factory=list)
    take_count: int = 0
    total_bytes: int = 0
    missing_file_count: int = 0
    # Files in media/takes_raw that no take points at (for example left by a
    # crash). Reported only; the app never deletes them by itself.
    unreferenced: list[UnreferencedFile] = Field(default_factory=list)
    unreferenced_bytes: int = 0


def build_storage_report(
    project: Project,
    sizes: Mapping[str, int | None],
    unreferenced: Mapping[str, int],
) -> StorageReport:
    """Sizes per line and take. ``sizes`` maps each take's raw file to its size on
    disk, or None when the file is missing. Lines without takes are left out."""
    by_line: dict[str, list[Take]] = {}
    for take in project.takes:
        by_line.setdefault(take.line_id, []).append(take)

    missing = 0

    def storage_for(takes: list[Take], active_id: str | None) -> list[TakeStorage]:
        nonlocal missing
        items: list[TakeStorage] = []
        for take in takes:
            size = sizes.get(take.raw_file)
            if size is None:
                missing += 1
            items.append(
                TakeStorage(
                    take_id=take.id,
                    seed=take.seed,
                    duration_ms=take.duration_ms,
                    size_bytes=size or 0,
                    file_exists=size is not None,
                    starred=take.starred,
                    active=take.id == active_id,
                )
            )
        return items

    lines: list[LineStorage] = []
    known_ids = {line.id for line in project.lines}
    for line in project.lines:
        takes = by_line.get(line.id, [])
        if not takes:
            continue
        items = storage_for(takes, line.active_take_id)
        lines.append(
            LineStorage(
                line_id=line.id,
                text=line.text,
                take_count=len(items),
                size_bytes=sum(item.size_bytes for item in items),
                takes=items,
            )
        )
    # Takes whose line is gone (should not happen) still count toward disk use.
    for line_id, takes in by_line.items():
        if line_id in known_ids:
            continue
        items = storage_for(takes, None)
        lines.append(
            LineStorage(
                line_id=line_id,
                text="(line missing)",
                take_count=len(items),
                size_bytes=sum(item.size_bytes for item in items),
                takes=items,
            )
        )

    extra = [
        UnreferencedFile(path=path, size_bytes=size)
        for path, size in sorted(unreferenced.items())
    ]
    return StorageReport(
        lines=lines,
        take_count=len(project.takes),
        total_bytes=sum(line.size_bytes for line in lines),
        missing_file_count=missing,
        unreferenced=extra,
        unreferenced_bytes=sum(item.size_bytes for item in extra),
    )
