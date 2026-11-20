"""Final render (M6-5): filter text and arguments, then real ffmpeg runs on generated
footage with an avatar and a voice (skipped without ``bin/ffmpeg.exe``)."""

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import soundfile
from PIL import Image

from backend.avatar.art import parse_art
from backend.avatar.track import FrameTrack
from backend.export.compositor import Compositor, SpriteBank
from backend.export.editgraph import OutputFormat, build_edit_graph, sample_count
from backend.export.errors import ExportCancelled, ExportError
from backend.export.pipeline import ExportInputs, ExportOptions, run_export
from backend.export.runner import (
    EDITED_NAME,
    FINAL_NAME,
    final_args,
    final_filters,
    first_clip_input,
    make_plan,
    parse_progress,
    run_render,
)
from backend.export.voicetrack import PROCESSED_NAME, RAW_NAME
from backend.project.schema import Clip, Project, Source
from backend.project.session import Session
from backend.project.timeline import TimelineClip, TimelinePlacement, TimelineState

RED, BLUE = "1" * 12, "2" * 12
FMT = OutputFormat(1920, 1080, Fraction(60))


def project(game_db: float = 0.0) -> Project:
    return Project(
        name="t",
        game_audio_db=game_db,
        sources=[
            Source(id=RED, path="footage/red.mkv", duration_ms=2000, fps_num=60, width=1280, height=720, audio_tracks=1),
            Source(id=BLUE, path="footage/blue.mp4", duration_ms=2000, fps_num=30, width=640, height=480),
        ],
        clips=[
            Clip(id="a" * 12, source_id=RED, in_ms=0, out_ms=1000),
            Clip(id="b" * 12, source_id=BLUE, in_ms=0, out_ms=2000, speed=2.0),
            Clip(id="c" * 12, source_id=RED, in_ms=500, out_ms=1000, speed=0.5),
        ],
    )


def avatar_track() -> FrameTrack:
    n = 91  # 3 s at 30 fps, plus the last frame
    return FrameTrack(
        version="t", fps=30, duration_ms=3000, frame_count=n, height_fraction=0.5,
        sprites=["a/oicm"], sprite_runs=[[0, -1], [45, 0]],  # appears at 1.5 s
        x=[0.5] * n, y=[1.0] * n, scale=[1.0] * n, rotation=[0.0] * n, squash=[0.0] * n,
    )  # fmt: skip


def compositor(tmp_path: Path) -> Compositor:
    sprite = tmp_path / "green.png"
    Image.new("RGBA", (100, 200), (0, 255, 0, 255)).save(sprite)
    return Compositor(avatar_track(), SpriteBank({"a/oicm": sprite}, 540), 1920, 1080)


def test_filters_with_and_without_avatar() -> None:
    graph = build_edit_graph(project(-6), {RED: Path("r.mkv"), BLUE: Path("b.mp4")}, FMT, first_input=2)
    filters = final_filters(graph, FMT, with_avatar=True, game_db=-6)
    assert filters[: len(graph.filters)] == graph.filters
    tail = filters[len(graph.filters) :]
    assert tail[0] == "[vedit]split=2[vmain][vedit_out]"
    assert tail[2] == "[0:v]format=rgba[avatar]"
    # M8-2: lanes under the avatar (none here), the avatar, lanes over it (none).
    assert tail[3] == "[vmain]null[vunder]"
    assert tail[4] == "[vunder][avatar]overlay=0:0:format=auto[vavatar]"
    assert tail[5] == "[vavatar]null[vover]"
    assert tail[6] == "[vover]format=yuv420p,trim=end_frame=180[vfinal]"
    assert tail[7] == "[agame]volume=-6.00dB[game]"
    assert tail[8].startswith("[1:a:0]aresample=48000,pan=stereo|c0=c0|c1=c0,")
    assert "atrim=end_sample=144000[voice]" in tail[8]
    assert "amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.891251:level=disabled" in tail[9]
    plain = final_filters(graph, FMT, with_avatar=False, game_db=0)
    assert "[vunder]null[vavatar]" in plain and plain[-2].startswith("[0:a:0]")
    assert first_clip_input(True) == 2 and first_clip_input(False) == 1


