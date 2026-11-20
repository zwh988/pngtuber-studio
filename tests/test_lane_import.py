"""Images and videos dropped on the video lanes (M8-2). ffprobe is faked."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import create_app
from backend.project.laneimport import (
    LaneImportError,
    import_image,
    import_video,
    media_kind,
    same_file_in,
)
from backend.project.schema import Source
from backend.project.session import Session

VIDEO_MS = 8000


def fake_probe(path: Path) -> dict[str, Any]:
    return {
        "streams": [
            {
                "codec_type": "video",
                "avg_frame_rate": "30/1",
                "width": 1280,
                "height": 720,
            },
            {"codec_type": "audio"},
        ],
        "format": {"duration": str(VIDEO_MS / 1000)},
    }


def write_png(path: Path, size: tuple[int, int] = (64, 32)) -> Path:
    Image.new("RGBA", size, (255, 0, 0, 128)).save(path)
    return path


def write_video(path: Path, payload: bytes = b"not really a video") -> Path:
    path.write_bytes(payload)
    return path


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    folder = tmp_path / "my stuff"
    folder.mkdir()
    return folder


# ---- pure ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("a.PNG", "image"),
        ("b.jpg", "image"),
        ("c.jpeg", "image"),
        ("d.mkv", "video"),
        ("e.mp4", "video"),
        ("f.wav", None),
        ("g", None),
    ],
)
def test_media_kind(name: str, kind: str | None) -> None:
    assert media_kind(name) == kind


def test_same_file_in() -> None:
    listing = [("A.mp4", 10), ("b.mp4", 20)]
    assert same_file_in(listing, "a.MP4", 10) == "A.mp4"
    assert same_file_in(listing, "a.mp4", 11) is None


# ---- images ----------------------------------------------------------------------


def test_import_image_copies_and_reuses(tmp_path: Path, outside: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    png = write_png(outside / "Title Card.png", (800, 200))
    image, reused = import_image(project, png, [])
    assert not reused and image.path == "images/Title Card.png"
    assert (image.width, image.height) == (800, 200)
    assert (project / image.path).read_bytes() == png.read_bytes()
    again, reused = import_image(project, png, [image])
    assert reused and again is image
    undone, reused = import_image(project, png, [])  # the copy left by an undone import
    assert not reused and undone.path == image.path
    assert [p.name for p in (project / "images").iterdir()] == ["Title Card.png"]


def test_import_image_refuses_a_broken_file(tmp_path: Path, outside: Path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    bad = outside / "bad.png"
    bad.write_bytes(b"nope")
    with pytest.raises(LaneImportError, match="not a readable image"):
        import_image(project, bad, [])
    assert list((project / "images").iterdir()) == []


# ---- videos ----------------------------------------------------------------------


def test_video_inside_footage_is_used_where_it_is(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    (project / "footage" / "sub").mkdir(parents=True)
    video = write_video(project / "footage" / "sub" / "cam.mkv")
    source, is_new, copied = import_video(project, video, [], probe=fake_probe)
    assert (source.path, is_new, copied) == ("footage/sub/cam.mkv", True, False)
    assert source.duration_ms == VIDEO_MS
    known = Source(
        id=source.id,
        path="FOOTAGE/sub/cam.mkv",
        duration_ms=1,
        fps_num=30,
        width=1,
        height=1,
    )
    again, is_new, _ = import_video(project, video, [known], probe=fake_probe)
    assert again is known and not is_new


def test_video_from_outside_is_copied_into_footage_once(
    tmp_path: Path, outside: Path
) -> None:
    project = tmp_path / "proj"
    (project / "footage").mkdir(parents=True)
    video = write_video(outside / "b roll.mp4")
    source, is_new, copied = import_video(project, video, [], probe=fake_probe)
    assert (source.path, is_new, copied) == ("footage/b roll.mp4", True, True)
    assert (project / "footage" / "b roll.mp4").read_bytes() == video.read_bytes()
    _, _, copied_again = import_video(project, video, [source], probe=fake_probe)
    assert not copied_again


def test_a_different_video_with_the_same_name_gets_a_new_name(
    tmp_path: Path, outside: Path
) -> None:
    project = tmp_path / "proj"
    (project / "footage").mkdir(parents=True)
    write_video(project / "footage" / "clip.mp4", b"one")
    video = write_video(outside / "clip.mp4", b"two!")
    source, _, copied = import_video(project, video, [], probe=fake_probe)
    assert copied and source.path == "footage/clip (2).mp4"


def test_a_video_that_cannot_be_probed_leaves_no_copy(
    tmp_path: Path, outside: Path
) -> None:
    project = tmp_path / "proj"
    (project / "footage").mkdir(parents=True)
    video = write_video(outside / "broken.mp4")
    with pytest.raises(LaneImportError):
        import_video(project, video, [], probe=lambda p: {"streams": []})
    assert list((project / "footage").iterdir()) == []


# ---- session and API -------------------------------------------------------------


@pytest.fixture
def session(tmp_path: Path) -> Session:
    session = Session(probe=fake_probe)
    session.new_project(str(tmp_path), "Rack")
    return session


def test_session_import_makes_a_lane_and_places_files_in_order(
    session: Session, outside: Path
) -> None:
    png = write_png(outside / "title.png")
    video = write_video(outside / "cut.mp4")
    result = session.import_lane_media([str(png), str(video)], None, 1000)
    assert result.errors == []
    assert [
        (i.name, i.kind, i.timeline_ms, i.lane_name, i.copied_to_footage)
        for i in result.imported
    ] == [
        ("title.png", "image", 1000, "Video 2", False),
        ("cut.mp4", "video", 6000, "Video 2", True),
    ]
    state = result.timeline
    assert [lane.name for lane in state.video_lanes] == ["Video 2"]
    assert [(c.name, c.timeline_ms, c.end_ms) for c in state.lane_clips] == [
        ("title.png", 1000, 6000),
        ("cut.mp4", 6000, 14_000),
    ]
    assert state.undo_label == "Import 2 files to video lanes"
    session.undo()
    after = session.timeline()
    assert after.video_lanes == [] and after.lane_clips == []
    assert session.footage().items == []  # the new source goes with the undo


def test_session_import_goes_up_or_to_a_new_lane(
    session: Session, outside: Path
) -> None:
    png = write_png(outside / "a.png")
    first = session.import_lane_media([str(png)], None, 0)
    lane = first.imported[0].lane_id
    second = session.import_lane_media(
        [str(png)], lane, 1000
    )  # overlaps: a new lane on top
    assert second.imported[0].lane_name == "Video 3"
    third = session.import_lane_media([str(png)], lane, 0, new_lane=True)
    assert third.imported[0].lane_name == "Video 4"
    assert len(third.timeline.video_lanes) == 3


def test_session_import_reports_bad_files(session: Session, outside: Path) -> None:
    png = write_png(outside / "ok.png")
    result = session.import_lane_media(
        [str(outside / "gone.png"), str(outside / "x.txt"), str(png)], None, 0
    )
    assert [i.name for i in result.imported] == ["ok.png"]
    assert len(result.errors) == 2


def test_api_import_and_image_route(session: Session, outside: Path) -> None:
    client = TestClient(create_app(static_dir=Path("does-not-exist"), session=session))
    png = write_png(outside / "t.png")
    response = client.post(
        "/api/lanes/import", json={"paths": [str(png)], "timeline_ms": 0}
    )
    assert response.status_code == 200, response.text
    image_id = response.json()["timeline"]["lane_clips"][0]["image_id"]
    media = client.get(f"/media/image/{image_id}")
    assert media.status_code == 200 and media.content[:4] == b"\x89PNG"
    assert client.get("/media/image/ffffffffffff").status_code == 404
