"""Export pre-flight (M6-1): pure checks, the session wrapper and the endpoint."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.export import clipeffects
from backend.export.clipeffects import ClipEffect
from backend.export.preflight import PreflightReport, preflight
from backend.export.tools import encoder_problem, nvenc_probe_args
from backend.project.schema import Clip, EffectSpec, FxChain, Project
from backend.project.session import Session
from backend.project.timeline import (
    TimelineClip,
    TimelineKeyframe,
    TimelinePlacement,
    TimelineProblem,
    TimelineReaction,
    TimelineSource,
    TimelineState,
)

SRC = "a" * 12
CLIP = "c" * 12


def source(missing: bool = False) -> TimelineSource:
    return TimelineSource(
        id=SRC,
        external=False,
        fps_num=60,
        fps_den=1,
        fps=60.0,
        width=2560,
        height=1440,
        duration_ms=60_000,
        file_missing=missing,
    )


def tclip(missing: bool = False, cid: str = CLIP, start: int = 0) -> TimelineClip:
    return TimelineClip(
        id=cid,
        position=0,
        source_id=SRC,
        start_ms=start,
        end_ms=start + 10_000,
        duration_ms=10_000,
        in_ms=0,
        out_ms=10_000,
        speed=1.0,
        overlay=True,
        source=source(missing),
    )


def placed(
    pid: str,
    start: int | None = 1000,
    *,
    take: str | None = "t",
    orphaned: bool = False,
    overflow: int = 0,
    allow: bool = False,
    text: str = "hello there",
) -> TimelinePlacement:
    return TimelinePlacement(
        id=pid,
        line_id="l" + pid,
        line_text=text,
        allow_overlap=allow,
        take_id=take,
        duration_ms=500,
        start_ms=start,
        end_ms=None if start is None else start + 500,
        anchor_clip_id=CLIP,
        anchor_source_ms=0,
        orphaned=orphaned,
        overflow_ms=overflow,
    )


def project(**kw: Any) -> Project:
    return Project(name="Rack", **kw)


def kinds(report: PreflightReport) -> list[tuple[str, str]]:
    return [(i.severity, i.kind) for i in report.issues]


def test_a_clean_project_is_ok() -> None:
    report = preflight(project(), TimelineState(clips=[tclip()], placements=[placed("p")]))
    assert report.ok and report.issues == []
    assert (report.error_count, report.warning_count) == (0, 0)


def test_no_clips_and_tools_block() -> None:
    report = preflight(project(), TimelineState(), tools_problem="ffmpeg was not found")
    assert kinds(report) == [("error", "tools"), ("error", "no_clips")]
    assert not report.ok and report.error_count == 2


def test_a_missing_source_is_reported_once_with_its_time() -> None:
    state = TimelineState(clips=[tclip(True), tclip(True, cid="d" * 12, start=10_000)])
    report = preflight(project(), state)
    assert kinds(report) == [("error", "source_missing")]
    assert report.issues[0].item_id == SRC and report.issues[0].t_ms == 0


def test_an_invalid_voice_chain_blocks() -> None:
    bad = FxChain.model_construct(**{**FxChain().model_dump(), "eq_bass_db": 99.0})
    report = preflight(
        project().model_copy(update={"fx_chain": bad}), TimelineState(clips=[tclip()])
    )
    assert kinds(report) == [("error", "fx_chain_invalid")]


def test_an_unknown_clip_effect_blocks_and_a_registered_one_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clip = Clip(
        id=CLIP, source_id=SRC, in_ms=0, out_ms=10_000, effects=[EffectSpec(type="wobble")]
    )
    proj = project(clips=[clip])
    state = TimelineState(clips=[tclip()])
    assert kinds(preflight(proj, state)) == [("error", "clip_effect_unknown")]
    monkeypatch.setattr(clipeffects, "REGISTRY", {})
    clipeffects.register(ClipEffect("wobble", "Wobble", lambda params: "hflip"))
    assert preflight(proj, state).ok
    assert clipeffects.video_filter_for("wobble", {}) == "hflip"
    with pytest.raises(ValueError, match="already registered"):
        clipeffects.register(ClipEffect("wobble", "Wobble", lambda params: "hflip"))


def test_voice_warnings_and_the_missing_take_error() -> None:
    state = TimelineState(
        clips=[tclip()],
        placements=[
            placed("o", orphaned=True),
            placed("n", None),
            placed("q", take=None),
            placed("m", take="gone"),
            placed("v", overflow=250),
            placed("a", overflow=250, allow=True),
        ],
    )
    report = preflight(project(), state, missing_take_ids={"gone"})
    assert kinds(report) == [
        ("warning", "orphan_placement"),
        ("warning", "placement_off_timeline"),
        ("warning", "no_take"),
        ("error", "take_file_missing"),
        ("warning", "overflow"),
    ]
    assert '"hello there"' in report.issues[0].message
    assert "250 ms" in report.issues[4].message
    assert report.issues[4].t_ms == 1000


def test_long_line_text_is_shortened() -> None:
    state = TimelineState(clips=[tclip()], placements=[placed("q", take=None, text="x " * 60)])
    message = preflight(project(), state).issues[0].message
    assert "…" in message and len(message) < 90


def test_avatar_orphans_and_art_state() -> None:
    key = TimelineKeyframe(
        id="k",
        lane_id="x",
        value=0.5,
        interpolation="smooth",
        t_ms=None,
        anchor_clip_id=CLIP,
        anchor_source_ms=0,
        orphaned=True,
    )
    reaction = TimelineReaction(
        id="r",
        type="hop",
        intensity=1,
        duration_ms=500,
        t_ms=None,
        anchor_clip_id=CLIP,
        anchor_source_ms=0,
        orphaned=True,
    )
    state = TimelineState(clips=[tclip()], keyframes=[key, key], reactions=[reaction])
    report = preflight(project(), state, art_status="folder_missing", art_problem="not found")
    assert kinds(report) == [
        ("warning", "orphan_keyframes"),
        ("warning", "orphan_reactions"),
        ("warning", "no_avatar"),
    ]
    assert report.issues[0].message.startswith("2 avatar keys")
    assert report.issues[1].message.startswith("1 reaction ")
    assert "(not found)" in report.issues[2].message
    assert report.ok
    fallback = preflight(project(), TimelineState(clips=[tclip()]), art_warnings=["smile lacks ciom"])
    assert kinds(fallback) == [("warning", "art_warning")]


def test_reference_problems_and_other_tracks() -> None:
    problems = [
        TimelineProblem(kind="clip_missing_source", owner_id="c", missing_id="s", message="m1"),
        TimelineProblem(kind="take_missing_line", owner_id="t", missing_id="l", message="m2"),
    ]
    state = TimelineState(clips=[tclip()], problems=problems, other_track_clips=2)
    report = preflight(project(), state)
    assert kinds(report) == [
        ("warning", "other_tracks"),
        ("error", "reference_clip_missing_source"),
        ("warning", "reference_take_missing_line"),
    ]
    assert report.issues[0].message.startswith("2 clips")


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def test_session_and_endpoint(tmp_path: Path) -> None:
    session = Session(probe=fake_probe)
    session.new_project(str(tmp_path), "Rack")
    report = session.export_preflight(tools_problem=None)
    assert ("error", "no_clips") in kinds(report)
    assert ("warning", "no_avatar") in kinds(report)
    client = TestClient(create_app(session=session, export_tools=lambda: "no ffmpeg here"))
    body = client.get("/api/export/preflight").json()
    assert body["ok"] is False
    assert body["issues"][0] == {
        "severity": "error",
        "kind": "tools",
        "message": "no ffmpeg here",
        "item_id": None,
        "t_ms": None,
    }


def test_endpoint_without_a_project() -> None:
    client = TestClient(create_app(session=Session(probe=fake_probe), export_tools=lambda: None))
    assert client.get("/api/export/preflight").status_code == 400


def test_encoder_problem_reports_a_missing_ffmpeg(tmp_path: Path) -> None:
    missing = tmp_path / "ffmpeg.exe"
    assert "not found" in (encoder_problem(missing) or "")
    args = nvenc_probe_args(missing)
    assert args[0] == str(missing) and "h264_nvenc" in args


REAL_FFMPEG = Path(__file__).resolve().parents[1] / "bin" / "ffmpeg.exe"


@pytest.mark.skipif(not REAL_FFMPEG.is_file(), reason="bin/ffmpeg.exe is not installed")
def test_the_real_ffmpeg_opens_nvenc() -> None:
    assert encoder_problem(REAL_FFMPEG, refresh=True) is None
