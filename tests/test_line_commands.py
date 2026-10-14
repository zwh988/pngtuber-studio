"""Line bank commands (M3-4)."""

import pytest

from backend.project.commands import CommandError, CommandStack
from backend.project.line_commands import (
    AddLine,
    NoChange,
    RemoveLine,
    SetActiveTake,
    SetAllowOverlap,
    SetLineCfgWeight,
    SetLineEmotion,
    SetLineExaggeration,
    SetLineText,
    StarTake,
)
from backend.project.schema import Anchor, Line, Placement, Project, Take

L1 = "aaaaaaaaaaaa"
L2 = "bbbbbbbbbbbb"
T1 = "cccccccccccc"
T2 = "dddddddddddd"
CLIP = "eeeeeeeeeeee"
EMOTIONS = ("neutral", "excited")


def make_take(take_id: str, line_id: str) -> Take:
    return Take(
        id=take_id,
        line_id=line_id,
        seed=1,
        text="hello",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id="111111111111",
        model_version="chatterbox-test",
        raw_key="0" * 64,
        raw_file=f"media/takes_raw/{take_id}.wav",
        duration_ms=1000,
    )


def make_stack() -> CommandStack:
    project = Project(
        name="Rack",
        lines=[Line(id=L1, text="one"), Line(id=L2, text="two")],
        takes=[make_take(T1, L1), make_take(T2, L2)],
    )
    return CommandStack(project)


def line(stack: CommandStack, line_id: str = L1) -> Line:
    return next(item for item in stack.project.lines if item.id == line_id)


# ---- AddLine ---------------------------------------------------------------


def test_add_line_appends_and_undoes() -> None:
    stack = make_stack()
    command = AddLine("hello", "excited", line_id="ffffffffffff", known_emotions=EMOTIONS)
    stack.execute(command)
    assert [x.id for x in stack.project.lines] == [L1, L2, "ffffffffffff"]
    added = stack.project.lines[-1]
    assert (added.text, added.emotion) == ("hello", "excited")
    assert command.line_id == "ffffffffffff"
    stack.undo()
    assert [x.id for x in stack.project.lines] == [L1, L2]
    stack.redo()
    assert stack.project.lines[-1].id == "ffffffffffff"


def test_add_line_at_a_position() -> None:
    stack = make_stack()
    stack.execute(AddLine("new", position=1, line_id="ffffffffffff"))
    assert [x.id for x in stack.project.lines] == [L1, "ffffffffffff", L2]


@pytest.mark.parametrize("position", [-1, 3])
def test_add_line_position_out_of_range_changes_nothing(position: int) -> None:
    stack = make_stack()
    with pytest.raises(CommandError, match="out of range"):
        stack.execute(AddLine("new", position=position))
    assert len(stack.project.lines) == 2
    assert not stack.can_undo


def test_add_line_generates_an_id() -> None:
    assert len(AddLine("x").line_id) == 12


def test_add_line_refuses_a_duplicate_id() -> None:
    stack = make_stack()
    with pytest.raises(CommandError, match="already exists"):
        stack.execute(AddLine("x", line_id=L1))


def test_add_line_rejects_unknown_or_empty_emotion() -> None:
    with pytest.raises(CommandError, match="unknown emotion"):
        AddLine("x", "furious", known_emotions=EMOTIONS)
    with pytest.raises(CommandError, match="must not be empty"):
        AddLine("x", "  ")


def test_add_line_rejects_a_bad_id() -> None:
    with pytest.raises(CommandError, match="invalid line"):
        AddLine("x", line_id="not-hex")


def test_add_line_without_known_emotions_accepts_any_emotion() -> None:
    assert AddLine("x", "anything").line.emotion == "anything"


# ---- RemoveLine ------------------------------------------------------------


