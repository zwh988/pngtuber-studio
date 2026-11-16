"""Manual take trim backend (M5-0, S3): schema v3, migration, the set_take_trim op,
processed keys, trim bounds inside the cut, render with edge fades, and the session
path (timeline length, undo, raw file untouched)."""

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile
from pydantic import TypeAdapter, ValidationError

from backend.audio import processed
from backend.audio.prefetch import plan_jobs
from backend.audio.processed import sidecar_path, trim_bounds_for
from backend.audio.trim import (
    manual_cuts_from_spec,
    spec_with_manual_trim,
)
from backend.audio.wanted import played_takes
from backend.project.commands import CommandError, CommandStack
from backend.project.line_commands import NoChange, SetTakeTrim
from backend.project.line_ops import (
    AddLineOp,
    LineEditBatch,
    LineEditOp,
    SetTakeTrimOp,
    build_line_command,
)
from backend.project.migrations import migrate
from backend.project.schema import (
    SCHEMA_VERSION,
    Anchor,
    Line,
    Placement,
    Project,
    Take,
)
from backend.project.session import Session, SessionError
from backend.voice.presets import parse_presets
from backend.voice.takes import NewTake, build_take_item

RATE = 24000
LINE, TAKE, PLACE, VOICE = "1" * 12, "2" * 12, "3" * 12, "4" * 12


def make_take(**kw: Any) -> Take:
    data: dict[str, Any] = {
        "id": TAKE,
        "line_id": LINE,
        "seed": 1,
        "text": "hello",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "voice_profile_id": VOICE,
        "model_version": "m",
        "raw_key": "a" * 64,
        "raw_file": f"media/takes_raw/{TAKE}.wav",
        "duration_ms": 2000,
    }
    data.update(kw)
    return Take(**data)


def make_project(**take_kw: Any) -> Project:
    return Project(
        name="t",
        lines=[Line(id=LINE, text="hello", active_take_id=TAKE)],
        takes=[make_take(**take_kw)],
        placements=[
            Placement(id=PLACE, line_id=LINE, anchor=Anchor(clip_id="5" * 12, source_ms=0))
        ],
    )


# ---- schema and migration ---------------------------------------------------


def test_schema_has_the_trim_fields_and_they_default_to_none() -> None:
    assert SCHEMA_VERSION >= 3
    take = make_take()
    assert (take.trim_start_ms, take.trim_end_ms) == (None, None)


def test_schema_refuses_a_start_at_or_after_the_end() -> None:
    with pytest.raises(ValidationError):
        make_take(trim_start_ms=500, trim_end_ms=500)
    with pytest.raises(ValidationError):
        make_take(trim_start_ms=-1)
    with pytest.raises(ValidationError):
        make_take(trim_end_ms=0)
    assert make_take(trim_start_ms=100, trim_end_ms=900).trim_end_ms == 900


def v2_data() -> dict[str, Any]:
    data = json.loads(make_project().model_dump_json())
    data["schema_version"] = 2
    for take in data["takes"]:
        del take["trim_start_ms"]
        del take["trim_end_ms"]
    return data


def test_migration_v2_to_v3_adds_empty_trim_to_every_take() -> None:
    old = v2_data()
    result = migrate(old, target=3)
    assert result["schema_version"] == 3
    assert result["takes"][0]["trim_start_ms"] is None
    assert result["takes"][0]["trim_end_ms"] is None
    assert "trim_start_ms" not in old["takes"][0]  # input not mutated
    assert Project.model_validate(result).takes[0].trim_end_ms is None


def test_migration_from_v1_runs_both_steps() -> None:
    data = v2_data()
    data["schema_version"] = 1
    for placement in data["placements"]:
        del placement["stretch"]
    result = migrate(data, target=3)
    assert result["schema_version"] == 3
    assert result["placements"][0]["stretch"] == 1.0
    assert result["takes"][0]["trim_start_ms"] is None


def test_migration_works_without_takes() -> None:
    assert migrate({"schema_version": 2, "name": "x"}, target=3)["schema_version"] == 3


# ---- command and op ------------------------------------------------------------


def test_set_take_trim_apply_undo_redo() -> None:
    project = make_project()
    stack = CommandStack(project)
    stack.execute(SetTakeTrim(TAKE, 150, 1800))
    take = project.takes[0]
    assert (take.trim_start_ms, take.trim_end_ms) == (150, 1800)
    assert stack.undo_label == "Trim take"
    stack.undo()
    assert (take.trim_start_ms, take.trim_end_ms) == (None, None)
    stack.redo()
    assert (take.trim_start_ms, take.trim_end_ms) == (150, 1800)


