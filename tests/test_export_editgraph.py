"""Edit graph (M6-3): pure graph text and counts, then a real ffmpeg run on generated
footage (skipped without ``bin/ffmpeg.exe``)."""

import json
import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from backend.export import clipeffects
from backend.export.clipeffects import ClipEffect
from backend.export.editgraph import (
    AUDIO_LABEL,
    VIDEO_LABEL,
    OutputFormat,
    atempo_chain,
    build_edit_graph,
    edited_video_args,
    frame_count,
    output_format,
    sample_count,
    seconds,
)
from backend.export.errors import ExportError
from backend.project.schema import Clip, EffectSpec, ExportSettings, Project, Source

RED, BLUE, BOOK = "1" * 12, "2" * 12, "3" * 12
FMT = OutputFormat(1920, 1080, Fraction(60))


def project(clips: list[Clip], **kw: object) -> Project:
    return Project(
        name="t",
        sources=[
            Source(id=RED, path="footage/red.mkv", duration_ms=2000, fps_num=60, width=1280, height=720, audio_tracks=1),
            Source(id=BLUE, path="footage/blue.mp4", duration_ms=2000, fps_num=30, width=640, height=480),
            Source(id=BOOK, external=True, path="C:/intro.mp4", duration_ms=2000, fps_num=25, width=1920, height=1080, audio_tracks=1),
        ],
        clips=clips,
        **kw,
    )


def clip(cid: str, source: str, in_ms: int, out_ms: int, speed: float = 1.0, **kw: object) -> Clip:
    return Clip(id=cid * 12, source_id=source, in_ms=in_ms, out_ms=out_ms, speed=speed, **kw)


THREE = [clip("a", RED, 0, 1000), clip("b", BLUE, 0, 2000, 2.0), clip("c", RED, 500, 1000, 0.5)]
PATHS = {RED: Path("C:/my footage/red.mkv"), BLUE: Path("C:/my footage/blue.mp4"), BOOK: Path("C:/intro.mp4")}


def test_seconds_text() -> None:
    assert [seconds(0), seconds(1), seconds(12_345), seconds(-5)] == ["0.000", "0.001", "12.345", "-0.005"]


def test_output_format_matches_the_first_footage_clip() -> None:
    bookend_first = [clip("d", BOOK, 0, 1000, overlay=False), clip("b", BLUE, 0, 1000), clip("a", RED, 0, 1000)]
    fmt = output_format(project(bookend_first))
    assert (fmt.width, fmt.height, fmt.fps, fmt.fps_text) == (1920, 1080, Fraction(30), "30/1")
    assert output_format(project([clip("d", BOOK, 0, 1000)])).fps == 30  # only a bookend
    fixed = output_format(project(THREE, export=ExportSettings(height=721, fps=59.94)))
    assert (fixed.width, fixed.height, fixed.fps) == (1280, 720, Fraction("59.94"))


def test_counts_round_half_up() -> None:
    assert frame_count(1000, FMT) == 60
    assert frame_count(25, FMT) == 2  # 1.5 frames rounds up
    assert frame_count(1001, OutputFormat(1, 1, Fraction(30000, 1001))) == 30
    assert sample_count(1) == 48 and sample_count(3000) == 144_000


def test_atempo_chain_keeps_every_factor_in_range() -> None:
    assert atempo_chain(1.0) == []
    assert atempo_chain(1.5) == ["atempo=1.5"]
    assert atempo_chain(8.0) == ["atempo=2", "atempo=2", "atempo=2"]
    assert atempo_chain(0.25) == ["atempo=0.5", "atempo=0.5"]
    assert atempo_chain(3.0) == ["atempo=2", "atempo=1.5"]
    assert atempo_chain(0.3) == ["atempo=0.5", "atempo=0.6"]


def test_graph_text_and_totals() -> None:
    graph = build_edit_graph(project(THREE), PATHS, FMT, first_input=1)
    assert (graph.frames, graph.samples, graph.duration_ms) == (180, 144_000, 3000)
    assert [c.clip_id for c in graph.inputs] == ["a" * 12, "b" * 12, "c" * 12]
    assert graph.input_args()[:6] == ["-ss", "0.000", "-t", "1.000", "-i", "C:\\my footage\\red.mkv"]
    assert graph.inputs[2].args()[:4] == ["-ss", "0.500", "-t", "0.500"]
    v0, a0, v1, a1, v2, a2, concat = graph.filters
    assert v0.startswith("[1:v:0]setpts=(PTS-STARTPTS)*1/1,fps=60/1,scale=1920:1080:")
    assert "tpad=stop_mode=clone:stop=60,trim=end_frame=60" in v0 and v0.endswith("[v0]")
    assert v1.startswith("[2:v:0]setpts=(PTS-STARTPTS)*1/2,")
    assert v2.startswith("[3:v:0]setpts=(PTS-STARTPTS)*2/1,")
    assert a0 == (
        "[1:a:0]asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "apad,atrim=end_sample=48000,asetpts=PTS-STARTPTS[a0]"
    )
    assert a1 == "anullsrc=r=48000:cl=stereo,atrim=end_sample=48000[a1]"  # blue has no audio
    assert "atempo=0.5," in a2
    assert concat == f"[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[{VIDEO_LABEL}][{AUDIO_LABEL}]"
    assert graph.script().count(";\n") == 6


