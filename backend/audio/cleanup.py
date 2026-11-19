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

M7 S4 adds the two other re-creatable caches with the same age rule:
``media/envelopes/`` (``<processed stem>.env.json``, kept while its processed take
is in ``takes_fx``) and ``media/avatar_preview/`` (``<16 hex>.png``, kept while it
is the preview of a sprite in the current art). ``plan_cache_cleanup`` and
``run_cache_cleanup`` handle both.
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
ENVELOPE_FILE = re.compile(r"^[0-9a-f]{16}\.env\.json$")
PREVIEW_FILE = re.compile(r"^[0-9a-f]{16}\.png$")


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


def plan_cache_cleanup(
    entries: Iterable[FxEntry],
    keep: Collection[str] | None,
    pattern: re.Pattern[str],
    now: float,
    min_age_s: float = MIN_AGE_S,
) -> list[str]:
    """Names to delete in a derived-cache folder: a file matching ``pattern`` that
    is not in ``keep`` and is old, and any old ``*.tmp``. ``keep`` None means the
    wanted set is unknown (for example the art folder cannot be read): then only
    temp files go. Other files are left alone."""
    doomed: list[str] = []
    for entry in entries:
        if now - entry.mtime < min_age_s:
            continue
        if entry.name.endswith(".tmp") or keep is not None and pattern.match(entry.name) and entry.name not in keep:
            doomed.append(entry.name)
    return sorted(doomed)


def envelope_keep_names(fx_folder: Path) -> set[str]:
    """``<stem>.env.json`` for every processed take still in ``fx_folder``."""
    try:
        return {f"{p.stem}.env.json" for p in fx_folder.iterdir() if _PROCESSED.match(p.name)}
    except OSError:
        return set()


def _list_entries(folder: Path) -> list[FxEntry] | None:
    entries: list[FxEntry] = []
    try:
        with os.scandir(folder) as scan:
            for item in scan:
                try:
                    if not item.is_file(follow_symlinks=False):
                        continue
                    stat = item.stat(follow_symlinks=False)
                except OSError:
                    continue
                entries.append(FxEntry(item.name, stat.st_size, stat.st_mtime))
    except OSError:
        return None
    return entries


def _delete(folder: Path, names: Iterable[str], sizes: dict[str, int]) -> CleanupReport:
    deleted: list[str] = []
    failed: list[str] = []
    for name in names:
        try:
            (folder / name).unlink(missing_ok=True)
        except OSError:
            failed.append(name)
        else:
            deleted.append(name)
    return CleanupReport(
        deleted=tuple(deleted),
        freed_bytes=sum(sizes[name] for name in deleted),
        failed=tuple(failed),
    )


def run_cache_cleanup(
    folder: Path,
    keep: Collection[str] | None,
    pattern: re.Pattern[str],
    *,
    now: float | None = None,
    min_age_s: float = MIN_AGE_S,
) -> CleanupReport:
    """Delete what ``plan_cache_cleanup`` picks in ``folder``. Never raises."""
    entries = _list_entries(folder)
    if entries is None:
        return CleanupReport()
    when = time.time() if now is None else now
    sizes = {entry.name: entry.size for entry in entries}
    return _delete(folder, plan_cache_cleanup(entries, keep, pattern, when, min_age_s), sizes)


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
    entries = _list_entries(fx_folder)
    if entries is None:
        return CleanupReport()

    raw_stems: set[str] | None
    try:
        raw_stems = {p.stem for p in raw_folder.iterdir() if p.suffix == ".wav"}
    except OSError:
        raw_stems = None

    when = time.time() if now is None else now
    sizes = {entry.name: entry.size for entry in entries}
    doomed = plan_cleanup(entries, wanted_names, raw_stems, when, min_age_s)
    return _delete(fx_folder, doomed, sizes)
