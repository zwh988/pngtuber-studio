"""The whole take lifecycle through Session with a fake generator standing in
for the worker: generate, reuse, reroll, close, reopen, zero regeneration."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from backend.project.line_ops import (
    AddLineOp,
    SetActiveTakeOp,
    SetLineTextOp,
    StarTakeOp,
)
from backend.project.session import Session, SessionError
from backend.voice.generation import GenerationPlan
from backend.voice.presets import parse_presets
from backend.voice.profile import AudioInfo

PRESETS = parse_presets(
    {"presets": {"neutral": {"exaggeration": 0.5, "cfg_weight": 0.5, "expression": "neutral"}}}
)
L1 = "aaaaaaaaaaaa"
MODEL = "chatterbox-test"
RATE = 24000


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def good_info(path: Path) -> AudioInfo:
    return AudioInfo(duration_ms=8000, sample_rate=RATE, channels=1)


class FakeGenerator:
    """Stands in for the GPU worker: counts calls, returns a tone per chunk."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, plan: GenerationPlan) -> np.ndarray:
        self.calls += 1
        samples = 1200 * len(plan.chunks)
        return (0.3 * np.sin(np.arange(samples) / 10)).astype(np.float32)


def make_session() -> Session:
    return Session(probe=fake_probe, audio_info=good_info, presets=PRESETS)


def generate(session: Session, generator: FakeGenerator, *, reroll: bool = False):
    """What the generate endpoint will do (chat C): plan, reuse, else generate."""
    plan = session.plan_generation(L1, model_version=MODEL, reroll=reroll)
    reused = session.reuse_take(plan.new_take)
    if reused is not None:
        return reused
    return session.add_take(plan.new_take, generator(plan), RATE)


def open_ready_project(tmp_path: Path, text: str = "Nice shot.") -> tuple[Session, Path]:
    session = make_session()
    session.new_project(str(tmp_path), "Rack")
    clip = tmp_path / "ref.wav"
    clip.write_bytes(b"reference-audio" * 20)
    session.set_voice_reference(str(clip))
    session.edit_lines([AddLineOp(line_id=L1, text=text)])
    return session, tmp_path / "Rack"


def test_plan_needs_a_ready_voice_reference(tmp_path: Path) -> None:
    session = make_session()
    session.new_project(str(tmp_path), "Rack")
    session.edit_lines([AddLineOp(line_id=L1, text="hi")])
    with pytest.raises(SessionError, match="voice reference is not ready"):
        session.plan_generation(L1, model_version=MODEL)


def test_plan_reports_line_problems(tmp_path: Path) -> None:
    session, _ = open_ready_project(tmp_path, text="")
    with pytest.raises(SessionError, match="no text"):
        session.plan_generation(L1, model_version=MODEL)
    with pytest.raises(SessionError, match="unknown line id"):
        session.plan_generation("999999999999", model_version=MODEL)


def test_plan_points_the_worker_at_the_project_copy_of_the_reference(
    tmp_path: Path,
) -> None:
    session, folder = open_ready_project(tmp_path)
    plan = session.plan_generation(L1, model_version=MODEL)
    assert Path(plan.reference_path).parent == folder / "media" / "voice"
    assert Path(plan.reference_path).is_file()
    assert plan.new_take.voice_profile_id == session.voice().profile_id
    assert plan.new_take.raw_key
    assert len(plan.new_take.raw_key) == 64


def test_generate_then_generate_again_runs_the_worker_once(tmp_path: Path) -> None:
    session, _ = open_ready_project(tmp_path)
    worker = FakeGenerator()
    first = generate(session, worker)
    second = generate(session, worker)
    assert first.reused is False
    assert second.reused is True
    assert second.take.id == first.take.id
    assert worker.calls == 1
    assert len(session.takes(L1)) == 1


def test_reroll_makes_a_new_take_and_keeps_the_old_one(tmp_path: Path) -> None:
    session, _ = open_ready_project(tmp_path)
    worker = FakeGenerator()
    first = generate(session, worker)
    second = generate(session, worker, reroll=True)
    assert second.reused is False
    assert second.take.id != first.take.id
    assert second.take.seed == first.take.seed + 1
    assert worker.calls == 2
    takes = {take.id: take for take in session.takes(L1)}
    assert set(takes) == {first.take.id, second.take.id}
    assert takes[second.take.id].active is True
    assert takes[first.take.id].active is False
    third = generate(session, worker, reroll=True)
    assert third.take.seed == first.take.seed + 2


def test_set_active_and_star_work_on_the_rerolled_takes(tmp_path: Path) -> None:
    session, _ = open_ready_project(tmp_path)
    worker = FakeGenerator()
    first = generate(session, worker)
    generate(session, worker, reroll=True)
    session.edit_lines(
        [SetActiveTakeOp(line_id=L1, take_id=first.take.id), StarTakeOp(take_id=first.take.id)],
        label="Pick take",
    )
    takes = {take.id: take for take in session.takes(L1)}
    assert takes[first.take.id].active is True
    assert takes[first.take.id].starred is True


def test_close_and_reopen_needs_no_regeneration(tmp_path: Path) -> None:
    session, folder = open_ready_project(tmp_path)
    worker = FakeGenerator()
    first = generate(session, worker)
    rerolled = generate(session, worker, reroll=True)
    assert worker.calls == 2

    reopened = make_session()
    reopened.open_project(str(folder))
    again = generate(reopened, worker)  # same inputs as the first generation
    assert again.reused is True
    assert again.take.id == first.take.id
    assert worker.calls == 2
    assert {take.id for take in reopened.takes(L1)} == {first.take.id, rerolled.take.id}


def test_editing_the_text_needs_a_new_generation(tmp_path: Path) -> None:
    session, _ = open_ready_project(tmp_path)
    worker = FakeGenerator()
    generate(session, worker)
    session.edit_lines([SetLineTextOp(line_id=L1, text="A different line.")])
    result = generate(session, worker)
    assert result.reused is False
    assert worker.calls == 2
    assert len(session.takes(L1)) == 2


def test_a_long_line_reaches_the_worker_in_chunks(tmp_path: Path) -> None:
    text = " ".join(f"This is sentence number {i} of the long line." for i in range(12))
    session, _ = open_ready_project(tmp_path, text=text)
    plan = session.plan_generation(L1, model_version=MODEL)
    assert len(plan.chunks) > 1