def test_args_order(tmp_path: Path) -> None:
    plan = make_plan(
        project(), {RED: Path("r.mkv"), BLUE: Path("b.mp4")}, FMT,
        ffmpeg=Path("ff.exe"), voice_wav=tmp_path / "v.wav", avatar=compositor(tmp_path), out_dir=tmp_path,
    )  # fmt: skip
    args = final_args(plan)
    i = args.index("pipe:0")
    assert args[i - 9 : i + 1] == ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", "1920x1080", "-r", "30", "-i", "pipe:0"]
    assert args[i + 1 : i + 3] == ["-i", str(tmp_path / "v.wav")]
    assert args[i + 3 : i + 9] == ["-ss", "0.000", "-t", "1.000", "-i", "r.mkv"]
    assert args[-1] == str(tmp_path / EDITED_NAME) and str(tmp_path / FINAL_NAME) in args
    assert "[2:v:0]" in plan.graph.filters[0]


def test_overlay_output_is_a_third_output(tmp_path: Path) -> None:
    plan = make_plan(
        project(), {RED: Path("r.mkv"), BLUE: Path("b.mp4")}, FMT, ffmpeg=Path("ff.exe"),
        voice_wav=tmp_path / "v.wav", avatar=compositor(tmp_path), out_dir=tmp_path, overlay_frames=91,
    )  # fmt: skip
    args = final_args(plan)
    assert args[-1] == str(tmp_path / "avatar_overlay" / "frame_%06d.png")
    i = args.index("[overlay_out]")
    assert args[i + 1 : i + 9] == ["-fps_mode", "passthrough", "-c:v", "png", "-pred", "sub", "-compression_level", "1"]
    filters = final_filters(plan.graph, FMT, with_avatar=True, game_db=0, overlay_frames=91)
    assert "[0:v]format=rgba,split=2[avatar][avpng]" in filters
    assert "[avpng]trim=end_frame=91[overlay_out]" in filters
    no_avatar = make_plan(
        project(), {RED: Path("r.mkv"), BLUE: Path("b.mp4")}, FMT, ffmpeg=Path("ff.exe"),
        voice_wav=tmp_path / "v.wav", avatar=None, out_dir=tmp_path, overlay_frames=91,
    )  # fmt: skip
    assert no_avatar.overlay_frames == 0 and "[overlay_out]" not in final_args(no_avatar)


def test_parse_progress() -> None:
    assert parse_progress("out_time_us=1500000\n") == ("out_time_us", "1500000")
    assert parse_progress("progress=end") == ("progress", "end")
    assert parse_progress("garbage") is None


def fake_probe(path: Path) -> dict[str, Any]:
    raise AssertionError("ffprobe should not run in these tests")


def test_session_export_inputs(tmp_path: Path) -> None:
    session = Session(probe=fake_probe)
    session.new_project(str(tmp_path), "Rack")
    stack = session._stack
    assert stack is not None
    stack.project.sources.extend(project().sources)
    stack.project.clips.extend(project().clips)
    inputs = session.export_inputs()
    assert [c.id for c in inputs.timeline.clips] == ["a" * 12, "b" * 12, "c" * 12]
    assert inputs.source_paths[RED] == tmp_path / "Rack" / "footage" / "red.mkv"
    assert inputs.track is None and inputs.art is None and inputs.art_root is None
    inputs.project.clips.clear()  # a snapshot: the open project is untouched
    assert len(session.export_inputs().project.clips) == 3


# --- real ffmpeg -------------------------------------------------------------------

