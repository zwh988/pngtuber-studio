"""The export steps in order (M6): voice tracks, then the final render. No session here:
the caller passes a snapshot of the project (``ExportInputs``) and the two take
callables, so the steps can be tested without a project folder."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.avatar.art import AvatarArt
from backend.avatar.track import FrameTrack
from backend.edl.timemap import timeline_duration
from backend.export.compositor import (
    Compositor,
    SpriteBank,
    needed_height,
    sprite_files,
)
from backend.export.editgraph import OutputFormat, limit_clips, output_format
from backend.export.errors import ExportError
from backend.export.runner import RenderReport, make_plan, run_render
from backend.export.voicetrack import (
    PROCESSED_NAME,
    VoiceCue,
    VoiceTrackReport,
    voice_schedule,
    write_voice_tracks,
)
from backend.project.schema import Project
from backend.project.timeline import TimelineState

# Share of the progress bar each step gets (the render dominates).
VOICE_SHARE = 0.1


@dataclass(frozen=True)
class ExportInputs:
    project: Project
    timeline: TimelineState
    source_paths: dict[str, Path]
    track: FrameTrack | None
    art: AvatarArt | None
    art_root: Path | None


@dataclass(frozen=True)
class ExportResult:
    fmt: OutputFormat
    voice: VoiceTrackReport
    render: RenderReport
    with_avatar: bool


Report = Callable[[str, float], None]  # (stage, overall fraction 0..1)


def build_compositor(inputs: ExportInputs, fmt: OutputFormat) -> Compositor | None:
    """The avatar layer, or None when there is no art or nothing to draw."""
    track, art, root = inputs.track, inputs.art, inputs.art_root
    if track is None or art is None or root is None or not track.sprites:
        return None
    bank = SpriteBank(sprite_files(track, art, root), needed_height(track, fmt.height))
    return Compositor(track, bank, fmt.width, fmt.height)


def run_export(
    inputs: ExportInputs,
    out_dir: Path,
    *,
    ffmpeg: Path,
    processed_for: Callable[[VoiceCue], Path],
    raw_for: Callable[[VoiceCue], tuple[np.ndarray, int]],
    should_stop: Callable[[], bool] = lambda: False,
    report: Report = lambda stage, fraction: None,
    limit_ms: int | None = None,
) -> ExportResult:
    """``limit_ms`` exports only the start of the timeline (a quick test export)."""
    if not inputs.timeline.clips:
        raise ExportError("the timeline has no clips")
    project = inputs.project if limit_ms is None else limit_clips(inputs.project, limit_ms)
    total_ms = timeline_duration(project.clips)
    fmt = output_format(project)
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
    report("avatar", VOICE_SHARE)
    compositor = build_compositor(inputs, fmt)
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
    )
    render = run_render(
        plan,
        should_stop=should_stop,
        progress=lambda f: report("render", VOICE_SHARE + f * (1 - VOICE_SHARE)),
    )
    report("done", 1.0)
    return ExportResult(fmt=fmt, voice=voice, render=render, with_avatar=compositor is not None)
