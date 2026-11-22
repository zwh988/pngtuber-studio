"""The export steps in order (M6): voice tracks, then the final render. No session here:
the caller passes a snapshot of the project (``ExportInputs``) and the two take
callables, so the steps can be tested without a project folder."""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

from backend.avatar.art import AvatarArt
from backend.avatar.track import FrameTrack, track_frame_at
from backend.edl.timemap import clip_spans
from backend.export.audioclips import (
    AUDIO_CLIPS_NAME,
    AudioClipTrackReport,
    write_audio_clip_track,
)
from backend.export.bundle import (
    RawLinks,
    ensure_new_folder,
    ffmpeg_version,
    link_raw_videos,
    write_manifest,
    write_overlay_readme,
    write_snapshot,
)
from backend.export.compositor import (
    Compositor,
    SpriteBank,
    needed_height,
    sprite_files,
)
from backend.export.editgraph import (
    AUDIO_ENCODE_ARGS,
    VIDEO_ENCODE_ARGS,
    OutputFormat,
    limit_clips,
    output_format,
)
from backend.export.errors import ExportCancelled, ExportError
from backend.export.lanes import program_end_ms
from backend.export.runner import RenderReport, make_plan, run_render
from backend.export.voicetrack import (
    PROCESSED_NAME,
    VoiceCue,
    VoiceTrackReport,
    voice_schedule,
    write_voice_tracks,
)
from backend.project.schema import SCHEMA_VERSION, Project
from backend.project.timeline import TimelineState

APP_NAME = "PNGtuber Studio"  # as in backend/app.py (imported from here would be circular)

# Share of the progress bar each step gets (the render dominates).
VOICE_SHARE = 0.1
FINISH_SHARE = 0.03


@dataclass(frozen=True)
class ExportInputs:
    project: Project
    timeline: TimelineState
    source_paths: dict[str, Path]
    track: FrameTrack | None
    art: AvatarArt | None
    art_root: Path | None
    # M8-1: the decoded 48 kHz WAV of each imported audio file, by file id.
    audio_paths: dict[str, Path] = field(default_factory=dict)
    # M8-4: the rendered FX file of each audio clip with FX, by clip id.
    audio_fx_paths: dict[str, Path] = field(default_factory=dict)
    # M8-2: each imported image (video lanes), by image id.
    image_paths: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportOptions:
    include_overlay: bool = False  # the avatar PNG sequence
    include_raw_links: bool = True  # video_raw/ hard links
    limit_ms: int | None = None  # export only the start of the timeline (test exports)

    @classmethod
    def from_project(cls, project: Project, limit_ms: int | None = None) -> "ExportOptions":
        return cls(
            include_overlay=project.export.include_avatar_overlay,
            include_raw_links=project.export.include_raw_video_link,
            limit_ms=limit_ms,
        )


@dataclass(frozen=True)
class ExportResult:
    fmt: OutputFormat
    voice: VoiceTrackReport
    render: RenderReport
    audio_clips: AudioClipTrackReport | None
    with_avatar: bool
    overlay_frames: int
    raw: RawLinks
    seconds: float


Report = Callable[[str, float], None]  # (stage, overall fraction 0..1)


def build_compositor(inputs: ExportInputs, fmt: OutputFormat) -> Compositor | None:
    """The avatar layer, or None when there is no art or nothing to draw."""
    track, art, root = inputs.track, inputs.art, inputs.art_root
    if track is None or art is None or root is None or not track.sprites:
        return None
    bank = SpriteBank(sprite_files(track, art, root), needed_height(track, fmt.height))
    return Compositor(track, bank, fmt.width, fmt.height)


def footage_paths(project: Project, source_paths: Mapping[str, Path]) -> list[Path]:
    """The recordings the track-0 clips use, in timeline order (bookends left out)."""
    sources = {s.id: s for s in project.sources}
    found: list[Path] = []
    for span in clip_spans(project.clips):
        clip = project.clips[span.index]
        source = sources.get(clip.source_id)
        path = source_paths.get(clip.source_id)
        if source is not None and not source.external and path is not None and path not in found:
            found.append(path)
    return found


