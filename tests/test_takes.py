"""Pure take logic (M3-4): lookup, building, removal, storage report."""

import pytest

from backend.project.schema import Anchor, Line, Placement, Project, Take
from backend.voice.takes import (
    NewTake,
    TakeError,
    build_delete_report,
    build_storage_report,
    build_take,
    build_take_item,
    find_take_by_key,
    raw_take_relpath,
    remove_line_and_takes,
    remove_takes,
)

L1 = "aaaaaaaaaaaa"
L2 = "bbbbbbbbbbbb"
T1 = "111111111111"
T2 = "222222222222"
T3 = "333333333333"
P1 = "444444444444"
CLIP = "555555555555"
KEY_A = "a" * 64
KEY_B = "b" * 64


def make_take(
    take_id: str, line_id: str, key: str = KEY_A, raw_file: str | None = None
) -> Take:
    return Take(
        id=take_id,
        line_id=line_id,
        seed=1,
        text="hello",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id="666666666666",
        model_version="m",
        raw_key=key,
        raw_file=raw_file or raw_take_relpath(take_id),
        duration_ms=1000,
    )


def make_new(**changes: object) -> NewTake:
    values: dict[str, object] = {
        "line_id": L1,
        "seed": 5,
        "text": "  hello   there \n",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "voice_profile_id": "666666666666",
        "model_version": "chatterbox-test",
        "raw_key": KEY_A,
    }
    values.update(changes)
    return NewTake(**values)  # type: ignore[arg-type]


def make_project() -> Project:
    return Project(
        name="Rack",
        lines=[Line(id=L1, active_take_id=T1), Line(id=L2)],
        takes=[make_take(T1, L1, KEY_A), make_take(T2, L1, KEY_B), make_take(T3, L2, KEY_A)],
        placements=[
            Placement(
                id=P1,
                line_id=L1,
                anchor=Anchor(clip_id=CLIP, source_ms=0),
                take_override_id=T2,
            )
        ],
    )


def test_raw_take_relpath() -> None:
    assert raw_take_relpath(T1) == f"media/takes_raw/{T1}.wav"


# ---- lookup ----------------------------------------------------------------


def test_find_take_by_key_none_and_first() -> None:
    project = make_project()
    assert find_take_by_key(project, "c" * 64) is None
    found = find_take_by_key(project, KEY_A)
    assert found is not None
    assert found.id == T1


def test_find_take_by_key_prefers_the_given_line() -> None:
    project = make_project()
    found = find_take_by_key(project, KEY_A, prefer_line_id=L2)
    assert found is not None
    assert found.id == T3
    other = find_take_by_key(project, KEY_B, prefer_line_id=L2)
    assert other is not None
    assert other.id == T2  # falls back to any line


# ---- build_take ------------------------------------------------------------


def test_build_take_normalizes_text_and_copies_fields() -> None:
    take = build_take(make_new(), T1, raw_take_relpath(T1), 1234)
    assert take.text == "hello there"
    assert (take.id, take.line_id, take.seed) == (T1, L1, 5)
    assert take.raw_key == KEY_A
    assert take.duration_ms == 1234
    assert take.starred is False


def test_build_take_rejects_empty_text() -> None:
    with pytest.raises(TakeError, match="text must not be empty"):
        build_take(make_new(text="  \n "), T1, raw_take_relpath(T1), 0)


@pytest.mark.parametrize("key", ["", "abc", "G" * 64, "A" * 64, "a" * 63])
def test_build_take_rejects_bad_keys(key: str) -> None:
    with pytest.raises(TakeError, match="raw_key"):
        build_take(make_new(raw_key=key), T1, raw_take_relpath(T1), 0)


def test_build_take_rejects_invalid_values() -> None:
    with pytest.raises(TakeError, match="invalid take"):
        build_take(make_new(exaggeration=3.0), T1, raw_take_relpath(T1), 0)
    with pytest.raises(TakeError, match="invalid take"):
        build_take(make_new(voice_profile_id="nope"), T1, raw_take_relpath(T1), 0)


# ---- remove_takes ----------------------------------------------------------


def test_remove_takes_unknown_id_changes_nothing() -> None:
    project = make_project()
    with pytest.raises(TakeError, match="unknown take id"):
        remove_takes(project, [T1, "999999999999"])
    assert len(project.takes) == 3
    assert project.lines[0].active_take_id == T1


