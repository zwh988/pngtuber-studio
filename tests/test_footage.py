"""Tests for backend/project/footage.py. Fixtures are JSON text, not video."""

from pathlib import Path
from typing import Any

import pytest

from backend.project.footage import (
    FfprobeNotFoundError,
    ProbeError,
    list_footage_files,
    parse_probe,
    parse_rate,
    plan_scan,
    run_ffprobe,
    scan_footage,
)
from backend.project.schema import Source


def probe_json(
    *,
    width: int = 2560,
    height: int = 1440,
    avg: str = "60/1",
    r: str = "60/1",
    duration: str | None = "600.123000",
    audio: int = 1,
) -> dict[str, Any]:
    streams: list[dict[str, Any]] = [
        {
            "index": 0,
            "codec_name": "h264",
            "codec_type": "video",
            "width": width,
            "height": height,
            "r_frame_rate": r,
            "avg_frame_rate": avg,
            "disposition": {"attached_pic": 0},
        }
    ]
    for i in range(audio):
        streams.append(
            {
                "index": i + 1,
                "codec_name": "aac",
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": 2,
            }
        )
    fmt: dict[str, Any] = {"format_name": "matroska,webm"}
    if duration is not None:
        fmt["duration"] = duration
    return {"streams": streams, "format": fmt}


def make_source(source_id: str, path: str) -> Source:
    return Source(
        id=source_id,
        path=path,
        duration_ms=1000,
        fps_num=60,
        width=1920,
        height=1080,
    )


# ---- parse_rate ----------------------------------------------------------


def test_parse_rate_rationals() -> None:
    assert parse_rate("60/1") == (60, 1)
    assert parse_rate("60000/1001") == (60000, 1001)
    assert parse_rate("30") == (30, 1)


@pytest.mark.parametrize("bad", ["0/0", "25/0", "abc", "", "-5/1"])
def test_parse_rate_rejects_bad_values(bad: str) -> None:
    with pytest.raises(ProbeError):
        parse_rate(bad)


# ---- parse_probe ---------------------------------------------------------


def test_parse_obs_clip() -> None:
    src = parse_probe(probe_json(), "footage/rack 1.mkv")
    assert src.path == "footage/rack 1.mkv"
    assert (src.width, src.height) == (2560, 1440)
    assert (src.fps_num, src.fps_den) == (60, 1)
    assert src.fps == 60.0
    assert src.duration_ms == 600123
    assert src.audio_tracks == 1
    assert len(src.id) == 12


def test_parse_ntsc_rate() -> None:
    src = parse_probe(probe_json(avg="60000/1001", r="60000/1001"), "footage/a.mkv")
    assert (src.fps_num, src.fps_den) == (60000, 1001)
    assert src.fps == pytest.approx(59.94, abs=0.01)


def test_parse_no_audio() -> None:
    src = parse_probe(probe_json(audio=0), "footage/a.mkv")
    assert src.audio_tracks == 0


def test_parse_two_audio_tracks() -> None:
    src = parse_probe(probe_json(audio=2), "footage/a.mkv")
    assert src.audio_tracks == 2


def test_avg_rate_zero_falls_back_to_r_frame_rate() -> None:
    src = parse_probe(probe_json(avg="0/0", r="30/1"), "footage/a.mkv")
    assert (src.fps_num, src.fps_den) == (30, 1)


def test_duration_falls_back_to_stream() -> None:
    data = probe_json(duration=None)
    data["streams"][0]["duration"] = "12.5"
    assert parse_probe(data, "footage/a.mkv").duration_ms == 12500


def test_missing_duration_is_error() -> None:
    with pytest.raises(ProbeError, match="duration"):
        parse_probe(probe_json(duration=None), "footage/a.mkv")


def test_no_video_stream_is_error() -> None:
    data = probe_json()
    data["streams"] = [s for s in data["streams"] if s["codec_type"] == "audio"]
    with pytest.raises(ProbeError, match="no video stream"):
        parse_probe(data, "footage/a.mkv")


def test_attached_picture_is_not_video() -> None:
    data = probe_json()
    data["streams"][0]["disposition"]["attached_pic"] = 1
    with pytest.raises(ProbeError, match="no video stream"):
        parse_probe(data, "footage/a.mkv")