BIN = Path(__file__).resolve().parents[1] / "bin"
FFMPEG, FFPROBE = BIN / "ffmpeg.exe", BIN / "ffprobe.exe"
needs_ffmpeg = pytest.mark.skipif(
    not (FFMPEG.is_file() and FFPROBE.is_file()), reason="bin/ffmpeg.exe is not installed"
)


def run(args: list[str]) -> bytes:
    result = subprocess.run(args, capture_output=True, timeout=180, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-2000:]
    return result.stdout


def footage(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    red, blue = folder / "red.mkv", folder / "blue.mp4"
    run([
        str(FFMPEG), "-hide_banner", "-y", "-f", "lavfi", "-i", "color=c=red:s=1280x720:r=60:d=2",
        "-f", "lavfi", "-i", "sine=f=220:sample_rate=48000:d=2", "-c:v", "libx264", "-g", "30",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(red),
    ])  # fmt: skip
    run([
        str(FFMPEG), "-hide_banner", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x480:r=30:d=2",
        "-c:v", "libx264", "-g", "15", "-pix_fmt", "yuv420p", str(blue),
    ])  # fmt: skip
    return {RED: red, BLUE: blue}


def voice_wav(path: Path) -> Path:
    """3 s at 24 kHz: a 1 kHz tone from 1.2 s to 1.8 s."""
    audio = np.zeros(72_000, dtype=np.float32)
    t = np.arange(14_400) / 24_000
    audio[28_800 : 28_800 + 14_400] = 0.5 * np.sin(2 * np.pi * 1000 * t)
    soundfile.write(str(path), audio, 24_000, subtype="FLOAT")
    return path


def frames_of(path: Path) -> np.ndarray:
    raw = run([
        str(FFMPEG), "-v", "error", "-i", str(path), "-vf", "scale=192:108:flags=neighbor",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ])  # fmt: skip
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 108, 192, 3).astype(int)


def pcm_of(path: Path) -> np.ndarray:
    raw = run([str(FFMPEG), "-v", "error", "-i", str(path), "-ac", "1", "-f", "f32le", "-"])
    return np.frombuffer(raw, dtype=np.float32)


def name(px: np.ndarray) -> str:
    r, g, b = px
    for label, (cr, cg, cb) in {"red": (255, 0, 0), "green": (0, 255, 0), "blue": (0, 0, 255)}.items():
        if abs(r - cr) < 70 and abs(g - cg) < 70 and abs(b - cb) < 70:
            return label
    return f"{r},{g},{b}"


def band(pcm: np.ndarray, a_ms: int, b_ms: int, hz: float | None = None) -> float:
    part = pcm[sample_count(a_ms) : sample_count(b_ms)].astype(np.float64)
    if hz is None:
        return float(np.sqrt(np.mean(part**2)))
    t = np.arange(part.size) / 48_000
    return float(abs(np.mean(part * np.exp(-2j * np.pi * hz * t))) * 2)  # amplitude at hz