def test_set_take_trim_can_move_start_past_the_old_end() -> None:
    project = make_project(trim_start_ms=100, trim_end_ms=600)
    stack = CommandStack(project)
    stack.execute(SetTakeTrim(TAKE, 800, 1500))
    assert (project.takes[0].trim_start_ms, project.takes[0].trim_end_ms) == (800, 1500)
    stack.undo()
    assert (project.takes[0].trim_start_ms, project.takes[0].trim_end_ms) == (100, 600)


def test_set_take_trim_canonicalises_cuts_at_the_ends() -> None:
    project = make_project()
    with pytest.raises(NoChange):
        SetTakeTrim(TAKE, 0, 2000).apply(project)  # same as no cut
    SetTakeTrim(TAKE, 0, 1500).apply(project)
    assert (project.takes[0].trim_start_ms, project.takes[0].trim_end_ms) == (None, 1500)


def test_set_take_trim_reset_label_and_refusals() -> None:
    project = make_project(trim_start_ms=100)
    reset = SetTakeTrim(TAKE, None, None)
    assert reset.label == "Reset take trim"
    reset.apply(project)
    assert project.takes[0].trim_start_ms is None
    for start, end in ((1500, 1000), (None, 2500), (1000, 1100), (-5, None)):
        with pytest.raises(CommandError):
            SetTakeTrim(TAKE, start, end).apply(project)
    with pytest.raises(CommandError):
        SetTakeTrim("9" * 12, 100, None).apply(project)
    assert project.takes[0].trim_start_ms is None  # refusals change nothing


def test_set_take_trim_op_parses_and_builds_the_command() -> None:
    op = TypeAdapter(LineEditOp).validate_python(
        {"op": "set_take_trim", "take_id": TAKE, "start_ms": 100, "end_ms": None}
    )
    assert isinstance(op, SetTakeTrimOp)
    command = build_line_command(op)
    assert isinstance(command, SetTakeTrim)
    assert (command.start_ms, command.end_ms) == (100, None)
    with pytest.raises(ValidationError):
        LineEditBatch.model_validate(
            {"ops": [{"op": "set_take_trim", "take_id": TAKE, "bogus": 1}]}
        )


def test_take_item_reports_the_cut_points() -> None:
    project = make_project(trim_start_ms=120, trim_end_ms=1700)
    item = build_take_item(project.takes[0], project.lines[0], True)
    assert (item.trim_start_ms, item.trim_end_ms) == (120, 1700)


# ---- keys and jobs -------------------------------------------------------------

SPEC: dict[str, Any] = {"version": 1, "stages": [], "loudness": {"target_lufs": -16}}


def test_manual_cuts_round_trip_through_the_spec() -> None:
    assert manual_cuts_from_spec(SPEC) == (None, None)
    assert manual_cuts_from_spec(spec_with_manual_trim(SPEC, 100, None)) == (100, None)
    assert manual_cuts_from_spec(spec_with_manual_trim(SPEC, None, 900)) == (None, 900)
    with pytest.raises(ValueError):
        manual_cuts_from_spec({"manual_trim": {"start_ms": -1}})
    with pytest.raises(ValueError):
        manual_cuts_from_spec({"manual_trim": 5})


def test_played_takes_carry_the_cut_points() -> None:
    played = played_takes(make_project(trim_start_ms=50, trim_end_ms=1900))
    assert (played[0].trim_start_ms, played[0].trim_end_ms) == (50, 1900)


def test_plan_jobs_keys_a_trimmed_take_apart_and_leaves_others_alone(
    tmp_path: Path,
) -> None:
    plain = plan_jobs(tmp_path, make_project())[0]
    cut = plan_jobs(tmp_path, make_project(trim_start_ms=100))[0]
    other = plan_jobs(tmp_path, make_project(trim_start_ms=200))[0]
    assert "manual_trim" not in plain.spec
    assert cut.spec["manual_trim"]["start_ms"] == 100
    assert len({plain.dest.name, cut.dest.name, other.dest.name}) == 3
    # The same cut gives the same file (rule 3).
    assert plan_jobs(tmp_path, make_project(trim_start_ms=100))[0].dest == cut.dest


# ---- trim bounds inside the manual region ------------------------------------------