def test_counts_never_drift_over_many_short_clips() -> None:
    clips = [clip(f"{k:x}", RED, 0, 37) for k in range(12)]  # 37 ms = 2.22 frames each
    graph = build_edit_graph(project(clips), PATHS, FMT)
    per_clip = [int(f.split("trim=end_frame=")[1].split(",")[0]) for f in graph.filters if ":v:0]" in f]
    assert sum(per_clip) == graph.frames == frame_count(12 * 37, FMT)
    assert set(per_clip) == {2, 3}


def test_a_clip_shorter_than_a_frame_is_skipped_and_other_tracks_ignored() -> None:
    clips = [clip("a", RED, 0, 1000), clip("b", RED, 0, 5), clip("c", RED, 0, 1000, track=1)]
    graph = build_edit_graph(project(clips), PATHS, FMT)
    assert graph.skipped == ["b" * 12] and len(graph.inputs) == 1


def test_errors() -> None:
    with pytest.raises(ExportError, match="no clips"):
        build_edit_graph(project([]), PATHS, FMT)
    with pytest.raises(ExportError, match="cannot be found"):
        build_edit_graph(project(THREE), {RED: PATHS[RED]}, FMT)
    with pytest.raises(ExportError, match="unknown clip effect"):
        build_edit_graph(project([clip("a", RED, 0, 1000, effects=[EffectSpec(type="zoom")])]), PATHS, FMT)


def test_clip_effects_come_from_the_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clipeffects, "REGISTRY", {})
    clipeffects.register(ClipEffect("mirror", "Mirror", lambda params: "hflip"))
    graph = build_edit_graph(project([clip("a", RED, 0, 1000, effects=[EffectSpec(type="mirror")])]), PATHS, FMT)
    assert "format=yuv420p,hflip,tpad=" in graph.filters[0]


def test_edited_video_args() -> None:
    graph = build_edit_graph(project(THREE), PATHS, FMT)
    args = edited_video_args(Path("ffmpeg.exe"), graph, Path("C:/out dir/graph.txt"), Path("C:/out dir/e.mp4"), FMT)
    assert args[0] == "ffmpeg.exe" and args[-1] == "C:\\out dir\\e.mp4"
    i = args.index("-/filter_complex")
    assert args[i + 1] == "C:\\out dir\\graph.txt"
    assert ["-map", "[vedit]", "-map", "[aedit]", "-r", "60/1", "-c:v", "h264_nvenc"] == args[i + 2 : i + 10]


# --- real ffmpeg -------------------------------------------------------------------

BIN = Path(__file__).resolve().parents[1] / "bin"
FFMPEG, FFPROBE = BIN / "ffmpeg.exe", BIN / "ffprobe.exe"
needs_ffmpeg = pytest.mark.skipif(
    not (FFMPEG.is_file() and FFPROBE.is_file()), reason="bin/ffmpeg.exe is not installed"
)


