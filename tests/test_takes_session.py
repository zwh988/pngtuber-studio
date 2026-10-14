"""Takes through Session (M3-4): add, reuse, delete, storage. Real files and
saving; only ffprobe and the voice worker are absent."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.project.line_ops import AddLineOp
from backend.project.schema import Anchor, Placement
from backend.project.session import Session, SessionError
from backend.voice.presets import parse_presets
from backend.voice.takes import NewTake

PRESETS = parse_presets(
    {"presets": {"neutral": {"exaggeration": 0.5, "cfg_weight": 0.5, "expression": "neutral"}}}
)
L1 = "aaaaaaaaaaaa"
L2 = "bbbbbbbbbbbb"
T1 = "111111111111"
T2 = "222222222222"
T3 = "333333333333"
KEY_A = "a" * 64
KEY_B = "b" * 64
RATE = 24000


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def tone(samples: int = 2400) -> np.ndarray:
    return (0.5 * np.sin(2 * np.pi * 440 * np.arange(samples) / RATE)).astype(np.float32)


def new_take(
    line_id: str = L1, key: str = KEY_A, take_id: str | None = None, seed: int = 7
) -> NewTake:
    return NewTake(
        line_id=line_id,
        seed=seed,
        text="hello there",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id="666666666666",
        model_version="chatterbox-test",
        raw_key=key,
        take_id=take_id,
    )


def open_with_lines(tmp_path: Path, *line_ids: str) -> tuple[Session, Path]:
    session = Session(probe=fake_probe, presets=PRESETS)
    session.new_project(str(tmp_path), "Rack")
    session.edit_lines([AddLineOp(line_id=line_id, text=line_id) for line_id in line_ids])
    return session, tmp_path / "Rack"


def raw_dir(folder: Path) -> Path:
    return folder / "media" / "takes_raw"


def add_placement(session: Session, line_id: str, override: str | None = None) -> None:
    stack = session._stack
    assert stack is not None
    stack.project.placements.append(
        Placement(
            id="777777777777",
            line_id=line_id,
            anchor=Anchor(clip_id="888888888888", source_ms=0),
            take_override_id=override,
        )
    )


# ---- add_take --------------------------------------------------------------


def test_add_take_writes_the_file_records_it_and_makes_it_active(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    result = session.add_take(new_take(take_id=T1), tone(), RATE)
    assert result.reused is False
    assert result.take.id == T1
    assert result.take.duration_ms == 100
    assert result.take.active is True
    assert (raw_dir(folder) / f"{T1}.wav").is_file()
    item = session.lines().lines[0]
    assert (item.active_take_id, item.take_count, item.generated) == (T1, 1, True)


def test_add_take_is_saved_to_project_json(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    reopened = Session(probe=fake_probe, presets=PRESETS)
    reopened.open_project(str(folder))
    takes = reopened.takes(L1)
    assert [take.id for take in takes] == [T1]
    assert takes[0].file_exists
    assert takes[0].text == "hello there"


def test_add_take_without_activation(tmp_path: Path) -> None:
    session, _ = open_with_lines(tmp_path, L1)
    result = session.add_take(new_take(take_id=T1), tone(), RATE, make_active=False)
    assert result.take.active is False
    assert session.lines().lines[0].active_take_id is None


def test_a_reroll_adds_a_second_take_and_activates_it(tmp_path: Path) -> None:
    session, _ = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1, seed=1), tone(), RATE)
    session.add_take(new_take(key=KEY_B, take_id=T2, seed=2), tone(4800), RATE)
    takes = session.takes(L1)
    assert [take.id for take in takes] == [T1, T2]
    assert [take.active for take in takes] == [False, True]


def test_add_take_picks_an_id_when_none_is_given(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    result = session.add_take(new_take(), tone(), RATE)
    assert len(result.take.id) == 12
    assert (raw_dir(folder) / f"{result.take.id}.wav").is_file()


def test_add_take_with_an_existing_id_is_refused(tmp_path: Path) -> None:
    session, _ = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    with pytest.raises(SessionError, match="already exists"):
        session.add_take(new_take(key=KEY_B, take_id=T1), tone(), RATE)


def test_add_take_unknown_line_and_bad_input_write_nothing(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    with pytest.raises(SessionError, match="unknown line"):
        session.add_take(new_take(line_id=L2), tone(), RATE)
    with pytest.raises(SessionError, match="raw_key"):
        session.add_take(new_take(key="nope"), tone(), RATE)
    with pytest.raises(SessionError, match="non-empty"):
        session.add_take(new_take(), np.zeros(0, dtype=np.float32), RATE)
    assert session.takes(L1) == []
    assert not list(raw_dir(folder).glob("*"))


# ---- reuse (rule 3) ----------------------------------------------------------


def test_reuse_take_returns_none_when_nothing_matches(tmp_path: Path) -> None:
    session, _ = open_with_lines(tmp_path, L1)
    assert session.reuse_take(new_take()) is None


def test_reuse_take_returns_the_existing_take_without_a_new_one(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    session.add_take(new_take(key=KEY_B, take_id=T2), tone(), RATE)  # T2 is active
    result = session.reuse_take(new_take())
    assert result is not None
    assert result.reused is True
    assert result.take.id == T1
    assert result.take.active is True  # re-activated
    assert len(session.takes(L1)) == 2
    assert len(list(raw_dir(folder).glob("*.wav"))) == 2


def test_reuse_without_activation_leaves_the_active_take(tmp_path: Path) -> None:
    session, _ = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    session.add_take(new_take(key=KEY_B, take_id=T2), tone(), RATE)
    result = session.reuse_take(new_take(), make_active=False)
    assert result is not None
    assert result.take.active is False
    assert session.lines().lines[0].active_take_id == T2


def test_adding_the_same_key_twice_reuses_the_first_take(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    first = session.add_take(new_take(take_id=T1), tone(), RATE)
    second = session.add_take(new_take(take_id=T2), tone(4800), RATE)
    assert second.reused is True
    assert second.take.id == first.take.id
    assert len(session.takes(L1)) == 1
    assert len(list(raw_dir(folder).glob("*.wav"))) == 1


def test_a_take_of_another_line_with_the_same_key_is_copied_not_regenerated(
    tmp_path: Path,
) -> None:
    session, folder = open_with_lines(tmp_path, L1, L2)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    result = session.reuse_take(new_take(line_id=L2, take_id=T2))
    assert result is not None
    assert result.reused is True
    assert result.take.id == T2
    assert result.take.line_id == L2
    copy = (raw_dir(folder) / f"{T2}.wav").read_bytes()
    assert copy == (raw_dir(folder) / f"{T1}.wav").read_bytes()
    assert [take.id for take in session.takes(L2)] == [T2]
    assert session.lines().lines[1].active_take_id == T2


def test_a_missing_file_is_written_back_for_the_same_key(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    (raw_dir(folder) / f"{T1}.wav").unlink()
    assert session.reuse_take(new_take()) is None  # nothing usable on disk
    result = session.add_take(new_take(), tone(4800), RATE)
    assert result.reused is False
    assert result.take.id == T1  # same record, file rewritten
    assert result.take.duration_ms == 200
    assert (raw_dir(folder) / f"{T1}.wav").is_file()
    assert len(session.takes(L1)) == 1


# ---- delete ----------------------------------------------------------------


def test_delete_take_removes_record_and_file(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    session.add_take(new_take(key=KEY_B, take_id=T2), tone(), RATE)
    size = (raw_dir(folder) / f"{T2}.wav").stat().st_size
    report = session.delete_take(T2)
    assert report.removed_take_count == 1
    assert report.removed_line is False
    assert report.freed_bytes == size
    assert report.failed_files == []
    assert report.cleared_active_line_ids == [L1]  # T2 was the active take
    assert not (raw_dir(folder) / f"{T2}.wav").exists()
    assert [take.id for take in session.takes(L1)] == [T1]
    assert session.lines().lines[0].active_take_id is None


def test_delete_take_is_saved(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    session.delete_take(T1)
    reopened = Session(probe=fake_probe, presets=PRESETS)
    reopened.open_project(str(folder))
    assert reopened.takes(L1) == []


def test_delete_take_clears_a_placement_override(tmp_path: Path) -> None:
    session, _ = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    session.add_take(new_take(key=KEY_B, take_id=T2), tone(), RATE)
    add_placement(session, L1, override=T1)
    report = session.delete_take(T1)
    assert report.cleared_override_placement_ids == ["777777777777"]
    assert session._stack is not None
    assert session._stack.project.placements[0].take_override_id is None


def test_delete_take_resets_undo_history(tmp_path: Path) -> None:
    session, _ = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    assert session.timeline().can_undo  # the add_line step
    session.delete_take(T1)
    assert not session.timeline().can_undo


def test_delete_unknown_take(tmp_path: Path) -> None:
    session, _ = open_with_lines(tmp_path, L1)
    with pytest.raises(SessionError, match="unknown take id"):
        session.delete_take(T1)


def test_a_file_that_cannot_be_deleted_is_reported_but_the_take_is_gone(
    tmp_path: Path,
) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    wav = raw_dir(folder) / f"{T1}.wav"
    wav.unlink()
    wav.mkdir()  # cannot be unlinked as a file
    report = session.delete_take(T1)
    assert report.failed_files == [f"media/takes_raw/{T1}.wav"]
    assert report.freed_bytes == 0
    assert session.takes(L1) == []


def test_delete_line_removes_the_line_and_its_takes(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1, L2)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    session.add_take(new_take(key=KEY_B, take_id=T2), tone(), RATE)
    session.add_take(new_take(line_id=L2, key="c" * 64, take_id=T3), tone(), RATE)
    report = session.delete_line(L1)
    assert report.removed_line is True
    assert report.removed_take_count == 2
    assert report.cleared_active_line_ids == []
    assert [item.id for item in session.lines().lines] == [L2]
    assert [path.name for path in raw_dir(folder).glob("*.wav")] == [f"{T3}.wav"]


def test_delete_line_refused_while_placed(tmp_path: Path) -> None:
    session, _ = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    add_placement(session, L1)
    with pytest.raises(SessionError, match="1 placement"):
        session.delete_line(L1)
    assert len(session.takes(L1)) == 1


# ---- storage report --------------------------------------------------------


def test_storage_report(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1, L2)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    session.add_take(new_take(key=KEY_B, take_id=T2), tone(4800), RATE)
    (raw_dir(folder) / "stray.wav").write_bytes(b"12345")
    report = session.storage()
    assert report.take_count == 2
    assert [line.line_id for line in report.lines] == [L1]  # L2 has no takes
    sizes = {take.take_id: take.size_bytes for take in report.lines[0].takes}
    assert sizes[T1] == (raw_dir(folder) / f"{T1}.wav").stat().st_size
    assert sizes[T2] > sizes[T1]
    assert report.total_bytes == sum(sizes.values())
    assert report.missing_file_count == 0
    assert [file.path for file in report.unreferenced] == ["media/takes_raw/stray.wav"]
    assert report.unreferenced_bytes == 5


def test_storage_report_flags_a_missing_file(tmp_path: Path) -> None:
    session, folder = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    (raw_dir(folder) / f"{T1}.wav").unlink()
    report = session.storage()
    assert report.missing_file_count == 1
    assert report.lines[0].takes[0].file_exists is False


def test_takes_need_an_open_project() -> None:
    session = Session(probe=fake_probe, presets=PRESETS)
    with pytest.raises(SessionError, match="no project is open"):
        session.storage()


# ---- undo and takes --------------------------------------------------------


def test_undoing_add_line_is_refused_once_the_line_has_a_take(tmp_path: Path) -> None:
    session, _ = open_with_lines(tmp_path, L1)
    session.add_take(new_take(take_id=T1), tone(), RATE)
    with pytest.raises(SessionError, match="1 take"):
        session.undo()
    assert [item.id for item in session.lines().lines] == [L1]
    assert session.lines().undo_label == "Add line"  # the step is still there
