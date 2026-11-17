"""Plain-language text for file errors the user can fix (M7 S4). Pure.

A full disk, a file another program holds open, and a folder Windows will not let
the app write to all reach the UI as raw ``[WinError 112] ...`` text otherwise.
``plain_os_error`` finds the ``OSError`` behind an exception (also through
``raise ... from``) and says what happened and what to do; anything else is left
to the caller's own message.
"""

import errno
from pathlib import PureWindowsPath

DISK_FULL_WINERRORS = frozenset({39, 112})  # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
IN_USE_WINERRORS = frozenset({32, 33})  # sharing and lock violations
ACCESS_WINERRORS = frozenset({5})  # ERROR_ACCESS_DENIED
MAX_CHAIN = 10


def find_os_error(exc: BaseException) -> OSError | None:
    """``exc`` itself or the first ``OSError`` among its causes."""
    seen: BaseException | None = exc
    for _ in range(MAX_CHAIN):
        if seen is None:
            return None
        if isinstance(seen, OSError):
            return seen
        seen = seen.__cause__ or seen.__context__
    return None


def _file_name(err: OSError) -> str | None:
    name = err.filename
    if not isinstance(name, str) or not name:
        return None
    return PureWindowsPath(name).name or name


def _drive(err: OSError) -> str | None:
    name = err.filename
    if not isinstance(name, str) or not name:
        return None
    return PureWindowsPath(name).drive or None


def plain_os_error(exc: BaseException) -> str | None:
    """A sentence for a disk-full, in-use or access-denied error, else None."""
    err = find_os_error(exc)
    if err is None:
        return None
    winerror = getattr(err, "winerror", None)
    name = _file_name(err)
    if err.errno == errno.ENOSPC or winerror in DISK_FULL_WINERRORS:
        drive = _drive(err)
        where = f" on drive {drive}" if drive else ""
        return f"The disk is full{where}. Free some space, then try again."
    # Windows reports a sharing violation as EACCES too, so check it first.
    if winerror in IN_USE_WINERRORS:
        what = name or "A file"
        return f"{what} is open in another program. Close it there, then try again."
    if err.errno == errno.EACCES or winerror in ACCESS_WINERRORS:
        what = name or "a file"
        return (
            f"Windows refused access to {what}. Check that the folder is not "
            "read-only or open in another program, then try again."
        )
    return None


def describe_error(exc: BaseException) -> str:
    """``plain_os_error`` when it applies, else the exception's own text."""
    return plain_os_error(exc) or str(exc) or type(exc).__name__