@needs_ffmpeg
def test_real_render_overlays_on_twos_and_mixes(tmp_path: Path) -> None:
    paths = footage(tmp_path / "footage")
    out = tmp_path / "out dir"
    out.mkdir()
    plan = make_plan(
        project(-6.0), paths, FMT, ffmpeg=FFMPEG, voice_wav=voice_wav(out / "voice.wav"),
        avatar=compositor(tmp_path), out_dir=out,
    )  # fmt: skip
    seen: list[float] = []
    report = run_render(plan, progress=seen.append)
    assert report.frames == 180 and report.avatar_frames == 91
    assert seen and seen[-1] == 1.0

    probe = json.loads(run([
        str(FFPROBE), "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(plan.final_path),
    ]))  # fmt: skip
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"], video["r_frame_rate"], int(video["nb_read_frames"])) == (
        1920, 1080, "60/1", 180,
    )  # fmt: skip

    final, edited = frames_of(plan.final_path), frames_of(plan.edited_path)
    centre = (80, 96)  # inside the avatar box (bottom centre, half the frame high)
    # Output frame n shows avatar frame floor(n / 2): it appears exactly at frame 90 (1.5 s).
    assert [name(final[k][centre]) for k in (30, 89, 90, 96, 150)] == ["red", "blue", "green", "green", "green"]
    assert [name(edited[k][centre]) for k in (30, 89, 90, 96, 150)] == ["red", "blue", "blue", "blue", "red"]
    assert name(final[96][(10, 96)]) == "blue"  # outside the avatar box

    game_final, game_edit = pcm_of(plan.final_path), pcm_of(plan.edited_path)
    ratio = band(game_final, 200, 800, 220) / band(game_edit, 200, 800, 220)
    assert ratio == pytest.approx(10 ** (-6 / 20), rel=0.05)  # game audio at -6 dB
    assert band(game_final, 1300, 1700, 1000) > 0.3  # the voice is in the final mix
    assert band(game_edit, 1300, 1700, 1000) < 0.01  # and not in the edited video
    assert np.max(np.abs(game_final)) < 0.95  # limited


@needs_ffmpeg
def test_real_render_without_avatar_and_cancel(tmp_path: Path) -> None:
    paths = footage(tmp_path / "footage")
    out = tmp_path / "out"
    out.mkdir()
    plan = make_plan(
        project(), paths, FMT, ffmpeg=FFMPEG, voice_wav=voice_wav(out / "voice.wav"), avatar=None, out_dir=out,
    )  # fmt: skip
    assert run_render(plan).avatar_frames == 0
    assert name(frames_of(plan.final_path)[96][(80, 96)]) == "blue"
    stopping = make_plan(
        project(), paths, FMT, ffmpeg=FFMPEG, voice_wav=out / "voice.wav",
        avatar=compositor(tmp_path), out_dir=tmp_path / "cancel",
    )  # fmt: skip
    calls = [0]

    def stop() -> bool:
        calls[0] += 1
        return calls[0] > 1

    with pytest.raises(ExportCancelled):
        run_render(stopping, should_stop=stop)


