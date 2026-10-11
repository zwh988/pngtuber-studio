"""Tests for backend/project/commands.py (pure, no I/O)."""

import pytest

from backend.project.commands import (
    AddSource,
    CommandError,
    CommandStack,
    RelinkSource,
    RemoveSource,
    RenameProject,
)
from backend.project.schema import Clip, Project, Source

ID_A = "aaaaaaaaaaaa"
ID_B = "bbbbbbbbbbbb"
ID_C = "cccccccccccc"
CLIP_ID = "111111111111"


def make_source(source_id: str, path: str) -> Source:
    return Source(
        id=source_id,
        path=path,
        duration_ms=60_000,
        fps_num=60,
        width=2560,
        height=1440,
        audio_tracks=1,
    )


def src_a() -> Source:
    return make_source(ID_A, "footage/a.mkv")


def src_b() -> Source:
    return make_source(ID_B, "footage/b.mkv")


def src_c() -> Source:
    return make_source(ID_C, "footage/c.mkv")


@pytest.fixture
def project() -> Project:
    return Project(name="Rack")


@pytest.fixture
def stack(project: Project) -> CommandStack:
    return CommandStack(project)


def paths(project: Project) -> list[str]:
    return [s.path for s in project.sources]


# ---- AddSource -------------------------------------------------------------


def test_add_source_apply_and_undo_redo(project: Project, stack: CommandStack) -> None:
    stack.execute(AddSource(src_a()))
    assert paths(project) == ["footage/a.mkv"]
    assert stack.undo() == "Add footage footage/a.mkv"
    assert project.sources == []
    assert stack.redo() == "Add footage footage/a.mkv"
    assert paths(project) == ["footage/a.mkv"]


def test_add_source_duplicate_id_rejected(project: Project, stack: CommandStack) -> None:
    stack.execute(AddSource(src_a()))
    with pytest.raises(CommandError, match="already exists"):
        stack.execute(AddSource(make_source(ID_A, "footage/other.mkv")))
    assert paths(project) == ["footage/a.mkv"]
    assert stack.undo_label == "Add footage footage/a.mkv"  # failed one not recorded


def test_add_source_duplicate_path_rejected_case_insensitive(
    project: Project, stack: CommandStack
) -> None:
    stack.execute(AddSource(src_a()))
    with pytest.raises(CommandError, match="already in the project"):
        stack.execute(AddSource(make_source(ID_B, "footage/A.MKV")))
    assert len(project.sources) == 1


def test_add_source_does_not_alias_command_object(
    project: Project, stack: CommandStack
) -> None:
    source = src_a()
    stack.execute(AddSource(source))
    source.width = 1
    assert project.sources[0].width == 2560


# ---- RemoveSource ----------------------------------------------------------


def test_remove_source_undo_restores_original_position(
    project: Project, stack: CommandStack
) -> None:
    for s in (src_a(), src_b(), src_c()):
        stack.execute(AddSource(s))
    stack.execute(RemoveSource(ID_B))
    assert [s.id for s in project.sources] == [ID_A, ID_C]
    stack.undo()
    assert [s.id for s in project.sources] == [ID_A, ID_B, ID_C]
    stack.redo()
    assert [s.id for s in project.sources] == [ID_A, ID_C]


def test_remove_unknown_source_rejected(stack: CommandStack) -> None:
    with pytest.raises(CommandError, match="unknown source"):
        stack.execute(RemoveSource(ID_A))
    assert not stack.can_undo


def test_remove_source_used_by_clip_rejected(
    project: Project, stack: CommandStack
) -> None:
    stack.execute(AddSource(src_a()))
    project.clips.append(Clip(id=CLIP_ID, source_id=ID_A, in_ms=0, out_ms=1000))
    with pytest.raises(CommandError, match="still use it"):
        stack.execute(RemoveSource(ID_A))
    assert [s.id for s in project.sources] == [ID_A]
    assert stack.undo_label == "Add footage footage/a.mkv"


# ---- RenameProject ---------------------------------------------------------