def test_remove_line_undo_restores_the_position() -> None:
    stack = CommandStack(Project(name="Rack", lines=[Line(id=L1), Line(id=L2)]))
    stack.execute(RemoveLine(L1))
    assert [x.id for x in stack.project.lines] == [L2]
    stack.undo()
    assert [x.id for x in stack.project.lines] == [L1, L2]
    stack.redo()
    assert [x.id for x in stack.project.lines] == [L2]


def test_remove_line_refused_while_it_has_takes() -> None:
    stack = make_stack()
    with pytest.raises(CommandError, match="1 take"):
        stack.execute(RemoveLine(L1))
    assert len(stack.project.lines) == 2


def test_remove_line_refused_while_it_has_placements() -> None:
    project = Project(
        name="Rack",
        lines=[Line(id=L1)],
        placements=[
            Placement(id=T1, line_id=L1, anchor=Anchor(clip_id=CLIP, source_ms=0))
        ],
    )
    with pytest.raises(CommandError, match="1 placement"):
        CommandStack(project).execute(RemoveLine(L1))


def test_remove_unknown_line() -> None:
    with pytest.raises(CommandError, match="unknown line"):
        make_stack().execute(RemoveLine("999999999999"))


# ---- single-field edits ----------------------------------------------------


def test_set_text_apply_undo_redo() -> None:
    stack = make_stack()
    stack.execute(SetLineText(L1, "changed"))
    assert line(stack).text == "changed"
    assert stack.undo_label == "Edit line text"
    stack.undo()
    assert line(stack).text == "one"
    stack.redo()
    assert line(stack).text == "changed"


def test_text_may_be_cleared_to_empty() -> None:
    stack = make_stack()
    stack.execute(SetLineText(L1, ""))
    assert line(stack).text == ""


def test_same_value_raises_no_change_and_records_nothing() -> None:
    stack = make_stack()
    with pytest.raises(NoChange):
        stack.execute(SetLineText(L1, "one"))
    assert not stack.can_undo


def test_no_change_is_a_command_error() -> None:
    assert issubclass(NoChange, CommandError)


def test_set_emotion_checks_known_emotions() -> None:
    stack = make_stack()
    stack.execute(SetLineEmotion(L1, " excited ", known_emotions=EMOTIONS))
    assert line(stack).emotion == "excited"
    with pytest.raises(CommandError, match="unknown emotion"):
        SetLineEmotion(L1, "furious", known_emotions=EMOTIONS)
    stack.undo()
    assert line(stack).emotion == "neutral"


def test_set_exaggeration_and_back_to_preset() -> None:
    stack = make_stack()
    stack.execute(SetLineExaggeration(L1, 1.2))
    assert line(stack).exaggeration == 1.2
    stack.execute(SetLineExaggeration(L1, None))
    assert line(stack).exaggeration is None
    stack.undo()
    assert line(stack).exaggeration == 1.2
    stack.undo()
    assert line(stack).exaggeration is None


@pytest.mark.parametrize("value", [-0.1, 2.1, float("nan")])
def test_exaggeration_out_of_range_changes_nothing(value: float) -> None:
    stack = make_stack()
    with pytest.raises(CommandError, match="invalid exaggeration"):
        stack.execute(SetLineExaggeration(L1, value))
    assert line(stack).exaggeration is None
    assert not stack.can_undo


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_cfg_weight_out_of_range(value: float) -> None:
    stack = make_stack()
    with pytest.raises(CommandError, match="invalid cfg_weight"):
        stack.execute(SetLineCfgWeight(L1, value))


def test_set_cfg_weight() -> None:
    stack = make_stack()
    stack.execute(SetLineCfgWeight(L1, 0.3))
    assert line(stack).cfg_weight == 0.3


def test_allow_overlap_toggle() -> None:
    stack = make_stack()
    stack.execute(SetAllowOverlap(L1, True))
    assert line(stack).allow_overlap is True
    with pytest.raises(NoChange):
        stack.execute(SetAllowOverlap(L1, True))
    stack.undo()
    assert line(stack).allow_overlap is False


