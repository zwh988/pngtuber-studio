"""Final render (M6-5): one ffmpeg run makes ``final_1080p.mp4`` and ``video_edited.mp4``.

Inputs, in order: the avatar frames as raw RGBA on stdin at the track's 30 fps (when
there is an avatar), the voice track (``voice_processed.wav``), then one input per clip
(the edit graph). The edited video and game audio are split: one copy is encoded as
``video_edited.mp4`` (footage audio at its own level); the other gets the avatar
overlaid (ffmpeg holds each avatar frame until the next one starts: the floor rule of
decision 2) and the mix: game audio at ``game_audio_db`` plus the voice on both
channels, summed without normalising, then limited at -1 dBFS (spec 7 "Mix"). When the
transparent overlay is asked for, the avatar frames are also split to a third output, a
PNG sequence written by ffmpeg's own (multi-threaded) PNG encoder in the same run.

``final_filters`` and ``final_args`` are pure; ``run_render`` runs the process (rule 14:
argument lists), feeds the avatar pipe from a thread, reads ``-progress`` from stdout,
writes ffmpeg's log to a file and stops it on cancel.
"""

import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from backend.audio.loudness import CEILING_DB, db_to_linear
from backend.export.bundle import OVERLAY_DIR
from backend.export.compositor import Compositor
from backend.export.editgraph import (
    AUDIO_ENCODE_ARGS,
    VIDEO_ENCODE_ARGS,
    EditGraph,
    OutputFormat,
    build_edit_graph,
)
from backend.export.errors import ExportCancelled, ExportError
from backend.export.lanes import LaneGraph, build_lane_graph, overlay_steps
from backend.project.schema import Project

FINAL_NAME = "final_1080p.mp4"
EDITED_NAME = "video_edited.mp4"
GRAPH_NAME = "export_graph.txt"
LOG_NAME = "export_ffmpeg.log"
PROGRESS_PERIOD_S = "0.5"
OVERLAY_PATTERN = "frame_%06d.png"  # same names as bundle.png_name
# ffmpeg's PNG encoder: "sub" prediction and fast deflate measured 341 fps and about
# 440 MB per minute on the real art (Pillow: about 40 fps, single-threaded).
OVERLAY_ENCODE_ARGS: tuple[str, ...] = ("-c:v", "png", "-pred", "sub", "-compression_level", "1")


@dataclass(frozen=True)
class RenderPlan:
    ffmpeg: Path
    graph: EditGraph
    fmt: OutputFormat
    voice_wav: Path
    game_db: float
    avatar: Compositor | None
    out_dir: Path
    overlay_frames: int = 0  # avatar frames to write as PNGs (0: no PNG sequence)
    # M8-1: the audio-lane clips (``audio_clips.wav``), None when no clip is heard.
    music_wav: Path | None = None
    # M8-2: the video-lane clips (inputs after the footage clips).
    lanes: LaneGraph = field(default_factory=LaneGraph)

    @property
    def overlay_dir(self) -> Path:
        return self.out_dir / OVERLAY_DIR

    @property
    def final_path(self) -> Path:
        return self.out_dir / FINAL_NAME

    @property
    def edited_path(self) -> Path:
        return self.out_dir / EDITED_NAME

    @property
    def script_path(self) -> Path:
        return self.out_dir / GRAPH_NAME

    @property
    def log_path(self) -> Path:
        return self.out_dir / LOG_NAME


@dataclass(frozen=True)
class RenderReport:
    frames: int
    avatar_frames: int
    seconds: float  # wall time of the ffmpeg run
    overlay_frames: int = 0  # PNG files written


def first_clip_input(with_avatar: bool, with_music: bool = False) -> int:
    """ffmpeg input index of the first clip: [avatar pipe], voice, [audio clips], then
    the clips."""
    return (2 if with_avatar else 1) + (1 if with_music else 0)


def make_plan(
    project: Project,
    source_paths: dict[str, Path],
    fmt: OutputFormat,
    *,
    ffmpeg: Path,
    voice_wav: Path,
    avatar: Compositor | None,
    out_dir: Path,
    overlay_frames: int = 0,
    music_wav: Path | None = None,
    image_paths: dict[str, Path] | None = None,
    total_ms: int | None = None,
) -> RenderPlan:
    first = first_clip_input(avatar is not None, music_wav is not None)
    graph = build_edit_graph(
        project, source_paths, fmt, first_input=first, total_ms=total_ms
    )
    lanes = build_lane_graph(
        project,
        source_paths,
        image_paths or {},
        fmt,
        graph.duration_ms,
        first_input=first + len(graph.inputs),
    )
    return RenderPlan(
        ffmpeg=ffmpeg,
        graph=graph,
        fmt=fmt,
        voice_wav=voice_wav,
        game_db=project.game_audio_db,
        avatar=avatar,
        out_dir=out_dir,
        overlay_frames=overlay_frames if avatar is not None else 0,
        music_wav=music_wav,
        lanes=lanes,
    )


