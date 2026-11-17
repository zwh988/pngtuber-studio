"""Clean-up of media/envelopes and media/avatar_preview (M7 S4)."""

import os
from pathlib import Path

from PIL import Image

from backend.audio.cleanup import (
    ENVELOPE_FILE,
    MIN_AGE_S,
    PREVIEW_FILE,
    FxEntry,
    envelope_keep_names,
    plan_cache_cleanup,
    run_cache_cleanup,
)
from backend.avatar.preview import preview_name
from backend.project.session import _preview_keep_names

NOW = 1_000_000.0
OLD = NOW - MIN_AGE_S
NEW = NOW - 5
ENV_A = "aaaaaaaaaaaaaaaa.env.json"
ENV_B = "bbbbbbbbbbbbbbbb.env.json"


def entry(name: str, mtime: float = OLD) -> FxEntry:
    return FxEntry(name, 10, mtime)


def test_unwanted_old_cache_files_go() -> None:
    entries = [entry(ENV_A), entry(ENV_B), entry("x.env.json.123.tmp"), entry("notes.txt")]
    assert plan_cache_cleanup(entries, {ENV_A}, ENVELOPE_FILE, NOW) == [
        ENV_B,
        "x.env.json.123.tmp",
    ]


def test_recent_files_stay() -> None:
    entries = [entry(ENV_B, NEW), entry("y.tmp", NEW)]
    assert plan_cache_cleanup(entries, set(), ENVELOPE_FILE, NOW) == []


def test_unknown_keep_set_deletes_only_temp_files() -> None:
    entries = [entry("0123456789abcdef.png"), entry("a.png.9.tmp")]
    assert plan_cache_cleanup(entries, None, PREVIEW_FILE, NOW) == ["a.png.9.tmp"]


def test_only_the_folder_pattern_is_touched() -> None:
    entries = [entry("0123456789abcdef.png"), entry("my-art.png"), entry(ENV_A)]
    assert plan_cache_cleanup(entries, set(), PREVIEW_FILE, NOW) == ["0123456789abcdef.png"]


def touch(path: Path, mtime: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"data")
    os.utime(path, (mtime, mtime))


def test_envelopes_follow_their_processed_take(tmp_path: Path) -> None:
    fx = tmp_path / "takes_fx"
    env = tmp_path / "envelopes"
    touch(fx / "aaaaaaaaaaaaaaaa.wav", NOW)
    touch(fx / "take_x1083.wav", NOW)  # not a processed take
    touch(env / ENV_A, OLD)
    touch(env / ENV_B, OLD)
    keep = envelope_keep_names(fx)
    assert keep == {ENV_A}
    report = run_cache_cleanup(env, keep, ENVELOPE_FILE, now=NOW)
    assert report.deleted == (ENV_B,)
    assert report.freed_bytes == 4
    assert (env / ENV_A).is_file()


def test_missing_folders_are_not_errors(tmp_path: Path) -> None:
    assert envelope_keep_names(tmp_path / "nope") == set()
    assert run_cache_cleanup(tmp_path / "nope", set(), ENVELOPE_FILE).deleted == ()


def sprite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 8)).save(path)


def test_preview_keep_names_cover_every_sprite_of_the_art(tmp_path: Path) -> None:
    art = tmp_path / "art"
    sprite(art / "01_neutral" / "01a_neutral_oiom.png")
    sprite(art / "01_neutral" / "01b_neutral_cicm.png")
    keep = _preview_keep_names(str(art.as_posix()), tmp_path)
    assert keep == {
        preview_name(art / "01_neutral" / "01a_neutral_oiom.png"),
        preview_name(art / "01_neutral" / "01b_neutral_cicm.png"),
    }


def test_no_art_folder_wants_no_previews_and_a_missing_one_is_unknown(tmp_path: Path) -> None:
    assert _preview_keep_names(None, tmp_path) == set()
    assert _preview_keep_names((tmp_path / "gone").as_posix(), tmp_path) is None
