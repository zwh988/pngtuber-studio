"""Export bundle (M6-6): folder names, raw video links and their fallback, the PNG
sequence, snapshot, manifest and the incomplete rename."""

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from backend.export.bundle import (
    LINKS_NAME,
    MANIFEST_NAME,
    OVERLAY_DIR,
    OVERLAY_README,
    RAW_DIR,
    ensure_new_folder,
    export_folder_name,
    ffmpeg_version,
    file_list,
    link_raw_videos,
    mark_incomplete,
    png_name,
    raw_link_names,
    unique_folder,
    write_manifest,
    write_overlay_readme,
    write_snapshot,
)
from backend.export.errors import ExportError
from backend.project.schema import Project


def test_folder_names(tmp_path: Path) -> None:
    assert export_folder_name(datetime(2026, 11, 17, 9, 5)) == "2026-11-17 0905"
    assert unique_folder(tmp_path, "a") == tmp_path / "a"
    (tmp_path / "a").mkdir()
    (tmp_path / "a (2)").mkdir()
    assert unique_folder(tmp_path, "a") == tmp_path / "a (3)"


def test_mark_incomplete_renames_and_keeps_the_files(tmp_path: Path) -> None:
    folder = tmp_path / "2026-11-17 0905"
    folder.mkdir()
    (folder / "voice_raw.wav").write_bytes(b"x")
    moved = mark_incomplete(folder)
    assert moved == tmp_path / "2026-11-17 0905 (incomplete)"
    assert (moved / "voice_raw.wav").read_bytes() == b"x" and not folder.exists()
    assert mark_incomplete(tmp_path / "gone") == tmp_path / "gone"  # nothing to rename


def test_ensure_new_folder(tmp_path: Path) -> None:
    ensure_new_folder(tmp_path / "new" / "deep")
    assert (tmp_path / "new" / "deep").is_dir()
    ensure_new_folder(tmp_path / "new" / "deep")  # empty: fine
    (tmp_path / "new" / "deep" / "f").write_text("x")
    with pytest.raises(ExportError, match="not empty"):
        ensure_new_folder(tmp_path / "new" / "deep")


def test_raw_link_names_avoid_clashes() -> None:
    paths = [Path("C:/a/rec.mkv"), Path("C:/b/rec.mkv"), Path("C:/c/REC.mkv"), Path("C:/d/other.mkv")]
    # Windows names ignore case: "2_REC.mkv" would clash with "2_rec.mkv".
    assert raw_link_names(paths) == ["rec.mkv", "2_rec.mkv", "3_REC.mkv", "other.mkv"]


def test_hard_links_share_the_file(tmp_path: Path) -> None:
    footage = tmp_path / "footage dir"
    footage.mkdir()
    rec = footage / "rec 1.mkv"
    rec.write_bytes(b"video bytes")
    out = tmp_path / "out"
    links = link_raw_videos([rec, rec], out)
    assert links.linked == ["rec 1.mkv"] and links.listed == []
    linked = out / RAW_DIR / "rec 1.mkv"
    assert linked.read_bytes() == b"video bytes"
    assert os.stat(linked).st_nlink == 2  # the same file under a second name, not a copy
    assert not (out / RAW_DIR / LINKS_NAME).exists()
    assert rec.read_bytes() == b"video bytes"  # the footage is unchanged (rule 2)
    assert link_raw_videos([], out).linked == []


def test_links_that_fail_are_listed_not_copied(tmp_path: Path) -> None:
    rec = tmp_path / "rec.mkv"
    rec.write_bytes(b"v")

    def no_link(src: Path, dest: Path) -> None:
        raise OSError(18, "Not same device")

    links = link_raw_videos([rec], tmp_path / "out", link=no_link)
    assert links.linked == [] and links.listed == [str(rec)]
    text = (tmp_path / "out" / RAW_DIR / LINKS_NAME).read_text(encoding="utf-8")
    assert str(rec) in text and "Not same device" in text
    assert not (tmp_path / "out" / RAW_DIR / "rec.mkv").exists()


def test_overlay_readme(tmp_path: Path) -> None:
    dest = write_overlay_readme(tmp_path, 1801, 30, 1920, 1080)
    assert dest == tmp_path / OVERLAY_DIR / OVERLAY_README
    text = dest.read_text(encoding="utf-8")
    assert "1801 frames, 30 fps, 1920x1080" in text and "DaVinci Resolve" in text
    assert png_name(12) == "frame_000012.png"


def test_snapshot_and_manifest(tmp_path: Path) -> None:
    project = Project(name="Rack 1")
    snap = write_snapshot(project, tmp_path)
    assert Project.model_validate_json(snap.read_text(encoding="utf-8")) == project
    (tmp_path / "lines").mkdir()
    (tmp_path / "lines" / "a.wav").write_bytes(b"12")
    manifest = write_manifest(tmp_path, {"project": "Rack 1", "seconds": {"total": 1.5}})
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["project"] == "Rack 1" and data["seconds"]["total"] == 1.5
    assert {"name": "lines/", "files": 1} in data["files"]
    assert {"name": "project.json", "bytes": snap.stat().st_size} in data["files"]
    assert all(item["name"] != MANIFEST_NAME for item in file_list(tmp_path))


def test_ffmpeg_version_of_a_missing_binary(tmp_path: Path) -> None:
    assert ffmpeg_version(tmp_path / "nope.exe") == "unknown"


REAL_FFMPEG = Path(__file__).resolve().parents[1] / "bin" / "ffmpeg.exe"


@pytest.mark.skipif(not REAL_FFMPEG.is_file(), reason="bin/ffmpeg.exe is not installed")
def test_ffmpeg_version_of_the_real_binary() -> None:
    assert ffmpeg_version(REAL_FFMPEG).startswith("ffmpeg version")