def test_rename_project_undo_redo(project: Project, stack: CommandStack) -> None:
    stack.execute(RenameProject("  Game 7  "))
    assert project.name == "Game 7"
    stack.undo()
    assert project.name == "Rack"
    stack.redo()
    assert project.name == "Game 7"


@pytest.mark.parametrize("bad", ["", "   "])
def test_rename_project_rejects_empty(bad: str) -> None:
    with pytest.raises(CommandError, match="must not be empty"):
        RenameProject(bad)


# ---- RelinkSource ----------------------------------------------------------


def test_relink_source_undo_redo(project: Project, stack: CommandStack) -> None:
    stack.execute(AddSource(src_a()))
    stack.execute(RelinkSource(ID_A, "footage/moved/a.mkv"))
    assert paths(project) == ["footage/moved/a.mkv"]
    stack.undo()
    assert paths(project) == ["footage/a.mkv"]
    stack.redo()
    assert paths(project) == ["footage/moved/a.mkv"]


@pytest.mark.parametrize("bad", ["C:/x/a.mkv", "/abs/a.mkv", "footage\\a.mkv", "../a.mkv"])
def test_relink_rejects_invalid_path_and_leaves_state(
    project: Project, stack: CommandStack, bad: str
) -> None:
    stack.execute(AddSource(src_a()))
    with pytest.raises(CommandError, match="invalid path"):
        stack.execute(RelinkSource(ID_A, bad))
    assert paths(project) == ["footage/a.mkv"]
    assert stack.undo_label == "Add footage footage/a.mkv"


def test_relink_rejects_path_used_by_other_source(
    project: Project, stack: CommandStack
) -> None:
    stack.execute(AddSource(src_a()))
    stack.execute(AddSource(src_b()))
    with pytest.raises(CommandError, match="already in the project"):
        stack.execute(RelinkSource(ID_A, "footage/B.mkv"))
    assert paths(project) == ["footage/a.mkv", "footage/b.mkv"]


def test_relink_to_own_path_is_allowed(project: Project, stack: CommandStack) -> None:
    stack.execute(AddSource(src_a()))
    stack.execute(RelinkSource(ID_A, "footage/a.mkv"))
    assert paths(project) == ["footage/a.mkv"]


def test_relink_unknown_source_rejected(stack: CommandStack) -> None:
    with pytest.raises(CommandError, match="unknown source"):
        stack.execute(RelinkSource(ID_A, "footage/a.mkv"))


# ---- stack basics ----------------------------------------------------------


def test_undo_redo_on_empty_stack_return_none(stack: CommandStack) -> None:
    assert stack.undo() is None
    assert stack.redo() is None
    assert not stack.can_undo
    assert not stack.can_redo


def test_multiple_undo_redo_order(project: Project, stack: CommandStack) -> None:
    stack.execute(RenameProject("One"))
    stack.execute(RenameProject("Two"))
    stack.execute(RenameProject("Three"))
    stack.undo()
    stack.undo()
    assert project.name == "One"
    stack.redo()
    assert project.name == "Two"
    stack.redo()
    assert project.name == "Three"
    assert not stack.can_redo


def test_new_command_clears_redo(project: Project, stack: CommandStack) -> None:
    stack.execute(RenameProject("One"))
    stack.undo()
    assert stack.can_redo
    stack.execute(RenameProject("Two"))
    assert not stack.can_redo
    assert stack.redo() is None
    assert project.name == "Two"


def test_labels(stack: CommandStack) -> None:
    assert stack.undo_label is None
    stack.execute(RenameProject("One"))
    assert stack.undo_label == "Rename project"
    assert stack.redo_label is None
    stack.undo()
    assert stack.undo_label is None
    assert stack.redo_label == "Rename project"


# ---- groups ----------------------------------------------------------------


def test_group_undoes_as_one_step(project: Project, stack: CommandStack) -> None:
    with stack.group("Add three clips of footage"):
        stack.execute(AddSource(src_a()))
        stack.execute(AddSource(src_b()))
        stack.execute(AddSource(src_c()))
    assert len(project.sources) == 3
    assert stack.undo_label == "Add three clips of footage"
    assert stack.undo() == "Add three clips of footage"
    assert project.sources == []
    assert not stack.can_undo
    assert stack.redo() == "Add three clips of footage"
    assert [s.id for s in project.sources] == [ID_A, ID_B, ID_C]


