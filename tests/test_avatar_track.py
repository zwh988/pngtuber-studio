"""Solver input from the project, avatar_version, frame track, preview sprites and
their routes (M5-6 backend, S10a)."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app import create_app
from backend.avatar.art import parse_art
from backend.avatar.envelope import Envelope
from backend.avatar.preview import ensure_preview
from backend.avatar.solver import build_solver
from backend.avatar.track import (
    TRACK_FPS,
    build_frame_track,
    build_input,
    frame_time,
    input_version,
    sprite_path_for_key,
)
from backend.project.avatar_commands import AddKeyframe, AddReaction
from backend.project.edit_ops import AddPlacementOp
from backend.project.line_ops import AddLineOp
from backend.project.schema import Anchor, Clip, Line, Placement, Project, Source
from backend.project.session import Session
from backend.project.timeline import build_timeline
from backend.voice.takes import NewTake

SRC, CLIP, LINE, TAKE, PLACE = "1" * 12, "2" * 12, "3" * 12, "4" * 12, "5" * 12
NAMES = ("smile", "cheeky")


def listing() -> dict[str, list[str]]:
    return {
        f"{i:02d}_{n}": [f"{i:02d}{c}_{n}_{s}.png" for c, s in zip("abcd", ("oicm", "oiom", "cicm", "ciom"), strict=True)]
        for i, n in enumerate(NAMES, start=1)
    }


ART = parse_art(listing())
LOUD = Envelope(10, tuple([-20.0] * 100))  # one second of speech


def make_project() -> Project:
    project = Project(
        name="t",
        seed=42,
        sources=[Source(id=SRC, path="footage/a.mkv", duration_ms=60_000, fps_num=30, width=1920, height=1080)],
        clips=[Clip(id=CLIP, source_id=SRC, in_ms=0, out_ms=10_000)],
        lines=[Line(id=LINE, text="hi", active_take_id=TAKE)],
        placements=[Placement(id=PLACE, line_id=LINE, anchor=Anchor(clip_id=CLIP, source_ms=2000))],
    )
    AddKeyframe("expression", 5000, "cheeky").apply(project)
    AddKeyframe("x", 1000, 0.5).apply(project)
    AddReaction("hop", 7000).apply(project)
    return project


def timeline_for(project: Project):
    state = build_timeline(project)
    # The test project has no take record: give the placement a playing take.
    state.placements[0].take_id = TAKE
    return state


def test_input_maps_keys_voices_and_reactions() -> None:
    project = make_project()
    inp = build_input(project, timeline_for(project), {PLACE: LOUD}, ART, {})
    assert inp.duration_ms == 10_000 and inp.seed == 42
    assert [(k.t_ms, k.expression, k.manual) for k in inp.expression_keys] == [(5000, "cheeky", True)]
    assert [(k.t_ms, k.value) for k in inp.lanes["x"]] == [(1000, 0.5)]
    assert [(v.start_ms, len(v.envelope.values)) for v in inp.voices] == [(2000, 100)]
    assert [(r.t_ms, r.type) for r in inp.reactions] == [(7000, "hop")]
    assert inp.default_expression == "smile"


def test_orphans_and_unknown_expressions() -> None:
    project = make_project()
    project.keyframes[0].orphaned = True
    project.reactions[0].orphaned = True
    inp = build_input(project, timeline_for(project), {}, ART, {})
    assert inp.expression_keys == [] and inp.reactions == [] and inp.voices == []
    AddKeyframe("expression", 6000, "angry").apply(project)  # not in the art
    inp = build_input(project, timeline_for(project), {}, ART, {})
    assert [k.expression for k in inp.expression_keys] == ["smile"]


def test_version_changes_exactly_with_the_picture() -> None:
    project = make_project()
    timeline = timeline_for(project)
    a = build_input(project, timeline, {PLACE: LOUD}, ART, {})
    b = build_input(project, timeline, {PLACE: LOUD}, ART, {})
    assert input_version(a, ART) == input_version(b, ART)
    louder = Envelope(10, tuple([-10.0] * 100))
    c = build_input(project, timeline, {PLACE: louder}, ART, {})
    assert input_version(c, ART) != input_version(a, ART)
    project.avatar.scale = 2.0
    d = build_input(project, timeline_for(project), {PLACE: LOUD}, ART, {})
    assert input_version(d, ART) != input_version(a, ART)
    assert input_version(a, None) != input_version(a, ART)


def test_frame_track_matches_the_solver() -> None:
    project = make_project()
    inp = build_input(project, timeline_for(project), {PLACE: LOUD}, ART, {})
    solver = build_solver(inp)
    track = build_frame_track(solver, ART, "v1")
    assert track.fps == TRACK_FPS and track.frame_count == 301
    assert len(track.x) == len(track.y) == len(track.scale) == track.frame_count
    assert track.sprite_runs[0][0] == 0
    runs = track.sprite_runs + [[track.frame_count, -1]]
    for k in (0, 75, 150, 210, 240, 300):
        frame = solver.query(frame_time(k))
        sprite = next(runs[i][1] for i in range(len(runs) - 1) if runs[i][0] <= k < runs[i + 1][0])
        expression, state = track.sprites[sprite].split("/")
        assert expression == frame.expression
        assert state == ("oi" if frame.eyes_open else "ci") + ("om" if frame.mouth_open else "cm")
        assert track.x[k] == round(frame.x, 4)
        assert track.y[k] == round(frame.y, 4)
    assert any(s.endswith("om") for s in track.sprites)  # the mouth opened
    assert {s.split("/")[0] for s in track.sprites} == {"smile", "cheeky"}
    assert build_frame_track(solver, ART, "v1") == track  # deterministic


def test_no_art_draws_nothing() -> None:
    project = make_project()
    inp = build_input(project, timeline_for(project), {}, None, {})
    track = build_frame_track(build_solver(inp), None, "v")
    assert track.sprites == [] and track.sprite_runs == [[0, -1]]


def test_sprite_lookup_by_key() -> None:
    assert sprite_path_for_key(ART, "Cheeky", "CIOM") == "02_cheeky/02d_cheeky_ciom.png"
    assert sprite_path_for_key(ART, "nope", "oicm") is None
    assert sprite_path_for_key(ART, "smile", "xxxx") is None


# ---- preview sprites ----------------------------------------------------------------


def write_png(path: Path, size: tuple[int, int] = (118, 210)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (200, 100, 50, 255)).save(path)


def test_preview_is_downscaled_cached_and_renamed_on_change(tmp_path: Path) -> None:
    src = tmp_path / "art" / "big.png"
    write_png(src, (590, 1048))
    cache = tmp_path / "cache"
    first = ensure_preview(src, cache, height=100)
    with Image.open(first) as image:
        assert image.size == (56, 100) and image.mode == "RGBA"
    assert ensure_preview(src, cache, height=100) == first
    small = tmp_path / "art" / "small.png"
    write_png(small, (20, 40))
    with Image.open(ensure_preview(small, cache, height=100)) as image:
        assert image.size == (20, 40)  # never upscaled
    write_png(src, (590, 1000))
    import os

    os.utime(src, ns=(src.stat().st_atime_ns, src.stat().st_mtime_ns + 10**9))
    assert ensure_preview(src, cache, height=100) != first


# ---- session and routes -------------------------------------------------------------


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def make_art(root: Path) -> Path:
    for folder, files in listing().items():
        for name in files:
            write_png(root / folder / name)
    return root


def open_project(tmp_path: Path) -> Session:
    session = Session(probe=fake_probe)
    session.new_project(str(tmp_path), "Rack")
    stack = session._stack
    assert stack is not None
    stack.project.sources.extend(make_project().sources)
    stack.project.clips.extend(make_project().clips)
    session.set_avatar_folder(str(make_art(tmp_path / "art")))
    return session


def test_track_and_sprite_routes(tmp_path: Path) -> None:
    session = open_project(tmp_path)
    client = TestClient(create_app(session=session))
    track = client.get("/api/avatar/track").json()
    assert track["frame_count"] == 301
    assert track["sprites"] == ["smile/oicm", "smile/cicm"]  # idle: blinks, no voice
    again = client.get("/api/avatar/track").json()
    assert again["version"] == track["version"]
    client.post(
        "/api/timeline/batch",
        json={"label": "k", "ops": [{"op": "key_lane", "lane_id": "scale", "timeline_ms": 0, "value": 2}]},
    )
    changed = client.get("/api/avatar/track").json()
    assert changed["version"] != track["version"] and changed["scale"][0] == 2.0
    sprite = client.get("/media/avatar/smile/oicm")
    assert sprite.status_code == 200 and sprite.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get("/media/avatar/smile/xxxx").status_code == 404
    assert client.get("/media/avatar/..%2F..%2Fproject.json/oicm").status_code == 404


def test_track_mouth_follows_a_placed_take(tmp_path: Path) -> None:
    pytest.importorskip("pedalboard")
    pytest.importorskip("pyloudnorm")
    session = open_project(tmp_path)
    session.edit_lines([AddLineOp(line_id=LINE, text="hello")])
    t = np.arange(24_000) / 24_000
    audio = (0.4 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)  # 1 s of "speech"
    session.add_take(
        NewTake(
            line_id=LINE, seed=1, text="hello", exaggeration=0.5, cfg_weight=0.5,
            voice_profile_id="6" * 12, model_version="t", raw_key="a" * 64, take_id=TAKE,
        ),
        audio,
        24_000,
    )
    session.edit([AddPlacementOp(line_id=LINE, timeline_ms=3000)])
    track = session.avatar_track()
    states = [track.sprites[i] for _, i in track.sprite_runs if i >= 0]
    assert any(s.endswith("om") for s in states)
    open_at = next(k for k, i in track.sprite_runs if i >= 0 and track.sprites[i].endswith("om"))
    assert 3000 <= frame_time(open_at) <= 3200