def test_remove_takes_clears_active_and_override_and_lists_files() -> None:
    project = make_project()
    removal = remove_takes(project, [T1, T2])
    assert removal.take_ids == (T1, T2)
    assert removal.files == (raw_take_relpath(T1), raw_take_relpath(T2))
    assert removal.cleared_active_line_ids == (L1,)
    assert removal.cleared_override_placement_ids == (P1,)
    assert [take.id for take in project.takes] == [T3]
    assert project.lines[0].active_take_id is None
    assert project.placements[0].take_override_id is None


def test_remove_takes_leaves_unrelated_references_alone() -> None:
    project = make_project()
    removal = remove_takes(project, [T3])
    assert removal.cleared_active_line_ids == ()
    assert removal.cleared_override_placement_ids == ()
    assert project.lines[0].active_take_id == T1
    assert project.placements[0].take_override_id == T2


def test_remove_takes_keeps_a_file_another_take_still_uses() -> None:
    project = make_project()
    shared = raw_take_relpath(T1)
    project.takes[2].raw_file = shared
    removal = remove_takes(project, [T1])
    assert removal.files == ()


def test_remove_no_takes_is_a_no_op() -> None:
    project = make_project()
    removal = remove_takes(project, [])
    assert removal.take_ids == ()
    assert len(project.takes) == 3


# ---- remove_line_and_takes -------------------------------------------------


def test_remove_line_and_takes_refused_while_placed() -> None:
    project = make_project()
    with pytest.raises(TakeError, match="1 placement"):
        remove_line_and_takes(project, L1)
    assert len(project.lines) == 2
    assert len(project.takes) == 3


def test_remove_line_and_takes() -> None:
    project = make_project()
    removal = remove_line_and_takes(project, L2)
    assert removal.take_ids == (T3,)
    assert [line.id for line in project.lines] == [L1]
    assert [take.id for take in project.takes] == [T1, T2]


def test_remove_line_and_takes_does_not_report_the_removed_line_as_cleared() -> None:
    project = make_project()
    project.placements.clear()
    removal = remove_line_and_takes(project, L1)
    assert removal.cleared_active_line_ids == ()
    assert [line.id for line in project.lines] == [L2]


def test_remove_line_without_takes_and_unknown_line() -> None:
    project = Project(name="Rack", lines=[Line(id=L1)])
    removal = remove_line_and_takes(project, L1)
    assert removal.take_ids == ()
    assert project.lines == []
    with pytest.raises(TakeError, match="unknown line id"):
        remove_line_and_takes(project, L1)


def test_build_delete_report() -> None:
    project = make_project()
    removal = remove_takes(project, [T1])
    report = build_delete_report(
        removal, removed_line=False, freed_bytes=10, failed_files=["x"]
    )
    assert report.removed_take_count == 1
    assert report.freed_bytes == 10
    assert report.failed_files == ["x"]
    assert report.cleared_active_line_ids == [L1]


# ---- items and storage report ----------------------------------------------


def test_build_take_item_marks_the_active_take() -> None:
    project = make_project()
    active = build_take_item(project.takes[0], project.lines[0], True)
    other = build_take_item(project.takes[1], project.lines[0], False)
    assert active.active is True
    assert other.active is False
    assert other.file_exists is False


def test_storage_report_sizes_missing_and_unreferenced() -> None:
    project = make_project()
    sizes = {
        raw_take_relpath(T1): 100,
        raw_take_relpath(T2): None,
        raw_take_relpath(T3): 50,
    }
    report = build_storage_report(project, sizes, {"media/takes_raw/stray.wav": 7})
    assert report.take_count == 3
    assert report.total_bytes == 150
    assert report.missing_file_count == 1
    assert [line.line_id for line in report.lines] == [L1, L2]
    first = report.lines[0]
    assert (first.take_count, first.size_bytes) == (2, 100)
    assert [take.active for take in first.takes] == [True, False]
    assert first.takes[1].file_exists is False
    assert report.unreferenced[0].path == "media/takes_raw/stray.wav"
    assert report.unreferenced_bytes == 7


def test_storage_report_leaves_out_lines_without_takes() -> None:
    project = Project(name="Rack", lines=[Line(id=L1)])
    report = build_storage_report(project, {}, {})
    assert report.lines == []
    assert report.total_bytes == 0


def test_storage_report_counts_takes_of_a_missing_line() -> None:
    project = Project(name="Rack", takes=[make_take(T1, L1)])
    report = build_storage_report(project, {raw_take_relpath(T1): 9}, {})
    assert report.lines[0].text == "(line missing)"
    assert report.total_bytes == 9
