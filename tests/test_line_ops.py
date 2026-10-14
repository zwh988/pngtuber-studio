"""Line bank edit ops (M3-4): parsing and mapping to commands."""

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.project.commands import CommandError
from backend.project.line_commands import (
    AddLine,
    RemoveLine,
    SetActiveTake,
    SetAllowOverlap,
    SetLineCfgWeight,
    SetLineEmotion,
    SetLineExaggeration,
    SetLineText,
    StarTake,
)
from backend.project.line_ops import LineEditBatch, LineEditOp, build_line_command

OP = TypeAdapter(LineEditOp)
L1 = "aaaaaaaaaaaa"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"op": "add_line"}, AddLine),
        ({"op": "add_line", "text": "hi", "emotion": "neutral"}, AddLine),
        ({"op": "remove_line", "line_id": L1}, RemoveLine),
        ({"op": "set_line_text", "line_id": L1, "text": "x"}, SetLineText),
        ({"op": "set_line_emotion", "line_id": L1, "emotion": "neutral"}, SetLineEmotion),
        ({"op": "set_line_exaggeration", "line_id": L1, "value": 1.0}, SetLineExaggeration),
        ({"op": "set_line_exaggeration", "line_id": L1, "value": None}, SetLineExaggeration),
        ({"op": "set_line_cfg_weight", "line_id": L1, "value": 0.2}, SetLineCfgWeight),
        ({"op": "set_allow_overlap", "line_id": L1, "value": True}, SetAllowOverlap),
        ({"op": "set_active_take", "line_id": L1, "take_id": None}, SetActiveTake),
        ({"op": "star_take", "take_id": L1}, StarTake),
    ],
)
def test_each_op_builds_its_command(body: dict[str, object], expected: type) -> None:
    assert isinstance(build_line_command(OP.validate_python(body)), expected)


def test_star_take_defaults_to_starred() -> None:
    command = build_line_command(OP.validate_python({"op": "star_take", "take_id": L1}))
    assert isinstance(command, StarTake)
    assert command.starred is True


def test_slider_value_is_required_but_may_be_null() -> None:
    with pytest.raises(ValidationError):
        OP.validate_python({"op": "set_line_exaggeration", "line_id": L1})


def test_extra_keys_and_unknown_ops_are_rejected() -> None:
    with pytest.raises(ValidationError):
        OP.validate_python({"op": "set_line_text", "line_id": L1, "text": "x", "oops": 1})
    with pytest.raises(ValidationError):
        OP.validate_python({"op": "nope"})


def test_known_emotions_are_passed_through() -> None:
    with pytest.raises(CommandError, match="unknown emotion"):
        build_line_command(
            OP.validate_python({"op": "add_line", "emotion": "furious"}),
            known_emotions={"neutral"},
        )
    with pytest.raises(CommandError, match="unknown emotion"):
        build_line_command(
            OP.validate_python(
                {"op": "set_line_emotion", "line_id": L1, "emotion": "furious"}
            ),
            known_emotions={"neutral"},
        )


def test_add_line_op_keeps_id_and_position() -> None:
    command = build_line_command(
        OP.validate_python({"op": "add_line", "line_id": L1, "position": 0})
    )
    assert isinstance(command, AddLine)
    assert command.line_id == L1
    assert command.position == 0


def test_batch_label_is_optional_but_not_empty_and_ops_are_required() -> None:
    assert LineEditBatch.model_validate({"ops": [{"op": "add_line"}]}).label is None
    with pytest.raises(ValidationError):
        LineEditBatch.model_validate({"label": "", "ops": [{"op": "add_line"}]})
    with pytest.raises(ValidationError):
        LineEditBatch.model_validate({"ops": []})
