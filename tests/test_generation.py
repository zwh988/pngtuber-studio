"""Generation planning (M3-4): seed policy, keys, chunks. Pure."""

import pytest

from backend.project.schema import Line, Project, Take
from backend.voice.chunking import plan_chunks
from backend.voice.generation import GenerationError, plan_generation
from backend.voice.keys import base_seed, raw_key
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
VOICE = "666666666666"
REF_HASH = "f" * 64
MODEL = "chatterbox-test"


def plan(project: Project, line_id: str = L1, *, reroll: bool = False, **changes: str):
    kwargs = {
        "voice_profile_id": VOICE,
        "reference_hash": REF_HASH,
        "reference_path": "C:/proj/media/voice/ref.wav",
        "model_version": MODEL,
    }
    kwargs.update(changes)
    return plan_generation(project, line_id, PRESETS, reroll=reroll, **kwargs)


def make_project(text: str = "Nice shot.", **line_fields: object) -> Project:
    return Project(name="Rack", seed=1234, lines=[Line(id=L1, text=text, **line_fields)])


def take_with_key(project: Project, line_id: str, key: str, take_id: str) -> None:
    project.takes.append(
        Take(
            id=take_id,
            line_id=line_id,
            seed=0,
            text="x",
            exaggeration=0.5,
            cfg_weight=0.5,
            voice_profile_id=VOICE,
            model_version=MODEL,
            raw_key=key,
            raw_file=f"media/takes_raw/{take_id}.wav",
            duration_ms=1,
        )
    )


def test_first_generation_uses_the_base_seed_and_the_raw_key() -> None:
    project = make_project()
    result = plan(project)
    base = base_seed(1234, L1)
    expected = raw_key(
        text="Nice shot.",
        voice_profile_id=VOICE,
        reference_hash=REF_HASH,
        exaggeration=0.5,
        cfg_weight=0.5,
        seed=base,
        model_version=MODEL,
    )
    take = result.new_take
    assert (take.line_id, take.seed, take.raw_key) == (L1, base, expected)
    assert (take.text, take.exaggeration, take.cfg_weight) == ("Nice shot.", 0.5, 0.5)
    assert (take.voice_profile_id, take.model_version) == (VOICE, MODEL)
    assert result.chunks == ("Nice shot.",)
    assert result.reference_path == "C:/proj/media/voice/ref.wav"
    assert result.reroll is False


def test_planning_twice_gives_the_same_plan() -> None:
    project = make_project()
    assert plan(project) == plan(project)


def test_text_is_normalized_before_keying() -> None:
    assert plan(make_project("  Nice   shot.\n")).new_take == plan(make_project()).new_take


def test_emotion_and_overrides_decide_the_parameters_and_the_key() -> None:
    neutral = plan(make_project()).new_take
    excited = plan(make_project(emotion="excited")).new_take
    override = plan(make_project(emotion="excited", exaggeration=1.4)).new_take
    assert (excited.exaggeration, excited.cfg_weight) == (0.9, 0.3)
    assert (override.exaggeration, override.cfg_weight) == (1.4, 0.3)
    assert len({neutral.raw_key, excited.raw_key, override.raw_key}) == 3


def test_voice_reference_and_model_are_part_of_the_key() -> None:
    project = make_project()
    base = plan(project).new_take.raw_key
    assert plan(project, reference_hash="e" * 64).new_take.raw_key != base
    assert plan(project, model_version="other").new_take.raw_key != base
    assert plan(project, voice_profile_id="777777777777").new_take.raw_key != base


def test_reroll_without_takes_uses_the_base_seed() -> None:
    project = make_project()
    assert plan(project, reroll=True).new_take.seed == base_seed(1234, L1)


def test_reroll_skips_seeds_already_used_by_the_line() -> None:
    project = make_project()
    base = base_seed(1234, L1)
    first = plan(project).new_take
    take_with_key(project, L1, first.raw_key, "111111111111")
    second = plan(project, reroll=True).new_take
    assert second.seed == base + 1
    assert second.raw_key != first.raw_key
    take_with_key(project, L1, second.raw_key, "222222222222")
    assert plan(project, reroll=True).new_take.seed == base + 2


def test_plain_generate_does_not_reroll() -> None:
    project = make_project()
    first = plan(project).new_take
    take_with_key(project, L1, first.raw_key, "111111111111")
    again = plan(project).new_take
    assert again.raw_key == first.raw_key  # so reuse_take will find it


def test_reroll_ignores_other_lines_takes() -> None:
    project = make_project()
    project.lines.append(Line(id=L2, text="Nice shot."))
    first = plan(project).new_take
    take_with_key(project, L2, first.raw_key, "111111111111")
    assert plan(project, reroll=True).new_take.seed == base_seed(1234, L1)


def test_editing_the_text_changes_the_key_but_not_the_first_seed() -> None:
    project = make_project()
    old = plan(project).new_take
    take_with_key(project, L1, old.raw_key, "111111111111")
    project.lines[0].text = "Terrible shot."
    new = plan(project, reroll=True).new_take
    assert new.seed == old.seed
    assert new.raw_key != old.raw_key


def test_long_text_is_chunked() -> None:
    text = " ".join(f"This is sentence number {i} of the long line." for i in range(12))
    result = plan(make_project(text))
    assert len(result.chunks) > 1
    assert result.chunks == tuple(plan_chunks(text))


def test_unusable_lines_are_refused() -> None:
    with pytest.raises(GenerationError, match="no text"):
        plan(make_project("  \n "))
    with pytest.raises(GenerationError, match="unknown emotion"):
        plan(make_project(emotion="furious"))
    with pytest.raises(GenerationError, match="unknown line id"):
        plan(make_project(), line_id=L2)


@pytest.mark.parametrize(
    "field", ["voice_profile_id", "reference_hash", "model_version"]
)
def test_empty_key_inputs_are_refused(field: str) -> None:
    with pytest.raises(GenerationError, match="must not be empty"):
        plan(make_project(), **{field: ""})
