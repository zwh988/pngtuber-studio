"""HTTP Range helpers for the media server (M2-S7), taken from the M0 spike.

``parse_range`` is pure. ``iter_file`` reads from disk in chunks so a
multi-gigabyte recording is never loaded into memory.
"""

import re
from collections.abc import Iterator
from pathlib import Path

CHUNK = 1024 * 1024


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """Parse one 'bytes=a-b' range into inclusive (start, end).

    Returns None when the header is malformed, asks for several ranges, or
    cannot be satisfied for a file of ``size`` bytes (the caller answers 416).
    """
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
    if match is None:
        return None
    start_s, end_s = match.groups()
    if start_s == "" and end_s == "":
        return None
    if start_s == "":
        suffix = int(end_s)
        if suffix == 0:
            return None
        start, end = max(size - suffix, 0), size - 1
    else:
        start = int(start_s)
        end = min(int(end_s), size - 1) if end_s else size - 1
    if start > end or start >= size:
        return None
    return start, end


def iter_file(path: Path, start: int, end: int, chunk: int = CHUNK) -> Iterator[bytes]:
    """Yield bytes ``start`` to ``end`` inclusive, at most ``chunk`` at a time.

    Stops early at end of file.
    """
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = f.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data
