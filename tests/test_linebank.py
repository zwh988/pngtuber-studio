"""Line bank state builder (M3-4). Pure."""

from backend.project.schema import Anchor, Line, Placement, Project, Take
from backend.voice.linebank import build_line_bank
from backend.voice.presets import parse_presets

PRESETS = parse_presets(
    {
        "presets": {
            "neutral": {"exaggeration": 0.5, "cfg_weight": 0.5, "expression": "neutral"},
            "excited": {"exaggeration": 0.9, "cfg_weight": 0.3, "expression": "happy"},
        }
    }
)
L1 = "aaaaaaaaaaaa"
L2 = "bbbbbbbbbbbb"
L3 = "cccccccccccc"


def take(take_id: str, line_id: str) -> Take:
    return Take(
        id=take_id,
        line_id=line_id,
        seed=1,
        text="t",
        exaggeration=0.5,
        cfg_weight=0.5,
        voice_profile_id="111111111111",
        model_version="m",
        raw_key="0" * 64,
        raw_file="media/takes_raw/x.wav",
        duration_ms=1000,
    )


def test_empty_project_lists_the_emotions_in_file_order() -> None:
    state = build_line_bank(Project(name="Rack"), PRESETS)
    assert state.lines == []
    assert state.emotions == ["neutral", "excited"]
    assert not state.can_undo


def test_effective_values_use_the_preset_then_the_overrides() -> None:
    project = Project(
        name="Rack",
        lines=[
            Line(id=L1, emotion="excited"),
            Line(id=L2, emotion="excited", exaggeration=1.4),
            Line(id=L3, emotion="neutral", cfg_weight=0.1),
        ],
    )
    first, second, third = build_line_bank(project, PRESETS).lines
    assert (first.effective_exaggeration, first.effective_cfg_weight) == (0.9, 0.3)
    assert (first.exaggeration, first.cfg_weight) == (None, None)
    assert (second.effective_exaggeration, second.effective_cfg_weight) == (1.4, 0.3)
    assert second.exaggeration == 1.4
    assert (third.effective_exaggeration, third.effective_cfg_weight) == (0.5, 0.1)


def test_unknown_emotion_is_flagged_without_failing() -> None:
    project = Project(name="Rack", lines=[Line(id=L1, emotion="furious")])
    item = build_line_bank(project, PRESETS).lines[0]
    assert item.emotion_known is False
    assert item.effective_exaggeration is None
    assert item.effective_cfg_weight is None
    assert item.emotion == "furious"


def test_counts_generated_flag_and_order() -> None:
    project = Project(
        name="Rack",
        lines=[
            Line(id=L2, text="second"),
            Line(id=L1, text="first", active_take_id="dddddddddddd"),
        ],
        takes=[take("dddddddddddd", L1), take("eeeeeeeeeeee", L1), take("ffffffffffff", L2)],
        placements=[
            Placement(id="111111111111", line_id=L1, anchor=Anchor(clip_id=L3, source_ms=0)),
        ],
    )
    state = build_line_bank(project, PRESETS)
    assert [item.id for item in state.lines] == [L2, L1]
    second, first = state.lines
    assert (second.take_count, second.placement_count, second.generated) == (1, 0, False)
    assert (first.take_count, first.placement_count, first.generated) == (2, 1, True)
    assert first.active_take_id == "dddddddddddd"


def test_undo_info_is_passed_through() -> None:
    state = build_line_bank(
        Project(name="Rack"),
        PRESETS,
        can_undo=True,
        undo_label="Add line",
        can_redo=True,
        redo_label="Remove line",
    )
    assert state.can_undo and state.can_redo
    assert (state.undo_label, state.redo_label) == ("Add line", "Remove line")