def final_filters(
    graph: EditGraph,
    fmt: OutputFormat,
    *,
    with_avatar: bool,
    game_db: float,
    overlay_frames: int = 0,
    with_music: bool = False,
    lanes: LaneGraph | None = None,
) -> list[str]:
    voice = 1 if with_avatar else 0
    limit = db_to_linear(CEILING_DB)
    lanes = lanes if lanes is not None else LaneGraph()
    under = [layer for layer in lanes.layers if not layer.over_avatar]
    over = [layer for layer in lanes.layers if layer.over_avatar]
    filters = [
        *graph.filters,
        *lanes.filters,
        f"[{graph.video}]split=2[vmain][vedit_out]",
        f"[{graph.audio}]asplit=2[agame][aedit_out]",
    ]
    if with_avatar:
        if overlay_frames > 0:
            filters.append("[0:v]format=rgba,split=2[avatar][avpng]")
            filters.append(f"[avpng]trim=end_frame={overlay_frames}[overlay_out]")
        else:
            filters.append("[0:v]format=rgba[avatar]")
    # M8-2: lane clips under the avatar, the avatar, then the lanes over it.
    filters += overlay_steps("vmain", under, "vunder", fmt, "lu")
    if with_avatar:
        filters.append("[vunder][avatar]overlay=0:0:format=auto[vavatar]")
    else:
        filters.append("[vunder]null[vavatar]")
    filters += overlay_steps("vavatar", over, "vover", fmt, "lo")
    # The avatar track runs one frame past the end; trim keeps the exact frame count.
    filters.append(f"[vover]format=yuv420p,trim=end_frame={graph.frames}[vfinal]")
    voice_chain = (
        f"[{voice}:a:0]aresample={fmt.sample_rate},pan=stereo|c0=c0|c1=c0,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad,atrim=end_sample={graph.samples}[voice]"
    )
    # M8-1: the audio-lane clips join the sum before the limiter, as in the preview.
    music_chain = (
        f"[{voice + 1}:a:0]aresample={fmt.sample_rate},"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad,atrim=end_sample={graph.samples}[music]"
    )
    sources = "[game][voice]" + ("[music]" if with_music else "")
    sources += "".join(f"[{label}]" for label in lanes.audio)  # M8-2: lane clip sound
    count = 2 + (1 if with_music else 0) + len(lanes.audio)
    mix = (
        f"{sources}amix=inputs={count}:normalize=0:duration=first,"
        f"alimiter=limit={limit:.6f}:level=disabled:latency=1,"
        f"atrim=end_sample={graph.samples}[afinal]"
    )
    filters += [f"[agame]volume={game_db:.2f}dB[game]", voice_chain]
    if with_music:
        filters.append(music_chain)
    filters.append(mix)
    return filters


def final_args(plan: RenderPlan) -> list[str]:
    fmt = plan.fmt
    inputs: list[str] = []
    if plan.avatar is not None:
        inputs += [
            "-f", "rawvideo", "-pix_fmt", "rgba",
            "-s", f"{plan.avatar.width}x{plan.avatar.height}",
            "-r", str(plan.avatar.track.fps), "-i", "pipe:0",
        ]  # fmt: skip
    inputs += ["-i", str(plan.voice_wav)]
    if plan.music_wav is not None:
        inputs += ["-i", str(plan.music_wav)]
    out = [
        "-map", "[vfinal]", "-map", "[afinal]", "-r", fmt.fps_text,
        *VIDEO_ENCODE_ARGS, *AUDIO_ENCODE_ARGS, "-movflags", "+faststart", str(plan.final_path),
        "-map", "[vedit_out]", "-map", "[aedit_out]", "-r", fmt.fps_text,
        *VIDEO_ENCODE_ARGS, *AUDIO_ENCODE_ARGS, "-movflags", "+faststart", str(plan.edited_path),
    ]  # fmt: skip
    if plan.avatar is not None and plan.overlay_frames > 0:
        out += [
            "-map", "[overlay_out]", "-fps_mode", "passthrough", *OVERLAY_ENCODE_ARGS,
            "-f", "image2", "-start_number", "0", str(plan.overlay_dir / OVERLAY_PATTERN),
        ]  # fmt: skip
    return [
        str(plan.ffmpeg), "-hide_banner", "-y", "-nostats",
        "-progress", "pipe:1", "-stats_period", PROGRESS_PERIOD_S,
        *inputs, *plan.graph.input_args(),
        *plan.lanes.input_args(),
        "-/filter_complex", str(plan.script_path),
        *out,
    ]  # fmt: skip