def write_take(folder: Path, name: str = TAKE) -> Path:
    """0.5 s silence, 0.2 s click, 0.3 s silence, 1 s tone, 0.5 s silence (2.5 s)."""
    raw = folder / "media" / "takes_raw" / f"{name}.wav"
    raw.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(RATE) / RATE
    click = 0.5 * np.sin(2 * np.pi * 1000 * t[: RATE // 5])
    tone = 0.3 * np.sin(2 * np.pi * 220 * t)
    data = np.concatenate(
        [
            np.zeros(RATE // 2),
            click,
            np.zeros(RATE * 3 // 10),
            tone,
            np.zeros(RATE // 2),
        ]
    ).astype(np.float32)
    soundfile.write(str(raw), data, RATE, subtype="FLOAT", format="WAV")
    return raw


def test_bounds_are_measured_inside_the_cut(tmp_path: Path) -> None:
    raw = write_take(tmp_path)
    whole = trim_bounds_for(raw)
    assert whole.start < RATE * 6 // 10  # the click counts without a cut
    cut = trim_bounds_for(raw, manual_start_ms=800)
    assert cut.start >= RATE * 8 // 10  # never before the cut
    assert cut.start < RATE  # but before the tone
    assert cut.end == whole.end
    data = json.loads(sidecar_path(raw).read_text(encoding="utf-8"))
    assert data["manual_start_ms"] == 800


def test_changing_the_cut_measures_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = write_take(tmp_path)
    trim_bounds_for(raw, manual_start_ms=800)
    calls: list[tuple[int | None, int | None]] = []
    real = processed.measure_bounds

    def counting(path: Path, start: int | None = None, end: int | None = None):
        calls.append((start, end))
        return real(path, start, end)

    monkeypatch.setattr(processed, "measure_bounds", counting)
    trim_bounds_for(raw, manual_start_ms=800)  # sidecar matches
    assert calls == []
    trim_bounds_for(raw, manual_start_ms=900)
    trim_bounds_for(raw)
    assert calls == [(900, None), (None, None)]


def test_a_cut_on_loud_audio_keeps_the_cut_edge(tmp_path: Path) -> None:
    raw = write_take(tmp_path)
    bounds = trim_bounds_for(raw, manual_start_ms=1500, manual_end_ms=1700)
    assert (bounds.start, bounds.end) == (RATE * 3 // 2, RATE * 17 // 10)


# ---- render ----------------------------------------------------------------------


def test_render_applies_the_cut_and_a_fade_and_leaves_the_raw_file(
    tmp_path: Path,
) -> None:
    pytest.importorskip("pedalboard")
    pytest.importorskip("pyloudnorm")
    from backend.audio.chainspec import processing_spec
    from backend.audio.processed import ensure_processed
    from backend.audio.trim import trimmed_duration_ms

    raw = write_take(tmp_path)
    before = hashlib.sha256(raw.read_bytes()).hexdigest()
    spec = spec_with_manual_trim(processing_spec(make_project().fx_chain), 1500, 1700)
    dest = ensure_processed(raw, "a" * 64, 1.0, spec)
    out, rate = soundfile.read(str(dest), dtype="float32")
    assert rate == RATE
    assert out.size == RATE // 5  # 200 ms kept, no stretch
    bounds = trim_bounds_for(raw, manual_start_ms=1500, manual_end_ms=1700)
    assert trimmed_duration_ms(bounds) == 200
    assert abs(float(out[0])) < 1e-3  # faded in from silence
    assert abs(float(out[-1])) < 0.05  # faded out
    assert float(np.max(np.abs(out[RATE // 20 : RATE // 10]))) > 0.05  # audio kept
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == before  # rule 1


# ---- session ---------------------------------------------------------------------

PRESETS = parse_presets(
    {"presets": {"neutral": {"exaggeration": 0.5, "cfg_weight": 0.5, "expression": "neutral"}}}
)


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def open_with_take(tmp_path: Path) -> tuple[Session, Path, str]:
    session = Session(probe=fake_probe, presets=PRESETS)
    session.new_project(str(tmp_path), "Rack")
    session.edit_lines([AddLineOp(line_id=LINE, text="hello")])
    folder = tmp_path / "Rack"
    audio, _ = soundfile.read(str(write_take(tmp_path / "src")), dtype="float32")
    result = session.add_take(
        NewTake(
            line_id=LINE,
            seed=7,
            text="hello",
            exaggeration=0.5,
            cfg_weight=0.5,
            voice_profile_id=VOICE,
            model_version="test",
            raw_key="a" * 64,
            take_id=TAKE,
        ),
        audio,
        RATE,
    )
    stack = session._stack
    assert stack is not None
    stack.project.placements.append(
        Placement(id=PLACE, line_id=LINE, anchor=Anchor(clip_id="5" * 12, source_ms=0))
    )
    return session, folder, result.take.raw_file


def placed_length(session: Session) -> int | None:
    return session.timeline().placements[0].raw_duration_ms


def test_session_trim_changes_the_block_length_and_undo_restores_it(
    tmp_path: Path,
) -> None:
    session, folder, raw_file = open_with_take(tmp_path)
    raw = folder / raw_file
    before = hashlib.sha256(raw.read_bytes()).hexdigest()
    untrimmed = placed_length(session)
    assert untrimmed is not None
    state = session.edit_lines([SetTakeTrimOp(take_id=TAKE, start_ms=800)])
    assert state.can_undo
    trimmed = placed_length(session)
    assert trimmed is not None and trimmed <= untrimmed - 450  # the click is gone
    assert session.takes(LINE)[0].trim_start_ms == 800
    session.undo()
    assert placed_length(session) == untrimmed
    session.redo()
    assert placed_length(session) == trimmed
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == before  # rule 1


def test_session_refuses_a_bad_trim(tmp_path: Path) -> None:
    session, _, _ = open_with_take(tmp_path)
    with pytest.raises(SessionError):
        session.edit_lines([SetTakeTrimOp(take_id=TAKE, start_ms=2000, end_ms=1000)])
    assert session.takes(LINE)[0].trim_start_ms is None


def test_session_trim_is_saved_and_reopened(tmp_path: Path) -> None:
    session, folder, _ = open_with_take(tmp_path)
    session.edit_lines([SetTakeTrimOp(take_id=TAKE, start_ms=300, end_ms=2200)])
    reopened = Session(probe=fake_probe, presets=PRESETS)
    reopened.open_project(str(folder))
    item = reopened.takes(LINE)[0]
    assert (item.trim_start_ms, item.trim_end_ms) == (300, 2200)


def test_take_trim_reports_auto_bounds_inside_the_cut(tmp_path: Path) -> None:
    session, _, _ = open_with_take(tmp_path)
    whole = session.take_trim(TAKE)
    assert (whole.trim_start_ms, whole.trim_end_ms) == (None, None)
    assert 400 <= whole.auto_start_ms <= 500  # the click at 500 ms, 40 ms before
    preview = session.take_trim(TAKE, preview=True, start_ms=800)
    assert preview.trim_start_ms == 800
    assert preview.stored_start_ms is None  # nothing was stored
    assert 900 <= preview.auto_start_ms <= 1000
    assert preview.auto_end_ms == whole.auto_end_ms
    with pytest.raises(SessionError):
        session.take_trim(TAKE, preview=True, start_ms=2400)
    session.edit_lines([SetTakeTrimOp(take_id=TAKE, start_ms=800)])
    stored = session.take_trim(TAKE)
    assert (stored.stored_start_ms, stored.auto_start_ms) == (800, preview.auto_start_ms)


def test_timeline_placement_carries_the_trim_tag(tmp_path: Path) -> None:
    session, _, _ = open_with_take(tmp_path)
    assert session.timeline().placements[0].trim == ""
    session.edit_lines([SetTakeTrimOp(take_id=TAKE, start_ms=800)])
    assert session.timeline().placements[0].trim == "800-"
    session.edit_lines([SetTakeTrimOp(take_id=TAKE, start_ms=800, end_ms=2000)])
    assert session.timeline().placements[0].trim == "800-2000"


def test_trim_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from backend.app import create_app

    session, _, _ = open_with_take(tmp_path)
    client = TestClient(create_app(session=session))
    body = client.get(f"/api/takes/{TAKE}/trim").json()
    assert body["take_id"] == TAKE and body["trim_start_ms"] is None
    body = client.get(f"/api/takes/{TAKE}/trim?preview=1&start_ms=800").json()
    assert body["trim_start_ms"] == 800
    assert client.get(f"/api/takes/{TAKE}/trim?preview=1&start_ms=9999").status_code == 400
    assert client.get(f"/api/takes/{'9' * 12}/trim").status_code == 400


def test_envelope_endpoint_follows_the_trim(tmp_path: Path) -> None:
    """M5-2: the envelope is of the processed take, so a trim shortens it."""
    pytest.importorskip("pedalboard")
    pytest.importorskip("pyloudnorm")
    from fastapi.testclient import TestClient

    from backend.app import create_app

    session, folder, _ = open_with_take(tmp_path)
    client = TestClient(create_app(session=session))
    whole = client.get(f"/api/takes/{TAKE}/envelope").json()
    assert whole["hop_ms"] == 10
    played = session.timeline().placements[0].duration_ms
    assert played is not None
    assert abs(len(whole["values"]) * 10 - played) <= 10
    assert list((folder / "media" / "envelopes").glob("*.env.json"))
    session.edit_lines([SetTakeTrimOp(take_id=TAKE, start_ms=800)])
    cut = client.get(f"/api/takes/{TAKE}/envelope").json()
    assert len(cut["values"]) < len(whole["values"]) - 40
    assert client.get(f"/api/takes/{'9' * 12}/envelope").status_code == 404