def run(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(args, capture_output=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr.decode(errors="replace")[-2000:]
    return result


def make_footage(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    red, blue = folder / "red.mkv", folder / "blue.mp4"
    run([
        str(FFMPEG), "-hide_banner", "-y", "-f", "lavfi", "-i", "color=c=red:s=1280x720:r=60:d=2",
        "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:d=2", "-c:v", "libx264", "-g", "30",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(red),
    ])  # fmt: skip
    run([
        str(FFMPEG), "-hide_banner", "-y", "-f", "lavfi", "-i", "color=c=blue:s=640x480:r=30:d=2",
        "-c:v", "libx264", "-g", "15", "-pix_fmt", "yuv420p", str(blue),
    ])  # fmt: skip
    return {RED: red, BLUE: blue}


@needs_ffmpeg
def test_real_ffmpeg_cuts_speeds_and_letterboxes_exactly(tmp_path: Path) -> None:
    paths = make_footage(tmp_path / "footage dir")
    graph = build_edit_graph(project(THREE), paths, FMT)
    script = tmp_path / "out dir" / "graph.txt"
    script.parent.mkdir()
    script.write_text(graph.script(), encoding="utf-8")
    dest = tmp_path / "out dir" / "edited.mp4"
    run(edited_video_args(FFMPEG, graph, script, dest, FMT))

    probe = json.loads(
        run([
            str(FFPROBE), "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(dest),
        ]).stdout
    )  # fmt: skip
    video = next(s for s in probe["streams"] if s["codec_type"] == "video")
    audio = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1920, 1080, "60/1")
    assert int(video["nb_read_frames"]) == 180
    assert (int(audio["sample_rate"]), int(audio["channels"])) == (48_000, 2)

    raw = run([
        str(FFMPEG), "-v", "error", "-i", str(dest), "-vf", "scale=16:9:flags=area",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]).stdout  # fmt: skip
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 9, 16, 3).astype(int)
    assert frames.shape[0] == 180

    def colour(k: int, x: int = 8) -> str:
        r, g, b = frames[k, 4, x]
        if r > 150 and g < 80 and b < 80:
            return "red"
        if b > 150 and r < 80 and g < 80:
            return "blue"
        return "black" if r + g + b < 60 else f"{r},{g},{b}"

    assert [colour(k) for k in (0, 59, 60, 119, 120, 179)] == ["red", "red", "blue", "blue", "red", "red"]
    assert colour(90, x=0) == "black"  # 4:3 footage is pillarboxed
    assert colour(30, x=0) == "red"  # 16:9 footage fills the frame

    pcm = run([
        str(FFMPEG), "-v", "error", "-i", str(dest), "-ac", "1", "-f", "f32le", "-",
    ]).stdout  # fmt: skip
    mono = np.frombuffer(pcm, dtype=np.float32)
    assert abs(mono.size - 144_000) <= 2048  # AAC frames round the end

    def rms(a_ms: int, b_ms: int) -> float:
        part = mono[sample_count(a_ms) : sample_count(b_ms)]
        return float(np.sqrt(np.mean(part**2)))

    assert rms(200, 800) > 0.05  # red: sine (lavfi sine is 1/8 full scale)
    assert rms(1200, 1800) < 0.01  # blue: no audio, silence
    assert rms(2200, 2800) > 0.05  # red at half speed: still a sine (atempo)


def test_limit_clips_cuts_the_timeline_at_the_limit() -> None:
    from backend.edl.timemap import timeline_duration
    from backend.export.editgraph import limit_clips

    proj = project([*THREE, clip("d", RED, 0, 500, track=1)])
    short = limit_clips(proj, 1500)
    ids = [c.id[0] for c in short.clips]
    assert ids == ["a", "b", "d"]  # c starts at 2000: dropped; the other track stays
    assert short.clips[1].out_ms == 1000  # 500 ms of timeline at 2x is 1000 ms of source
    assert timeline_duration(short.clips) == 1500
    assert limit_clips(proj, 99_999).clips == proj.clips
    assert len(proj.clips) == 4  # the input is not changed
    with pytest.raises(ExportError):
        limit_clips(proj, 0)


FROZEN = [clip("a", RED, 0, 500), clip("f", RED, 0, 1000, freeze_ms=500), clip("b", RED, 500, 1000)]


def test_a_freeze_frame_reads_one_frame_clones_it_and_is_silent() -> None:
    graph = build_edit_graph(project(FROZEN), PATHS, FMT)
    assert (graph.frames, graph.duration_ms) == (120, 2000)
    assert graph.inputs[1].args()[:4] == ["-ss", "0.500", "-t", "0.250"]
    v1 = graph.filters[2]
    assert v1.startswith("[1:v:0]trim=end_frame=1,setpts=")
    assert "tpad=stop_mode=clone:stop=60,trim=end_frame=60" in v1
    assert graph.filters[3] == "anullsrc=r=48000:cl=stereo,atrim=end_sample=48000[a1]"


@needs_ffmpeg
def test_real_ffmpeg_holds_the_frame_for_its_length(tmp_path: Path) -> None:
    paths = make_footage(tmp_path / "footage")
    graph = build_edit_graph(project(FROZEN), paths, FMT)
    script = tmp_path / "graph.txt"
    script.write_text(graph.script(), encoding="utf-8")
    dest = tmp_path / "frozen.mp4"
    run(edited_video_args(FFMPEG, graph, script, dest, FMT))
    raw = run([
        str(FFMPEG), "-v", "error", "-i", str(dest), "-vf", "scale=16:9:flags=area",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]).stdout  # fmt: skip
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 9, 16, 3).astype(int)
    assert frames.shape[0] == 120
    assert frames[60, 4, 8, 0] > 150  # the hold shows the red frame
    pcm = run([
        str(FFMPEG), "-v", "error", "-i", str(dest), "-ac", "1", "-f", "f32le", "-",
    ]).stdout  # fmt: skip
    mono = np.frombuffer(pcm, dtype=np.float32)

    def rms(a_ms: int, b_ms: int) -> float:
        part = mono[sample_count(a_ms) : sample_count(b_ms)]
        return float(np.sqrt(np.mean(part**2)))

    assert rms(100, 400) > 0.05
    assert rms(700, 1300) < 0.01  # the hold is silent
    assert rms(1600, 1900) > 0.05