def run_export(
    inputs: ExportInputs,
    out_dir: Path,
    *,
    ffmpeg: Path,
    processed_for: Callable[[VoiceCue], Path],
    raw_for: Callable[[VoiceCue], tuple[np.ndarray, int]],
    options: ExportOptions | None = None,
    should_stop: Callable[[], bool] = lambda: False,
    report: Report = lambda stage, fraction: None,
) -> ExportResult:
    """Every export step into ``out_dir`` (an empty or new folder): voice tracks and
    lines, the final and edited videos, the optional PNG sequence, the raw video links,
    the project snapshot and ``export.json``. The caller renames the folder when this
    raises (``mark_incomplete``)."""
    started = time.perf_counter()
    opts = options if options is not None else ExportOptions.from_project(inputs.project)
    if not inputs.timeline.clips:
        raise ExportError("the timeline has no clips")
    ensure_new_folder(out_dir)
    project = inputs.project if opts.limit_ms is None else limit_clips(inputs.project, opts.limit_ms)
    # M8-2: the video runs to the last clip on any lane (black past the footage).
    total_ms = program_end_ms(inputs.project)
    if opts.limit_ms is not None:
        total_ms = min(total_ms, opts.limit_ms)
    fmt = output_format(project)
    compositor = build_compositor(inputs, fmt)
    overlay_count = (
        track_frame_at(total_ms, compositor.frame_count) + 1
        if opts.include_overlay and compositor is not None
        else 0
    )
    render_share = 1 - VOICE_SHARE - FINISH_SHARE
    timings: dict[str, float] = {}

    def timed(name: str, since: float) -> float:
        now = time.perf_counter()
        timings[name] = round(now - since, 2)
        return now

    mark = started
    report("voice", 0.0)
    cues = [cue for cue in voice_schedule(inputs.timeline) if cue.start_ms < total_ms]
    voice = write_voice_tracks(
        cues,
        total_ms,
        out_dir,
        processed_for=processed_for,
        raw_for=raw_for,
        should_stop=should_stop,
        progress=lambda f: report("voice", f * VOICE_SHARE),
    )
    music = write_audio_clip_track(
        project,
        total_ms,
        out_dir,
        inputs.audio_paths,
        fx_paths=inputs.audio_fx_paths,
        should_stop=should_stop,
    )
    mark = timed("voice", mark)
    report("render", VOICE_SHARE)
    if compositor is not None:
        compositor.preload()
    plan = make_plan(
        project,
        inputs.source_paths,
        fmt,
        ffmpeg=ffmpeg,
        voice_wav=out_dir / PROCESSED_NAME,
        avatar=compositor,
        out_dir=out_dir,
        overlay_frames=overlay_count,
        music_wav=None if music is None else out_dir / AUDIO_CLIPS_NAME,
        image_paths=inputs.image_paths,
        total_ms=total_ms,
    )
    render = run_render(
        plan,
        should_stop=should_stop,
        progress=lambda f: report("render", VOICE_SHARE + f * render_share),
    )
    mark = timed("render", mark)
    overlay_frames = render.overlay_frames
    if compositor is not None and overlay_frames:
        write_overlay_readme(
            out_dir, overlay_frames, compositor.track.fps, compositor.width, compositor.height
        )
    if should_stop():
        raise ExportCancelled("export cancelled")
    report("finish", 1 - FINISH_SHARE)
    raw = (
        link_raw_videos(footage_paths(project, inputs.source_paths), out_dir)
        if opts.include_raw_links
        else RawLinks()
    )
    write_snapshot(inputs.project, out_dir)
    seconds = time.perf_counter() - started
    timed("finish", mark)
    write_manifest(
        out_dir,
        {
            "app": APP_NAME,
            "schema_version": SCHEMA_VERSION,
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "project": inputs.project.name,
            "ffmpeg": ffmpeg_version(ffmpeg),
            "video": {
                "width": fmt.width,
                "height": fmt.height,
                "fps": fmt.fps_text,
                "frames": render.frames,
                "duration_ms": total_ms,
                "encode": " ".join(VIDEO_ENCODE_ARGS),
                "audio": " ".join(AUDIO_ENCODE_ARGS),
            },
            "limited_to_ms": opts.limit_ms,
            "game_audio_db": project.game_audio_db,
            "voice": {
                "lines": voice.lines,
                "sample_rate": voice.sample_rate,
                "peak": round(voice.peak, 4),
                "cut_ms": voice.cut_ms,
            },
            "audio_clips": (
                {"clips": 0, "files": []}
                if music is None
                else {
                    "clips": music.clips,
                    "sample_rate": music.sample_rate,
                    "peak": round(music.peak, 4),
                    "cut_ms": music.cut_ms,
                    "files": music.files,
                }
            ),
            "video_lanes": {
                "clips": len(plan.lanes.layers),
                "with_sound": len(plan.lanes.audio),
            },
            "avatar": {
                "drawn": compositor is not None,
                "frames_fed": render.avatar_frames,
                "overlay_frames": overlay_frames,
            },
            "raw_video": {"linked": raw.linked, "listed": raw.listed},
            "seconds": {**timings, "total": round(seconds, 2)},
        },
    )
    report("done", 1.0)
    return ExportResult(
        fmt=fmt,
        voice=voice,
        render=render,
        audio_clips=music,
        with_avatar=compositor is not None,
        overlay_frames=overlay_frames,
        raw=raw,
        seconds=seconds,
    )