@needs_ffmpeg
def test_ffmpeg_failure_is_reported_with_its_log(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    plan = make_plan(
        project(), {RED: tmp_path / "missing.mkv", BLUE: tmp_path / "missing.mp4"}, FMT,
        ffmpeg=FFMPEG, voice_wav=voice_wav(out / "voice.wav"), avatar=None, out_dir=out,
    )  # fmt: skip
    with pytest.raises(ExportError, match="ffmpeg failed"):
        run_render(plan)


@needs_ffmpeg
def test_pipeline_writes_voice_then_renders(tmp_path: Path) -> None:
    paths = footage(tmp_path / "footage")
    take = voice_wav(tmp_path / "take.wav")
    clips = [TimelineClip(
        id="a" * 12, position=0, source_id=RED, start_ms=0, end_ms=3000, duration_ms=3000,
        in_ms=0, out_ms=1000, speed=1.0, overlay=True, source=None,
    )]  # fmt: skip
    placement = TimelinePlacement(
        id="p", line_id="l", line_text="hello", allow_overlap=False, take_id="t", duration_ms=3000,
        start_ms=0, end_ms=3000, anchor_clip_id="a" * 12, anchor_source_ms=0, orphaned=False,
    )  # fmt: skip
    inputs = ExportInputs(
        project=project(), timeline=TimelineState(clips=clips, placements=[placement], duration_ms=3000),
        source_paths=paths, track=avatar_track(), art=parse_art({"01_a": ["01a_a_oicm.png"]}),
        art_root=tmp_path / "art",
    )  # fmt: skip
    sprite = tmp_path / "art" / "01_a" / "01a_a_oicm.png"
    sprite.parent.mkdir(parents=True)
    Image.new("RGBA", (100, 200), (0, 255, 0, 255)).save(sprite)
    stages: list[tuple[str, float]] = []
    result = run_export(
        inputs, tmp_path / "bundle", ffmpeg=FFMPEG,
        processed_for=lambda cue: take,
        raw_for=lambda cue: (soundfile.read(str(take), dtype="float32")[0], 24_000),
        options=ExportOptions(include_overlay=True, include_raw_links=True),
        report=lambda stage, fraction: stages.append((stage, fraction)),
    )  # fmt: skip
    assert result.with_avatar and result.voice.lines == 1 and result.render.frames == 180
    assert result.overlay_frames == 91 and result.raw.linked == ["red.mkv", "blue.mp4"]
    bundle = tmp_path / "bundle"
    for file in (PROCESSED_NAME, RAW_NAME, FINAL_NAME, EDITED_NAME, "project.json", "export.json"):
        assert (bundle / file).is_file(), file
    assert len(list((bundle / "avatar_overlay").glob("frame_*.png"))) == 91
    with Image.open(bundle / "avatar_overlay" / "frame_000045.png") as png:  # appears at 1.5 s
        assert png.mode == "RGBA" and png.size == (1920, 1080)
        assert png.getpixel((960, 800)) == (0, 255, 0, 255) and png.getpixel((10, 10))[3] == 0
    with Image.open(bundle / "avatar_overlay" / "frame_000044.png") as png:
        assert png.getextrema()[3] == (0, 0)  # nothing yet: fully transparent
    assert "91 frames, 30 fps" in (bundle / "avatar_overlay" / "README.txt").read_text(encoding="utf-8")
    assert (bundle / "video_raw" / "red.mkv").stat().st_nlink == 2
    manifest = json.loads((bundle / "export.json").read_text(encoding="utf-8"))
    assert manifest["video"]["frames"] == 180 and manifest["video"]["fps"] == "60/1"
    assert manifest["ffmpeg"].startswith("ffmpeg version")
    assert set(manifest["seconds"]) == {"voice", "render", "finish", "total"}
    names = [s for s, _ in stages]
    assert names[0] == "voice" and "render" in names and names[-1] == "done"
    fractions = [f for _, f in stages]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    with pytest.raises(ExportError, match="not empty"):
        run_export(inputs, bundle, ffmpeg=FFMPEG, processed_for=lambda c: take, raw_for=lambda c: (np.zeros(1), 24_000))


@needs_ffmpeg
def test_pipeline_with_a_limit_exports_only_the_start(tmp_path: Path) -> None:
    paths = footage(tmp_path / "footage")
    take = voice_wav(tmp_path / "take.wav")
    session = Session(probe=fake_probe)
    session.new_project(str(tmp_path), "Rack")
    stack = session._stack
    assert stack is not None
    stack.project.sources.extend(project().sources)
    stack.project.clips.extend(project().clips)
    inputs = session.export_inputs()
    inputs = ExportInputs(
        project=inputs.project, timeline=inputs.timeline, source_paths=paths,
        track=None, art=None, art_root=None,
    )  # fmt: skip
    result = run_export(
        inputs, tmp_path / "short", ffmpeg=FFMPEG, processed_for=lambda c: take,
        raw_for=lambda c: (np.zeros(1, dtype=np.float32), 24_000),
        options=ExportOptions(limit_ms=1500, include_raw_links=False),
    )  # fmt: skip
    assert result.render.frames == 90 and not result.with_avatar and result.overlay_frames == 0
    assert not (tmp_path / "short" / "video_raw").exists()
    assert soundfile.info(str(tmp_path / "short" / PROCESSED_NAME)).frames == 36_000  # 1.5 s


@needs_ffmpeg
def test_real_render_draws_lane_clips_past_the_footage(tmp_path: Path) -> None:
    """M8-2: a yellow still on Video 2 runs past the 3 s footage to 4 s; a magenta
    recording with an 880 Hz tone plays on Video 3 at 2 to 2.5 s."""
    from backend.export.lanes import program_end_ms
    from backend.project.schema import ImageFile, LaneClip, VideoLane

    paths = footage(tmp_path / "footage")
    pink = tmp_path / "footage" / "pink.mp4"
    run([
        str(FFMPEG), "-hide_banner", "-y", "-f", "lavfi", "-i", "color=c=magenta:s=640x360:r=30:d=2",
        "-f", "lavfi", "-i", "sine=f=880:sample_rate=48000:d=2", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(pink),
    ])  # fmt: skip
    title = tmp_path / "title.png"
    Image.new("RGBA", (400, 400), (255, 255, 0, 255)).save(title)
    pink_id, img_id, v2, v3 = "5" * 12, "6" * 12, "7" * 12, "8" * 12
    proj = project()
    proj.sources.append(
        Source(id=pink_id, path="footage/pink.mp4", duration_ms=2000, fps_num=30, width=640, height=360, audio_tracks=1)
    )  # fmt: skip
    proj.image_files.append(
        ImageFile(id=img_id, path="images/title.png", name="title.png", size_bytes=1, width=400, height=400)
    )  # fmt: skip
    proj.video_lanes = [VideoLane(id=v2, name="Video 2"), VideoLane(id=v3, name="Video 3")]
    proj.lane_clips = [
        LaneClip(id="d" * 12, lane_id=v2, image_id=img_id, timeline_ms=500, out_ms=3500, x=0.15, y=0.2, scale=0.3),
        LaneClip(id="e" * 12, lane_id=v3, source_id=pink_id, timeline_ms=2000, in_ms=0, out_ms=500, x=0.85, y=0.2, scale=0.25),
    ]  # fmt: skip
    total = program_end_ms(proj)
    assert total == 4000
    out = tmp_path / "out"
    out.mkdir()
    plan = make_plan(
        proj, {**paths, pink_id: pink}, FMT, ffmpeg=FFMPEG, voice_wav=voice_wav(out / "voice.wav"),
        avatar=None, out_dir=out, image_paths={img_id: title}, total_ms=total,
    )  # fmt: skip
    report = run_render(plan)
    assert report.frames == 240

    final = frames_of(plan.final_path)
    assert final.shape[0] == 240
    yellow, pink_px, footage_px = (21, 28), (21, 163), (80, 96)  # (row, col) at 192 x 108

    def is_yellow(px: np.ndarray) -> bool:
        return px[0] > 180 and px[1] > 180 and px[2] < 90

    def is_pink(px: np.ndarray) -> bool:
        return px[0] > 180 and px[1] < 90 and px[2] > 180

    assert not is_yellow(final[20][yellow])  # 0.33 s: before the still
    assert is_yellow(final[45][yellow]) and name(final[45][footage_px]) == "red"
    assert is_pink(final[135][pink_px]) and not is_pink(final[160][pink_px])  # 2.25 s / 2.67 s
    assert is_yellow(final[210][yellow])  # 3.5 s: past the footage, the still stays
    assert final[210][footage_px].sum() < 60  # and the frame under it is black
    assert is_yellow(final[239][yellow])  # the still lasts to the last frame (4 s)
    # Frame-exact edges (60 fps): the still from frame 30, the recording 120 to 149.
    assert [is_yellow(final[k][yellow]) for k in (29, 30)] == [False, True]
    assert [is_pink(final[k][pink_px]) for k in (119, 120, 149, 150)] == [False, True, True, False]

    pcm = pcm_of(plan.final_path)
    assert abs(pcm.size - sample_count(4000)) <= 2048
    assert band(pcm, 2050, 2450, 880) > 0.03  # the lane clip's sound is in the mix
    assert band(pcm, 1000, 1900, 880) < 0.005
    assert band(pcm, 3100, 3900) < 0.01  # silence past the footage
