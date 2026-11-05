"""Clean-up of ``media/takes_fx`` (M4-1, S3b): drop re-creatable files nobody uses.

Everything in ``takes_fx`` can be rendered again, so removing it is safe, but a file
that was just used must survive: undo of a chain change goes back to files rendered a
minute ago. The rules:

- a processed take (``<16 hex>.wav``) goes when the current project does not want it
  and it has not been touched for ``MIN_AGE_S``;
- an old Tighten copy (``<stem>_x<n>.wav``, from M3) goes after the same age: nothing
  in M4 asks for it, and it is re-created on demand if something does;
- a leftover temp file (``*.tmp``) goes after the same age;
- a trim sidecar (``<stem>.trim.json``) goes only when its raw take no longer exists.

Anything else in the folder is left alone, and raw takes are never touched (rule 1).
``plan_cleanup`` is pure; ``run_cleanup`` is the I/O edge.
"""

import os
import re
import time
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from pathlib import Path

MIN_AGE_S = 600.0  # ten minutes

_PROCESSED = re.compile(r"^[0-9a-f]{16}\.wav$")
_STRETCHED = re.compile(r"^.+_x\d+\.wav$")
_SIDECAR = re.compile(r"^(?P<stem>.+)\.trim\.json$")


@dataclass(frozen=True)
class FxEntry:
    name: str  # file name inside takes_fx
    size: int
    mtime: float  # seconds since the epoch


@dataclass(frozen=True)
class CleanupReport:
    deleted: tuple[str, ...] = ()
    freed_bytes: int = 0
    failed: tuple[str, ...] = ()


def plan_cleanup(
    entries: Iterable[FxEntry],
    wanted_names: Collection[str],
    raw_stems: Collection[str] | None,
    now: float,
    min_age_s: float = MIN_AGE_S,
) -> list[str]:
    """Names of the files to delete.

    ``wanted_names`` are processed file names the current project needs.
    ``raw_stems`` are the stems of the raw take files that exist; ``None`` means
    unknown, and then no sidecar is deleted.
    """
    wanted = set(wanted_names)
    stems = None if raw_stems is None else set(raw_stems)
    doomed: list[str] = []
    for entry in entries:
        name = entry.name
        old = now - entry.mtime >= min_age_s
        sidecar = _SIDECAR.match(name)
        if sidecar is not None:
            if stems is not None and sidecar["stem"] not in stems:
                doomed.append(name)
        elif name.endswith(".tmp"):
            if old:
                doomed.append(name)
        elif _PROCESSED.match(name):
            if name not in wanted and old:
                doomed.append(name)
        elif _STRETCHED.match(name) and old:
            doomed.append(name)
    return sorted(doomed)


def run_cleanup(
    fx_folder: Path,
    raw_folder: Path,
    wanted_names: Collection[str],
    *,
    now: float | None = None,
    min_age_s: float = MIN_AGE_S,
) -> CleanupReport:
    """Delete what ``plan_cleanup`` picks in ``fx_folder``. Never raises for files:
    one that cannot be deleted is reported in ``failed``."""
    entries: list[FxEntry] = []
    try:
        with os.scandir(fx_folder) as scan:
            for item in scan:
                try:
                    if not item.is_file(follow_symlinks=False):
                        continue
                    stat = item.stat(follow_symlinks=False)
                except OSError:
                    continue
                entries.append(FxEntry(item.name, stat.st_size, stat.st_mtime))
    except OSError:
        return CleanupReport()

    raw_stems: set[str] | None
    try:
        raw_stems = {p.stem for p in raw_folder.iterdir() if p.suffix == ".wav"}
    except OSError:
        raw_stems = None

    when = time.time() if now is None else now
    sizes = {entry.name: entry.size for entry in entries}
    deleted: list[str] = []
    failed: list[str] = []
    for name in plan_cleanup(entries, wanted_names, raw_stems, when, min_age_s):
        try:
            (fx_folder / name).unlink(missing_ok=True)
        except OSError:
            failed.append(name)
        else:
            deleted.append(name)
    return CleanupReport(
        deleted=tuple(deleted),
        freed_bytes=sum(sizes[name] for name in deleted),
        failed=tuple(failed),
    )
