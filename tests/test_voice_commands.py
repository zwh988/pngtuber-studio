"""Voice profile commands (M3-1)."""

import pytest

from backend.project.commands import CommandError, CommandStack
from backend.project.schema import Project, VoiceProfile
from backend.project.voice_commands import AddVoiceProfile, SetReferenceClip

PROFILE_ID = "aaaaaaaaaaaa"
CLIP = "media/voice/ref-01234567.wav"
OTHER = "media/voice/other-89abcdef.wav"


def make_stack(with_profile: bool = True) -> CommandStack:
    project = Project(name="Rack")
    if with_profile:
        project.voice_profiles.append(VoiceProfile(id=PROFILE_ID, name="Default"))
    return CommandStack(project)


def test_add_profile_apply_undo_redo() -> None:
    stack = make_stack(with_profile=False)
    command = AddVoiceProfile("  Main  ", profile_id=PROFILE_ID)
    stack.execute(command)
    assert [p.name for p in stack.project.voice_profiles] == ["Main"]
    assert command.profile_id == PROFILE_ID
    stack.undo()
    assert stack.project.voice_profiles == []
    stack.redo()
    assert stack.project.voice_profiles[0].id == PROFILE_ID


def test_add_profile_generates_an_id() -> None:
    assert len(AddVoiceProfile("Main").profile_id) == 12


def test_add_profile_rejects_an_empty_name() -> None:
    with pytest.raises(CommandError, match="must not be empty"):
        AddVoiceProfile("   ")


def test_add_profile_refuses_a_duplicate_id() -> None:
    stack = make_stack()
    with pytest.raises(CommandError, match="already exists"):
        stack.execute(AddVoiceProfile("Again", profile_id=PROFILE_ID))
    assert len(stack.project.voice_profiles) == 1
    assert not stack.can_undo


def test_set_reference_apply_undo_redo() -> None:
    stack = make_stack()
    stack.execute(SetReferenceClip(PROFILE_ID, CLIP))
    assert stack.project.voice_profiles[0].reference_clips == [CLIP]
    stack.undo()
    assert stack.project.voice_profiles[0].reference_clips == []
    stack.redo()
    assert stack.project.voice_profiles[0].reference_clips == [CLIP]


def test_set_reference_replaces_and_undo_restores_the_previous_clip() -> None:
    stack = make_stack()
    stack.execute(SetReferenceClip(PROFILE_ID, CLIP))
    stack.execute(SetReferenceClip(PROFILE_ID, OTHER))
    assert stack.project.voice_profiles[0].reference_clips == [OTHER]
    stack.undo()
    assert stack.project.voice_profiles[0].reference_clips == [CLIP]


def test_set_reference_refuses_the_current_clip_without_an_undo_step() -> None:
    stack = make_stack()
    stack.execute(SetReferenceClip(PROFILE_ID, CLIP))
    with pytest.raises(CommandError, match="already"):
        stack.execute(SetReferenceClip(PROFILE_ID, CLIP))
    assert stack.undo_label == "Set voice reference"
    stack.undo()
    assert not stack.can_undo


def test_set_reference_unknown_profile_changes_nothing() -> None:
    stack = make_stack()
    with pytest.raises(CommandError, match="unknown voice profile"):
        stack.execute(SetReferenceClip("bbbbbbbbbbbb", CLIP))
    assert stack.project.voice_profiles[0].reference_clips == []


@pytest.mark.parametrize(
    "path",
    [
        "ref.wav",
        "footage/ref.wav",
        "media/voice",
        "media/voice\\ref.wav",
        "media/voice/../ref.wav",
        "/media/voice/ref.wav",
        "C:/media/voice/ref.wav",
        "",
    ],
)
def test_set_reference_rejects_paths_outside_media_voice(path: str) -> None:
    with pytest.raises(CommandError):
        SetReferenceClip(PROFILE_ID, path)


def test_add_profile_and_reference_undo_together_in_a_group() -> None:
    stack = make_stack(with_profile=False)
    adding = AddVoiceProfile("Default", profile_id=PROFILE_ID)
    with stack.group("Set voice reference"):
        stack.execute(adding)
        stack.execute(SetReferenceClip(adding.profile_id, CLIP))
    assert stack.project.voice_profiles[0].reference_clips == [CLIP]
    stack.undo()
    assert stack.project.voice_profiles == []
    stack.redo()
    assert stack.project.voice_profiles[0].reference_clips == [CLIP]
