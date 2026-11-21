"""Keyed image clips in the export (keyframes task, step 8).

The real render (skipped without ``bin/ffmpeg.exe``) checks every output frame against
``keyed_frames``, which is ``clip_values_at`` (the preview's evaluation, see
``tests/test_clip_key_eval.py``) plus ``pip_rect``: preview and export agree frame by frame.
"""

import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from backend.export.editgraph import OutputFormat
from backend.export.lanes import (
    PipRect,
    build_lane_graph,
    keyed_chain,
    keyed_frames,
    overlay_steps,
)
from backend.project.schema import ClipKey, ImageFile, LaneClip, Project, VideoLane

FFMPEG = Path(__file__).resolve().parents[1] / "bin" / "ffmpeg.exe"
needs_ffmpeg = pytest.mark.skipif(not FFMPEG.is_file(), reason="bin/ffmpeg.exe is not installed")

FMT = OutputFormat(320, 180, Fraction(10))
LANE, IMG, CLIP = "a" * 12, "b" * 12, "c" * 12


def key(n: int, prop: str, t: int, value: float, interp: str = "linear", strength: float = 1.0) -> ClipKey:
    return ClipKey(
        id=f"{n:012x}", prop=prop, t_ms=t, value=value, interpolation=interp, ease_strength=strength
    )  # type: ignore[arg-type]


def keyed_project(keys: list[ClipKey], start_ms: int = 500, length_ms: int = 2000) -> Project:
    return Project(
        name="t",
        image_files=[ImageFile(id=IMG, path="images/red.png", name="red.png", size_bytes=1, width=40, height=40)],
        video_lanes=[VideoLane(id=LANE, name="Video 2")],
        lane_clips=[
            LaneClip(id=CLIP, lane_id=LANE, image_id=IMG, timeline_ms=start_ms, out_ms=length_ms, x=0.5, y=0.5, scale=0.25, keys=keys)
        ],
    )  # fmt: skip


MOVING = [
    key(1, "x", 0, 0.0, "ease_in_out"),
    key(2, "x", 2000, 1.1),
    key(3, "y", 0, 0.2, "ease_out", 2.0),
    key(4, "y", 1500, 0.9),
    key(5, "scale", 0, 0.1, "ease_in", 1.5),
    key(6, "scale", 2000, 0.6),
    key(7, "opacity", 0, 0.0),
    key(8, "opacity", 1000, 1.0, "hold"),
    key(9, "opacity", 1500, 0.4),
]


def test_frames_follow_the_keys() -> None:
    clip = keyed_project(MOVING).lane_clips[0]
    frames = keyed_frames(clip, 40, 40, FMT, start_frame=5, frames=20)
    assert frames[0].opacity == 0.0 and frames[0].rect.width == round(180 * 0.1)
    assert frames[5].opacity == pytest.approx(0.5)  # 1000 ms: half way up the fade
    assert frames[12].opacity == 1.0 and frames[15].opacity == pytest.approx(0.4)  # held, then jumped
    assert frames[-1].rect.left > frames[0].rect.left


def test_chain_sends_only_changes_and_starts_at_frame_0() -> None:
    clip = keyed_project([key(1, "opacity", 0, 0.0), key(2, "opacity", 200, 1.0)]).lane_clips[0]
    frames = keyed_frames(clip, 40, 40, FMT, 5, 5)
    chain = keyed_chain(frames, FMT, "7")
    assert chain[0] == "format=rgba"
    assert chain[1] == (
        "sendcmd=c='0.050000 colorchannelmixer@m7 aa 0.5000;0.150000 colorchannelmixer@m7 aa 1.0000'"
    )
    assert "scale@s7=w=45:h=45:eval=frame" in chain and "colorchannelmixer@m7=aa=0.0000" in chain
    # 45 px picture centred: left 160 - 22.5 rounds to 138, so the window starts at 320 - 138.
    assert chain[-1] == "crop@c7=w=320:h=180:x=182:y=112:exact=1"


def test_graph_places_a_keyed_clip_at_0_0_and_leaves_plain_clips_alone() -> None:
    project = keyed_project(MOVING)
    project.lane_clips.append(
        LaneClip(id="d" * 12, lane_id=LANE, image_id=IMG, timeline_ms=3000, out_ms=500, opacity=0.5)
    )
    graph = build_lane_graph(project, {}, {IMG: Path("C:/p/red.png")}, FMT, 4000, first_input=1)
    keyed, plain = graph.layers
    assert (keyed.left, keyed.top) == (0, 0)
    assert "sendcmd=" in graph.filters[0] and "crop@c0=" in graph.filters[0]
    assert "sendcmd" not in graph.filters[1] and "colorchannelmixer=aa=0.5000" in graph.filters[1]
    assert (plain.left, plain.top) == (70, 0)  # full size (scale 1), centred


@needs_ffmpeg
def test_real_render_matches_the_evaluation_frame_by_frame(tmp_path: Path) -> None:
    red = tmp_path / "red.png"
    Image.new("RGBA", (40, 40), (255, 0, 0, 255)).save(red)
    project = keyed_project(MOVING)
    total_ms = 3000
    graph = build_lane_graph(project, {}, {IMG: red}, FMT, total_ms, first_input=1)
    script = tmp_path / "graph.txt"
    filters = [*graph.filters, *overlay_steps("0:v", graph.layers, "out", FMT, "l")]
    script.write_text(";".join(filters) + "\n", encoding="utf-8")
    raw = subprocess.run(
        [
            str(FFMPEG), "-v", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=320x180:r=10:d={total_ms / 1000}",
            *graph.input_args(),
            "-/filter_complex", str(script), "-map", "[out]",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        check=True,
        capture_output=True,
    ).stdout  # fmt: skip
    video = np.frombuffer(raw, np.uint8).reshape(-1, 180, 320, 3)
    assert len(video) == 30
    layer = graph.layers[0]
    expected = keyed_frames(project.lane_clips[0], 40, 40, FMT, layer.start_frame, layer.end_frame - layer.start_frame)
    checked = 0
    for n, frame in enumerate(video):
        red_px = frame[:, :, 0].astype(int)
        if not layer.start_frame <= n < layer.end_frame:
            assert red_px.max() == 0, n  # nothing before or after the clip
            continue
        want = expected[n - layer.start_frame]
        r: PipRect = want.rect
        mask = np.zeros((180, 320), bool)
        mask[max(0, r.top) : max(0, r.top + r.height), max(0, r.left) : max(0, r.left + r.width)] = True
        level = round(255 * want.opacity)
        if level == 0:
            assert red_px.max() == 0, n
        else:
            assert (red_px[mask] - level).__abs__().max() <= 2, n  # inside: the faded red
            assert red_px[~mask].max() == 0, n  # outside: untouched
        checked += 1
    assert checked == 20
