"""Voice chain commands and ops (M4-1, S3c)."""

import math

import pytest
from pydantic import ValidationError

from backend.project.commands import CommandError, CommandStack
from backend.project.fx_commands import SetFxChain, SetGameAudioDb
from backend.project.fx_ops import (
    FxEditBatch,
    SetFxChainOp,
    SetGameAudioDbOp,
    build_fx_command,
)
from backend.project.line_commands import NoChange
from backend.project.schema import EffectSpec, FxChain, Project


def make_project() -> Project:
    return Project(name="t")


# --- SetFxChain ----------------------------------------------------------------


def test_set_fx_chain_applies_and_reverts() -> None:
    project = make_project()
    command = SetFxChain(FxChain(eq_bass_db=4.0, loudness_target_lufs=-18.0))
    command.apply(project)
    assert project.fx_chain.eq_bass_db == 4.0
    assert project.fx_chain.loudness_target_lufs == -18.0
    command.revert(project)
    assert project.fx_chain == FxChain()


def test_the_command_keeps_its_own_copy_of_the_chain() -> None:
    project = make_project()
    chain = FxChain(eq_bass_db=4.0)
    command = SetFxChain(chain)
    chain.eq_bass_db = 9.0  # a later edit by the caller must not leak in
    command.apply(project)
    assert project.fx_chain.eq_bass_db == 4.0
    assert project.fx_chain is not command.chain


def test_setting_the_same_chain_is_no_change() -> None:
    project = make_project()
    with pytest.raises(NoChange):
        SetFxChain(FxChain()).apply(project)
    assert project.fx_chain == FxChain()


def test_an_unusable_chain_is_refused_and_changes_nothing() -> None:
    project = make_project()
    with pytest.raises(CommandError, match="eq_bass_db") as caught:
        SetFxChain(FxChain(eq_bass_db=99.0)).apply(project)
    assert not isinstance(caught.value, NoChange)
    assert project.fx_chain == FxChain()


def test_an_unknown_effect_is_refused() -> None:
    chain = FxChain(effects=[EffectSpec(type="warp_drive", params={})])
    with pytest.raises(CommandError, match="warp_drive"):
        SetFxChain(chain).apply(make_project())


def test_a_known_effect_is_accepted() -> None:
    chain = FxChain(effects=[EffectSpec(type="chorus", params={"mix": 0.3})])
    project = make_project()
    SetFxChain(chain).apply(project)
    assert project.fx_chain.effects[0].type == "chorus"


def test_undo_and_redo_walk_through_the_chains() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(SetFxChain(FxChain(eq_bass_db=1.0)))
    stack.execute(SetFxChain(FxChain(eq_bass_db=2.0)))
    assert stack.undo_label == "Set voice chain"
    stack.undo()
    assert project.fx_chain.eq_bass_db == 1.0
    stack.undo()
    assert project.fx_chain == FxChain()
    stack.redo()
    assert project.fx_chain.eq_bass_db == 1.0


def test_a_group_of_a_chain_and_a_level_undoes_together() -> None:
    project = make_project()
    stack = CommandStack(project)
    with stack.group("Voice preset"):
        stack.execute(SetFxChain(FxChain(eq_treble_db=3.0)))
        stack.execute(SetGameAudioDb(-8.0))
    stack.undo()
    assert project.fx_chain == FxChain()
    assert project.game_audio_db == 0.0


# --- SetGameAudioDb ------------------------------------------------------------


def test_set_game_audio_applies_and_reverts() -> None:
    project = make_project()
    command = SetGameAudioDb(-6.0)
    command.apply(project)
    assert project.game_audio_db == -6.0
    command.revert(project)
    assert project.game_audio_db == 0.0


def test_the_level_is_rounded() -> None:
    project = make_project()
    SetGameAudioDb(-6.004).apply(project)
    assert project.game_audio_db == -6.0


def test_the_same_level_is_no_change() -> None:
    project = make_project()
    with pytest.raises(NoChange):
        SetGameAudioDb(0.0).apply(project)
    with pytest.raises(NoChange):
        SetGameAudioDb(-0.0).apply(project)


@pytest.mark.parametrize("bad", [-60.1, 12.1, math.nan, math.inf, True])
def test_a_bad_level_is_refused_when_the_command_is_made(bad: float) -> None:
    with pytest.raises(CommandError, match="game audio level"):
        SetGameAudioDb(bad)


# --- ops -----------------------------------------------------------------------


def test_ops_parse_and_build_the_matching_commands() -> None:
    batch = FxEditBatch.model_validate(
        {
            "ops": [
                {"op": "set_fx_chain", "chain": {"eq_bass_db": 2.0}},
                {"op": "set_game_audio_db", "db": -6},
            ],
            "label": "Voice preset",
        }
    )
    first, second = batch.ops
    assert isinstance(first, SetFxChainOp)
    assert isinstance(second, SetGameAudioDbOp)
    chain_command = build_fx_command(first)
    assert isinstance(chain_command, SetFxChain)
    assert chain_command.chain.eq_bass_db == 2.0
    assert isinstance(build_fx_command(second), SetGameAudioDb)


def test_a_chain_op_fills_in_defaults() -> None:
    batch = FxEditBatch.model_validate(
        {"ops": [{"op": "set_fx_chain", "chain": {"eq_mid_db": 1.5}}]}
    )
    op = batch.ops[0]
    assert isinstance(op, SetFxChainOp)
    assert op.chain.loudness_target_lufs == -16.0
    assert batch.label is None


@pytest.mark.parametrize(
    "body",
    [
        {"ops": []},
        {"ops": [{"op": "set_game_audio_db", "db": 1, "extra": 1}]},
        {"ops": [{"op": "launch_rocket"}]},
        {"ops": [{"op": "set_fx_chain", "chain": {"eq_bass_dB": 1.0}}]},
        {"ops": [{"op": "set_game_audio_db", "db": 1}], "label": ""},
    ],
)
def test_bad_request_bodies_are_rejected(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        FxEditBatch.model_validate(body)
