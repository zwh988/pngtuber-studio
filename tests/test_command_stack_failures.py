"""A failing revert or redo leaves the step where it was (M3-4 hardening)."""

import pytest

from backend.project.commands import Command, CommandError, CommandStack, RenameProject
from backend.project.schema import Project


class FailingRevert(Command):
    @property
    def label(self) -> str:
        return "failing revert"

    def apply(self, project: Project) -> None:
        return None

    def revert(self, project: Project) -> None:
        raise CommandError("cannot revert")


class FailsOnSecondApply(Command):
    def __init__(self) -> None:
        self.applied = 0

    @property
    def label(self) -> str:
        return "fails on redo"

    def apply(self, project: Project) -> None:
        self.applied += 1
        if self.applied > 1:
            raise CommandError("cannot apply again")

    def revert(self, project: Project) -> None:
        return None


def make_stack() -> tuple[CommandStack, list[int]]:
    calls: list[int] = []
    stack = CommandStack(Project(name="Old"), on_change=lambda: calls.append(1))
    return stack, calls


def test_failed_undo_keeps_the_step() -> None:
    stack, calls = make_stack()
    stack.execute(FailingRevert())
    with pytest.raises(CommandError, match="cannot revert"):
        stack.undo()
    assert stack.can_undo
    assert not stack.can_redo
    assert stack.undo_label == "failing revert"
    assert len(calls) == 1  # only the execute notified


def test_failed_undo_in_a_group_restores_what_was_already_reverted() -> None:
    stack, _ = make_stack()
    with stack.group("both"):
        stack.execute(FailingRevert())
        stack.execute(RenameProject("New"))
    with pytest.raises(CommandError):
        stack.undo()  # reverts the rename first, then fails: rename comes back
    assert stack.project.name == "New"
    assert stack.can_undo
    assert not stack.can_redo


def test_failed_redo_keeps_the_step() -> None:
    stack, _ = make_stack()
    stack.execute(FailsOnSecondApply())
    stack.undo()
    with pytest.raises(CommandError, match="cannot apply again"):
        stack.redo()
    assert stack.can_redo
    assert not stack.can_undo


def test_failed_redo_in_a_group_reverts_what_was_already_applied() -> None:
    stack, _ = make_stack()
    with stack.group("both"):
        stack.execute(RenameProject("New"))
        stack.execute(FailsOnSecondApply())
    stack.undo()
    assert stack.project.name == "Old"
    with pytest.raises(CommandError):
        stack.redo()
    assert stack.project.name == "Old"
    assert stack.can_redo


def test_normal_undo_and_redo_still_work() -> None:
    stack, calls = make_stack()
    stack.execute(RenameProject("New"))
    assert stack.undo() == "Rename project"
    assert stack.project.name == "Old"
    assert stack.redo() == "Rename project"
    assert stack.project.name == "New"
    assert len(calls) == 3