def test_missing_streams_key_is_error() -> None:
    with pytest.raises(ProbeError):
        parse_probe({"format": {}}, "footage/a.mkv")


def test_missing_width_is_error() -> None:
    data = probe_json()
    del data["streams"][0]["width"]
    with pytest.raises(ProbeError):
        parse_probe(data, "footage/a.mkv")


def test_explicit_source_id_is_used() -> None:
    src = parse_probe(probe_json(), "footage/a.mkv", source_id="abcdefabcdef")
    assert src.id == "abcdefabcdef"


# ---- plan_scan -----------------------------------------------------------


def test_plan_scan_splits_new_present_missing() -> None:
    known = [
        make_source("aaaaaaaaaaaa", "footage/a.mkv"),
        make_source("bbbbbbbbbbbb", "footage/gone.mkv"),
    ]
    plan = plan_scan(["footage/a.mkv", "footage/new.mkv"], known)
    assert plan.to_probe == ["footage/new.mkv"]
    assert [s.id for s in plan.present] == ["aaaaaaaaaaaa"]
    assert [s.id for s in plan.missing] == ["bbbbbbbbbbbb"]


def test_plan_scan_is_case_insensitive() -> None:
    known = [make_source("aaaaaaaaaaaa", "footage/Rack.mkv")]
    plan = plan_scan(["footage/rack.MKV"], known)
    assert plan.to_probe == []
    assert plan.missing == []


# ---- ffprobe wrapper -----------------------------------------------------


def test_run_ffprobe_missing_binary(tmp_path: Path) -> None:
    with pytest.raises(FfprobeNotFoundError, match="ffprobe not found"):
        run_ffprobe(tmp_path / "x.mkv", ffprobe=tmp_path / "nope" / "ffprobe.exe")


# ---- folder scan (fake probe, empty placeholder files) -------------------


def test_list_footage_files_filters_and_sorts(tmp_path: Path) -> None:
    project = tmp_path / "My Rack"
    (project / "footage" / "sub").mkdir(parents=True)
    (project / "footage" / "b.mp4").write_bytes(b"")
    (project / "footage" / "a.MKV").write_bytes(b"")
    (project / "footage" / "sub" / "c.mov").write_bytes(b"")
    (project / "footage" / "notes.txt").write_text("hi")
    assert list_footage_files(project) == [
        "footage/a.MKV",
        "footage/b.mp4",
        "footage/sub/c.mov",
    ]


def test_list_footage_files_no_folder(tmp_path: Path) -> None:
    assert list_footage_files(tmp_path) == []


def test_scan_footage_new_known_missing_and_errors(tmp_path: Path) -> None:
    project = tmp_path / "My Rack"
    (project / "footage").mkdir(parents=True)
    for name in ("a.mkv", "new clip.mkv", "bad.mkv"):
        (project / "footage" / name).write_bytes(b"")
    known = [
        make_source("aaaaaaaaaaaa", "footage/a.mkv"),
        make_source("bbbbbbbbbbbb", "footage/gone.mkv"),
    ]
    probed: list[str] = []

    def fake_probe(path: Path) -> dict[str, Any]:
        probed.append(path.name)
        if path.name == "bad.mkv":
            raise ProbeError("bad.mkv: ffprobe failed: invalid data")
        return probe_json()

    result = scan_footage(project, known, probe=fake_probe)

    assert sorted(probed) == ["bad.mkv", "new clip.mkv"]  # known file not re-probed
    assert [s.path for s in result.new_sources] == ["footage/new clip.mkv"]
    assert [s.id for s in result.present] == ["aaaaaaaaaaaa"]
    assert [s.id for s in result.missing] == ["bbbbbbbbbbbb"]
    assert [rel for rel, _ in result.errors] == ["footage/bad.mkv"]


def test_scan_footage_does_not_touch_files(tmp_path: Path) -> None:
    project = tmp_path / "P"
    (project / "footage").mkdir(parents=True)
    clip = project / "footage" / "a.mkv"
    clip.write_bytes(b"abc")
    before = (clip.stat().st_size, clip.stat().st_mtime_ns)
    scan_footage(project, probe=lambda _p: probe_json())
    assert (clip.stat().st_size, clip.stat().st_mtime_ns) == before
    assert sorted(p.name for p in (project / "footage").iterdir()) == ["a.mkv"]
