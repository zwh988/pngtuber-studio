import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.media.ranges import iter_file, parse_range
from backend.project.commands import AddSource
from backend.project.schema import Source
from backend.project.session import Session

DATA = bytes(range(256)) * 40  # 10240 bytes, every byte value repeats


def hid(name: str) -> str:
    return hashlib.sha1(name.encode()).hexdigest()[:12]


# ---- pure: parse_range ---------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        ("bytes=0-99", 1000, (0, 99)),
        ("bytes=500-", 1000, (500, 999)),
        ("bytes=0-", 1000, (0, 999)),
        ("bytes=-100", 1000, (900, 999)),
        ("bytes=-5000", 1000, (0, 999)),
        ("bytes=0-5000", 1000, (0, 999)),
        ("bytes=999-999", 1000, (999, 999)),
        ("  bytes=0-9  ", 1000, (0, 9)),
    ],
)
def test_parse_range_valid(header: str, size: int, expected: tuple[int, int]) -> None:
    assert parse_range(header, size) == expected


@pytest.mark.parametrize(
    ("header", "size"),
    [
        ("bytes=1000-", 1000),
        ("bytes=2000-3000", 1000),
        ("bytes=5-2", 1000),
        ("bytes=-", 1000),
        ("bytes=-0", 1000),
        ("items=0-1", 1000),
        ("bytes=0-1,5-6", 1000),
        ("bytes=abc-", 1000),
        ("", 1000),
        ("bytes=0-", 0),
    ],
)
def test_parse_range_unsatisfiable_or_malformed(header: str, size: int) -> None:
    assert parse_range(header, size) is None


# ---- iter_file --------------------------------------------------------------------


def test_iter_file_returns_exact_slice_in_chunks(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(DATA)
    chunks = list(iter_file(path, 10, 600, chunk=100))
    assert b"".join(chunks) == DATA[10:601]
    assert all(len(c) <= 100 for c in chunks)
    assert len(chunks) == 6


def test_iter_file_stops_at_end_of_file(tmp_path: Path) -> None:
    path = tmp_path / "data.bin"
    path.write_bytes(DATA)
    assert b"".join(iter_file(path, 10_000, 99_999)) == DATA[10_000:]


def test_iter_file_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    assert list(iter_file(path, 0, -1)) == []


# ---- endpoint ---------------------------------------------------------------------


def _no_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("nothing should be probed")


def make_source(name: str, path: str, *, external: bool = False) -> Source:
    return Source(
        id=hid(name),
        external=external,
        path=path,
        duration_ms=10_000,
        fps_num=60,
        fps_den=1,
        width=2560,
        height=1440,
        audio_tracks=1,
    )


def open_session(tmp_path: Path) -> Session:
    session = Session(probe=_no_probe)
    session.new_project(str(tmp_path), "Rack")
    return session


def add_source(session: Session, source: Source) -> None:
    stack = session._stack
    assert stack is not None
    stack.execute(AddSource(source))


def client_for(session: Session, tmp_path: Path) -> TestClient:
    return TestClient(create_app(static_dir=tmp_path, session=session))


def session_with_clip_file(tmp_path: Path) -> tuple[Session, str]:
    """A project whose footage has a space in its file name."""
    session = open_session(tmp_path)
    footage = tmp_path / "Rack" / "footage"
    footage.mkdir(exist_ok=True)
    (footage / "clip a.mkv").write_bytes(DATA)
    add_source(session, make_source("s1", "footage/clip a.mkv"))
    return session, hid("s1")


def test_full_file_without_range(tmp_path: Path) -> None:
    session, source_id = session_with_clip_file(tmp_path)
    response = client_for(session, tmp_path).get(f"/media/source/{source_id}")
    assert response.status_code == 200
    assert response.content == DATA
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(DATA))


def test_bounded_range(tmp_path: Path) -> None:
    session, source_id = session_with_clip_file(tmp_path)
    response = client_for(session, tmp_path).get(
        f"/media/source/{source_id}", headers={"Range": "bytes=100-199"}
    )
    assert response.status_code == 206
    assert response.content == DATA[100:200]
    assert response.headers["content-range"] == f"bytes 100-199/{len(DATA)}"
    assert response.headers["content-length"] == "100"


def test_open_ended_range_like_the_browser_sends(tmp_path: Path) -> None:
    session, source_id = session_with_clip_file(tmp_path)
    response = client_for(session, tmp_path).get(
        f"/media/source/{source_id}", headers={"Range": "bytes=10000-"}
    )
    assert response.status_code == 206
    assert response.content == DATA[10_000:]
    assert response.headers["content-range"] == f"bytes 10000-{len(DATA) - 1}/{len(DATA)}"


def test_suffix_range(tmp_path: Path) -> None:
    session, source_id = session_with_clip_file(tmp_path)
    response = client_for(session, tmp_path).get(
        f"/media/source/{source_id}", headers={"Range": "bytes=-50"}
    )
    assert response.status_code == 206
    assert response.content == DATA[-50:]


def test_unsatisfiable_range_is_416(tmp_path: Path) -> None:
    session, source_id = session_with_clip_file(tmp_path)
    response = client_for(session, tmp_path).get(
        f"/media/source/{source_id}", headers={"Range": "bytes=999999-"}
    )
    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(DATA)}"


def test_unknown_source_is_404(tmp_path: Path) -> None:
    session, _ = session_with_clip_file(tmp_path)
    response = client_for(session, tmp_path).get(f"/media/source/{hid('nope')}")
    assert response.status_code == 404


def test_the_url_can_never_name_a_file(tmp_path: Path) -> None:
    session, _ = session_with_clip_file(tmp_path)
    client = client_for(session, tmp_path)
    for attempt in [
        "..%2Fproject.json",
        "..%2F..%2Fproject.json",
        "footage%2Fclip%20a.mkv",
        "footage/clip a.mkv",
    ]:
        assert client.get(f"/media/source/{attempt}").status_code == 404, attempt


def test_missing_file_is_404(tmp_path: Path) -> None:
    session = open_session(tmp_path)
    add_source(session, make_source("s1", "footage/gone.mkv"))
    response = client_for(session, tmp_path).get(f"/media/source/{hid('s1')}")
    assert response.status_code == 404


def test_no_open_project_is_404(tmp_path: Path) -> None:
    client = client_for(Session(probe=_no_probe), tmp_path)
    assert client.get(f"/media/source/{hid('s1')}").status_code == 404


def test_external_source_is_served_from_its_absolute_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(DATA)
    session = open_session(tmp_path)
    add_source(session, make_source("b1", outside.as_posix(), external=True))
    response = client_for(session, tmp_path).get(
        f"/media/source/{hid('b1')}", headers={"Range": "bytes=0-9"}
    )
    assert response.status_code == 206
    assert response.content == DATA[:10]


def test_only_sources_of_the_open_project_are_served(tmp_path: Path) -> None:
    session, source_id = session_with_clip_file(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "Rack2").mkdir()
    stranger = other / "stranger.mkv"
    stranger.write_bytes(DATA)
    # A file on disk is not served unless it is a source of the project.
    response = client_for(session, tmp_path).get(f"/media/source/{hid('stranger')}")
    assert response.status_code == 404
    assert source_id != hid("stranger")
