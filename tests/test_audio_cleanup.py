"""Clean-up of takes_fx (M4-1, S3b)."""

import os
from pathlib import Path

from backend.audio.cleanup import MIN_AGE_S, FxEntry, plan_cleanup, run_cleanup

NOW = 1_000_000.0
OLD = NOW - MIN_AGE_S - 1
FRESH = NOW - 5

KEEP = "0123456789abcdef.wav"
DROP = "fedcba9876543210.wav"


def entry(name: str, mtime: float = OLD) -> FxEntry:
    return FxEntry(name, 10, mtime)


def test_unused_old_processed_files_go_and_wanted_ones_stay() -> None:
    doomed = plan_cleanup(
        [entry(KEEP), entry(DROP)], {KEEP}, {"t1"}, NOW
    )
    assert doomed == [DROP]


def test_a_recent_file_stays_even_when_unused() -> None:
    assert plan_cleanup([entry(DROP, FRESH)], set(), {"t1"}, NOW) == []


def test_the_age_limit_is_inclusive() -> None:
    exact = entry(DROP, NOW - MIN_AGE_S)
    assert plan_cleanup([exact], set(), set(), NOW) == [DROP]


def test_old_stretch_copies_and_temp_files_go_after_the_same_age() -> None:
    names = ["abc123def456_x1083.wav", f"{KEEP}.123.4.tmp"]
    assert plan_cleanup([entry(n) for n in names], set(), set(), NOW) == sorted(names)
    assert plan_cleanup([entry(n, FRESH) for n in names], set(), set(), NOW) == []


def test_sidecars_follow_their_raw_take_not_the_age() -> None:
    sidecars = [entry("t1.trim.json", FRESH), entry("t2.trim.json", FRESH)]
    assert plan_cleanup(sidecars, set(), {"t1"}, NOW) == ["t2.trim.json"]


def test_unknown_raw_takes_means_no_sidecar_is_deleted() -> None:
    assert plan_cleanup([entry("t2.trim.json")], set(), None, NOW) == []


def test_unknown_files_are_left_alone() -> None:
    names = ["notes.txt", "0123456789abcdef.mp3", "short.wav", "envelope.json"]
    assert plan_cleanup([entry(n) for n in names], set(), set(), NOW) == []


def touch(path: Path, mtime: float, size: int = 4) -> None:
    path.write_bytes(b"x" * size)
    os.utime(path, (mtime, mtime))


def test_run_cleanup_deletes_only_what_the_plan_picks(tmp_path: Path) -> None:
    raw = tmp_path / "media" / "takes_raw"
    fx = tmp_path / "media" / "takes_fx"
    raw.mkdir(parents=True)
    fx.mkdir(parents=True)
    touch(raw / "t1.wav", OLD, 100)
    touch(fx / KEEP, OLD)
    touch(fx / DROP, OLD, 8)
    touch(fx / "t1.trim.json", OLD)
    touch(fx / "gone.trim.json", FRESH, 6)
    touch(fx / "readme.txt", OLD)

    report = run_cleanup(fx, raw, {KEEP}, now=NOW)

    assert sorted(report.deleted) == sorted([DROP, "gone.trim.json"])
    assert report.freed_bytes == 14
    assert report.failed == ()
    assert sorted(p.name for p in fx.iterdir()) == sorted(
        [KEEP, "t1.trim.json", "readme.txt"]
    )
    assert (raw / "t1.wav").read_bytes() == b"x" * 100  # raw takes are never touched


def test_a_missing_folder_is_not_an_error(tmp_path: Path) -> None:
    report = run_cleanup(tmp_path / "nope", tmp_path / "also-nope", set(), now=NOW)
    assert report.deleted == () and report.freed_bytes == 0


def test_an_unreadable_raw_folder_keeps_every_sidecar(tmp_path: Path) -> None:
    fx = tmp_path / "takes_fx"
    fx.mkdir()
    touch(fx / "t9.trim.json", OLD)
    report = run_cleanup(fx, tmp_path / "missing-raw", set(), now=NOW)
    assert report.deleted == ()
    assert (fx / "t9.trim.json").exists()
