"""Pure helpers for relinking a moved footage file (M1-6).

Both functions work on values only; the caller resolves real paths and runs
ffprobe.
"""

from pathlib import PurePath

from backend.project.schema import Source

DURATION_TOLERANCE_MS = 100


def to_footage_relpath(project_folder: PurePath, picked: PurePath) -> str:
    """Relative POSIX path of ``picked`` under ``<project>/footage``.

    Raises ``ValueError`` when the file is outside the footage folder (the app
    never copies footage, so the user has to move it there first).
    """
    message = (
        "the file must be inside the project's footage folder "
        f"({project_folder / 'footage'}); move it there first"
    )
    try:
        rel = picked.relative_to(project_folder)
    except ValueError:
        raise ValueError(message) from None
    if len(rel.parts) < 2 or rel.parts[0].casefold() != "footage":
        raise ValueError(message)
    return rel.as_posix()


def relink_mismatches(
    old: Source,
    new: Source,
    duration_tolerance_ms: int = DURATION_TOLERANCE_MS,
) -> list[str]:
    """Why ``new`` is not the same footage as ``old`` (empty list = match)."""
    problems: list[str] = []
    if (old.width, old.height) != (new.width, new.height):
        problems.append(
            f"resolution is {new.width}x{new.height}, expected {old.width}x{old.height}"
        )
    if old.fps_num * new.fps_den != new.fps_num * old.fps_den:
        problems.append(f"frame rate is {new.fps:.3f}, expected {old.fps:.3f}")
    if abs(old.duration_ms - new.duration_ms) > duration_tolerance_ms:
        problems.append(
            f"length is {new.duration_ms} ms, expected {old.duration_ms} ms"
        )
    if old.audio_tracks != new.audio_tracks:
        problems.append(
            f"has {new.audio_tracks} audio track(s), expected {old.audio_tracks}"
        )
    return problems
