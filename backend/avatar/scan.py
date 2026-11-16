"""Read an avatar art folder from disk (M5-1) and describe it for the UI.

The only file access of the art loader: list the expression folders and their files,
read ``avatar.json``. Everything else is ``art.py`` (pure). The art is never copied or
changed (rule 2 applies to footage; the same care applies here).
"""

import json
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field

from backend.avatar.art import (
    CONFIG_NAME,
    STATES,
    AvatarArt,
    parse_art,
    parse_config,
    state_code,
)


class ArtFolderError(Exception):
    """The art folder cannot be read (missing, not a folder, no access)."""


def is_absolute_stored(art_folder: str) -> bool:
    """True for ``/x/y`` or ``D:/x/y`` (a stored absolute POSIX path)."""
    return art_folder.startswith("/") or (len(art_folder) >= 3 and art_folder[1:3] == ":/")


def resolve_art_folder(art_folder: str, project_folder: Path) -> Path:
    """Disk path of ``AvatarSettings.art_folder``: absolute as stored, or relative to
    the project folder."""
    if is_absolute_stored(art_folder):
        return Path(art_folder)
    return project_folder / Path(*PurePosixPath(art_folder).parts)


def to_stored_path(path: Path, project_folder: Path) -> str:
    """How a chosen folder is stored: relative POSIX when inside the project folder,
    otherwise absolute POSIX (like a template's external bookends)."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(project_folder.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def read_listing(folder: Path) -> dict[str, list[str]]:
    """``{subfolder name: [file names]}`` of an art folder (one level deep)."""
    if not folder.is_dir():
        raise ArtFolderError(f"art folder not found: {folder}")
    listing: dict[str, list[str]] = {}
    try:
        for child in folder.iterdir():
            if child.is_dir():
                listing[child.name] = [f.name for f in child.iterdir() if f.is_file()]
    except OSError as exc:
        raise ArtFolderError(f"cannot read the art folder: {exc}") from exc
    return listing


def scan_art_folder(folder: Path) -> AvatarArt:
    """Parse the art in ``folder`` (with its ``avatar.json`` when present)."""
    listing = read_listing(folder)
    config_path = folder / CONFIG_NAME
    data = None
    config_warning: str | None = None
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            config_warning = f"{CONFIG_NAME} cannot be read ({exc}); ignored"
    config = parse_config(data)
    if config_warning is not None:
        config = type(config)(
            config.default_expression, config.emotion_map, (*config.warnings, config_warning)
        )
    return parse_art(listing, config)


# --- state for the API --------------------------------------------------------------


class ExpressionItem(BaseModel):
    id: str
    order: int
    folder: str
    states: list[str]  # state codes present, e.g. ["oicm", "oiom", "cicm", "ciom"]
    complete: bool


class AvatarState(BaseModel):
    """``GET /api/avatar``. ``status``: ``not_configured`` (no folder set),
    ``folder_missing`` (cannot be read), ``no_art`` (no usable sprite), ``ready``."""

    status: str
    art_folder: str | None  # as stored in the project
    resolved_folder: str | None  # where it was looked for on disk
    external: bool  # stored as an absolute path (breaks if the project moves machine)
    name: str | None  # the art folder's own name ("nanairo miku")
    expressions: list[ExpressionItem] = Field(default_factory=list)
    default_expression: str | None = None
    emotion_map: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    problem: str | None = None
    can_undo: bool = False
    can_redo: bool = False
    undo_label: str | None = None
    redo_label: str | None = None
    save_error: str | None = None


def build_avatar_state(art_folder: str | None, project_folder: Path) -> AvatarState:
    """Scan the project's art folder and describe it. Never raises for bad art."""
    if art_folder is None:
        return AvatarState(
            status="not_configured", art_folder=None, resolved_folder=None,
            external=False, name=None,
        )
    folder = resolve_art_folder(art_folder, project_folder)
    external = is_absolute_stored(art_folder)
    base = {
        "art_folder": art_folder,
        "resolved_folder": str(folder),
        "external": external,
        "name": folder.name,
    }
    try:
        art = scan_art_folder(folder)
    except ArtFolderError as exc:
        return AvatarState(status="folder_missing", problem=str(exc), **base)
    items = [
        ExpressionItem(
            id=e.id,
            order=e.order,
            folder=e.folder,
            states=[state_code(s) for s in STATES if s in e.sprites],
            complete=e.complete,
        )
        for e in art.expressions
    ]
    return AvatarState(
        status="ready" if art.usable else "no_art",
        expressions=items,
        default_expression=art.default_expression,
        emotion_map=dict(art.emotion_map),
        warnings=list(art.warnings),
        problem=None if art.usable else "the folder holds no usable sprites",
        **base,
    )


def avatar_status_text(state: AvatarState) -> str:
    """One line for the project summary."""
    if state.status == "not_configured":
        return "not configured"
    if state.status == "folder_missing":
        return "art folder missing"
    if state.status == "no_art":
        return "no usable art"
    warn = f", {len(state.warnings)} warnings" if state.warnings else ""
    return f"{state.name}: {len(state.expressions)} expressions{warn}"