def test_edit_unknown_line() -> None:
    with pytest.raises(CommandError, match="unknown line"):
        make_stack().execute(SetLineText("999999999999", "x"))


# ---- takes -----------------------------------------------------------------


def test_set_active_take_apply_undo_redo() -> None:
    stack = make_stack()
    stack.execute(SetActiveTake(L1, T1))
    assert line(stack).active_take_id == T1
    stack.undo()
    assert line(stack).active_take_id is None
    stack.redo()
    assert line(stack).active_take_id == T1


def test_set_active_take_can_clear_and_switch() -> None:
    stack = make_stack()
    stack.project.takes.append(make_take("999999999999", L1))
    stack.execute(SetActiveTake(L1, T1))
    stack.execute(SetActiveTake(L1, "999999999999"))
    stack.execute(SetActiveTake(L1, None))
    assert line(stack).active_take_id is None
    stack.undo()
    assert line(stack).active_take_id == "999999999999"
    stack.undo()
    assert line(stack).active_take_id == T1


def test_set_active_take_refuses_another_lines_take() -> None:
    stack = make_stack()
    with pytest.raises(CommandError, match="another line"):
        stack.execute(SetActiveTake(L1, T2))
    assert line(stack).active_take_id is None


def test_set_active_take_unknown_take() -> None:
    with pytest.raises(CommandError, match="unknown take"):
        make_stack().execute(SetActiveTake(L1, "999999999999"))


def test_set_active_take_same_take_is_no_change() -> None:
    stack = make_stack()
    stack.execute(SetActiveTake(L1, T1))
    with pytest.raises(NoChange):
        stack.execute(SetActiveTake(L1, T1))
    with pytest.raises(NoChange):
        stack.execute(SetActiveTake(L2, None))


def test_star_and_unstar() -> None:
    stack = make_stack()
    stack.execute(StarTake(T1, True))
    assert stack.project.takes[0].starred is True
    assert stack.undo_label == "Star take"
    stack.execute(StarTake(T1, False))
    assert stack.undo_label == "Unstar take"
    stack.undo()
    assert stack.project.takes[0].starred is True
    stack.undo()
    assert stack.project.takes[0].starred is False


def test_star_same_state_is_no_change_and_unknown_take_errors() -> None:
    stack = make_stack()
    with pytest.raises(NoChange):
        stack.execute(StarTake(T1, False))
    with pytest.raises(CommandError, match="unknown take"):
        stack.execute(StarTake("999999999999", True))


# ---- groups ----------------------------------------------------------------


def test_new_line_with_edits_is_one_undo_step() -> None:
    stack = make_stack()
    with stack.group("New line"):
        add = AddLine(line_id="ffffffffffff")
        stack.execute(add)
        stack.execute(SetLineText("ffffffffffff", "typed"))
        stack.execute(SetLineExaggeration("ffffffffffff", 0.9))
    assert stack.undo_label == "New line"
    stack.undo()
    assert [x.id for x in stack.project.lines] == [L1, L2]
    stack.redo()
    new = stack.project.lines[-1]
    assert (new.text, new.exaggeration) == ("typed", 0.9)


def test_group_with_a_failing_command_rolls_everything_back() -> None:
    stack = make_stack()
    with pytest.raises(CommandError), stack.group("Bad"):
        stack.execute(SetLineText(L1, "changed"))
        stack.execute(SetLineText("999999999999", "x"))
    assert line(stack).text == "one"
    assert not stack.can_undo


def test_undoing_add_line_is_refused_once_the_line_has_takes() -> None:
    stack = make_stack()
    stack.execute(AddLine("x", line_id="ffffffffffff"))
    stack.project.takes.append(make_take("999999999999", "ffffffffffff"))
    with pytest.raises(CommandError, match="1 take"):
        stack.undo()
    assert any(item.id == "ffffffffffff" for item in stack.project.lines)
    assert stack.can_undo
    assert not stack.can_redo