def test_group_mixed_commands_redo_in_order(project: Project, stack: CommandStack) -> None:
    with stack.group("Setup"):
        stack.execute(AddSource(src_a()))
        stack.execute(RelinkSource(ID_A, "footage/z.mkv"))
        stack.execute(RenameProject("Setup done"))
    stack.undo()
    assert project.sources == []
    assert project.name == "Rack"
    stack.redo()
    assert paths(project) == ["footage/z.mkv"]
    assert project.name == "Setup done"


def test_empty_group_records_nothing(stack: CommandStack) -> None:
    with stack.group("Nothing"):
        pass
    assert not stack.can_undo


def test_nested_groups_merge_into_outer(project: Project, stack: CommandStack) -> None:
    with stack.group("Outer"):
        stack.execute(AddSource(src_a()))
        with stack.group("Inner"):
            stack.execute(AddSource(src_b()))
        stack.execute(AddSource(src_c()))
    assert stack.undo_label == "Outer"
    stack.undo()
    assert project.sources == []
    assert not stack.can_undo


def test_group_rolls_back_when_block_raises(project: Project, stack: CommandStack) -> None:
    stack.execute(RenameProject("B"))
    stack.undo()  # leaves one redo entry
    with pytest.raises(RuntimeError), stack.group("Will fail"):
        stack.execute(AddSource(src_a()))
        stack.execute(AddSource(src_b()))
        raise RuntimeError("boom")
    assert project.sources == []
    assert not stack.can_undo
    assert stack.can_redo  # redo restored by the rollback
    stack.redo()
    assert project.name == "B"


def test_group_rolls_back_when_command_fails(project: Project, stack: CommandStack) -> None:
    with pytest.raises(CommandError), stack.group("Add dup"):
        stack.execute(AddSource(src_a()))
        stack.execute(AddSource(src_a()))  # duplicate id
    assert project.sources == []
    assert not stack.can_undo


def test_group_clears_redo_when_committed(stack: CommandStack) -> None:
    stack.execute(RenameProject("B"))
    stack.undo()
    with stack.group("New work"):
        stack.execute(AddSource(src_a()))
    assert not stack.can_redo


def test_undo_redo_clear_rejected_inside_group(stack: CommandStack) -> None:
    stack.execute(RenameProject("B"))
    with stack.group("Open"):
        stack.execute(AddSource(src_a()))
        assert stack.in_group
        with pytest.raises(CommandError, match="group is open"):
            stack.undo()
        with pytest.raises(CommandError, match="group is open"):
            stack.redo()
        with pytest.raises(CommandError, match="group is open"):
            stack.clear()
    assert not stack.in_group


def test_clear_forgets_history(project: Project, stack: CommandStack) -> None:
    stack.execute(RenameProject("B"))
    stack.undo()
    stack.clear()
    assert not stack.can_undo
    assert not stack.can_redo
    assert project.name == "Rack"


# ---- on_change -------------------------------------------------------------


def test_on_change_fires_once_per_top_level_change(project: Project) -> None:
    calls: list[int] = []
    stack = CommandStack(project, on_change=lambda: calls.append(1))

    stack.execute(RenameProject("One"))
    assert len(calls) == 1

    with stack.group("Two adds"):
        stack.execute(AddSource(src_a()))
        stack.execute(AddSource(src_b()))
    assert len(calls) == 2

    stack.undo()
    assert len(calls) == 3
    stack.redo()
    assert len(calls) == 4


def test_on_change_not_fired_for_failures_empty_or_rolled_back(project: Project) -> None:
    calls: list[int] = []
    stack = CommandStack(project, on_change=lambda: calls.append(1))

    with pytest.raises(CommandError):
        stack.execute(RemoveSource(ID_A))
    with stack.group("Empty"):
        pass
    with pytest.raises(RuntimeError), stack.group("Boom"):
        stack.execute(AddSource(src_a()))
        raise RuntimeError("boom")
    assert stack.undo() is None
    assert calls == []
