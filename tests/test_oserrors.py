"""Plain-language file errors (M7 S4)."""

import errno

from backend.oserrors import describe_error, find_os_error, plain_os_error


def win_error(winerror: int, err: int, filename: str | None = None) -> OSError:
    exc = OSError(err, "system text", filename)
    exc.winerror = winerror  # type: ignore[attr-defined]  # set by Windows only
    return exc


def test_disk_full_names_the_drive() -> None:
    exc = OSError(errno.ENOSPC, "No space left on device", r"D:\Rack 1\project.json.tmp")
    assert plain_os_error(exc) == "The disk is full on drive D:. Free some space, then try again."


def test_disk_full_by_winerror_without_a_file() -> None:
    text = plain_os_error(win_error(112, 0))
    assert text == "The disk is full. Free some space, then try again."


def test_a_file_in_use_is_not_reported_as_access_denied() -> None:
    exc = win_error(32, errno.EACCES, r"C:\x\exports\video.mp4")
    assert plain_os_error(exc) == (
        "video.mp4 is open in another program. Close it there, then try again."
    )


def test_access_denied() -> None:
    text = plain_os_error(PermissionError(errno.EACCES, "denied", r"C:\x\media\take.wav"))
    assert text is not None
    assert text.startswith("Windows refused access to take.wav.")
    assert "read-only" in text


def test_found_through_raise_from() -> None:
    class ProjectError(Exception):
        pass

    try:
        try:
            raise OSError(errno.ENOSPC, "No space left on device", r"E:\p\project.json")
        except OSError as inner:
            raise ProjectError("cannot write project.json") from inner
    except ProjectError as outer:
        assert isinstance(find_os_error(outer), OSError)
        assert describe_error(outer).startswith("The disk is full on drive E:")


def test_other_errors_keep_their_own_text() -> None:
    assert plain_os_error(ValueError("bad")) is None
    assert plain_os_error(FileNotFoundError(errno.ENOENT, "gone", "x.wav")) is None
    assert describe_error(ValueError("bad value")) == "bad value"
    assert describe_error(RuntimeError()) == "RuntimeError"