def parse_progress(line: str) -> tuple[str, str] | None:
    key, sep, value = line.strip().partition("=")
    return (key, value) if sep else None


def _log_tail(path: Path, lines: int = 12) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no ffmpeg log)"
    kept = [line for line in text.splitlines() if line.strip()]
    return "\n".join(kept[-lines:])


def run_render(
    plan: RenderPlan,
    *,
    should_stop: Callable[[], bool] = lambda: False,
    progress: Callable[[float], None] = lambda fraction: None,
) -> RenderReport:
    """Run the final ffmpeg pass. Raises ``ExportCancelled`` when ``should_stop`` turns
    true (ffmpeg is stopped), ``ExportError`` when ffmpeg or the avatar feed fails."""
    import time

    plan.out_dir.mkdir(parents=True, exist_ok=True)
    with_avatar = plan.avatar is not None
    overlay = plan.overlay_frames if with_avatar else 0
    if overlay:
        plan.overlay_dir.mkdir(parents=True, exist_ok=True)  # image2 does not create folders
    script = ";\n".join(
        final_filters(
            plan.graph,
            plan.fmt,
            with_avatar=with_avatar,
            game_db=plan.game_db,
            overlay_frames=overlay,
            with_music=plan.music_wav is not None,
            lanes=plan.lanes,
        )
    )
    plan.script_path.write_text(script + "\n", encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    started = time.perf_counter()
    with plan.log_path.open("w", encoding="utf-8", errors="replace") as log:
        try:
            proc = subprocess.Popen(
                final_args(plan),
                stdin=subprocess.PIPE if with_avatar else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=log,
                creationflags=flags,
            )
        except OSError as exc:
            raise ExportError(f"ffmpeg could not be started: {exc}") from exc

        feed_error: list[BaseException] = []
        fed = [0]
        stop_feed = threading.Event()

        def feed() -> None:
            assert proc.stdin is not None
            try:
                for view in plan.avatar.frames():  # type: ignore[union-attr]
                    if stop_feed.is_set():
                        break
                    proc.stdin.write(view)
                    fed[0] += 1
            except (BrokenPipeError, ConnectionResetError, ValueError):
                pass  # ffmpeg stopped reading: its exit code says why
            except BaseException as exc:  # noqa: BLE001 - reported to the caller below
                feed_error.append(exc)
                proc.kill()
            finally:
                try:
                    proc.stdin.close()
                except OSError:
                    pass

        feeder = threading.Thread(target=feed, name="avatar-feed", daemon=True) if with_avatar else None
        if feeder is not None:
            feeder.start()
        cancelled = False
        total_us = max(plan.graph.duration_ms, 1) * 1000
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                if should_stop():
                    cancelled = True
                    proc.kill()
                    break
                parsed = parse_progress(raw.decode("utf-8", errors="replace"))
                if parsed is None:
                    continue
                key, value = parsed
                if key == "out_time_us" and value.isdigit():
                    progress(min(int(value) / total_us, 1.0))
        finally:
            code = proc.wait()
            stop_feed.set()
            if feeder is not None:
                feeder.join(timeout=30)
    if cancelled or should_stop():
        raise ExportCancelled("export cancelled")
    if feed_error:
        error = feed_error[0]
        if isinstance(error, ExportError):
            raise error
        raise ExportError(f"drawing the avatar failed: {error}") from error
    if code != 0:
        raise ExportError(f"ffmpeg failed (exit code {code}):\n{_log_tail(plan.log_path)}")
    progress(1.0)
    return RenderReport(
        frames=plan.graph.frames,
        avatar_frames=fed[0],
        seconds=time.perf_counter() - started,
        overlay_frames=len(list(plan.overlay_dir.glob("frame_*.png"))) if overlay else 0,
    )
