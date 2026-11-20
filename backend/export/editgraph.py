"""Clip list to ffmpeg filter graph (M6-3). Pure: paths come in, argument lists go out.

Each track-0 clip is its own ffmpeg input, opened with ``-ss`` / ``-t`` so only its
part of the recording is decoded (input seeking is frame-accurate when re-encoding).
Per clip, the video is sped up (``setpts``), brought to the output frame rate
(``fps``), scaled into the 16:9 output with black bars (like the preview's
``object-fit: contain``), run through the clip effects from the registry (rule 13),
then padded or cut to exactly its number of output frames. The audio is sped up with
``atempo`` (pitch kept, as in the preview), resampled to 48 kHz stereo and padded or
cut to exactly its number of samples. A clip whose source has no audio gets silence.

A freeze frame (``Clip.freeze_ms``) reads a moment from its frame, keeps one frame,
clones it to the clip's length (the same ``tpad`` that pads every clip) and is silent.

Frame and sample counts come from the clip's timeline start and end
(``count(end) - count(start)``), so the totals equal the timeline length and the cuts
never drift, however many clips there are. The clips are joined with ``concat``.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from backend.edl.timemap import clip_spans, round_half_up, speed_fraction
from backend.export.clipeffects import ClipEffectError, video_filter_for
from backend.export.errors import ExportError
from backend.project.schema import Project

OUTPUT_ASPECT = Fraction(16, 9)
SAMPLE_RATE = 48_000
FALLBACK_FPS = Fraction(30)
ATEMPO_MIN = Fraction(1, 2)
ATEMPO_MAX = Fraction(2)

VIDEO_ENCODE_ARGS: tuple[str, ...] = (
    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0",
    "-pix_fmt", "yuv420p",
)  # fmt: skip
AUDIO_ENCODE_ARGS: tuple[str, ...] = ("-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE))
VIDEO_LABEL = "vedit"
# How much of the recording a freeze frame's input decodes (ms): enough for one frame.
FREEZE_READ_MS = 250
AUDIO_LABEL = "aedit"


@dataclass(frozen=True)
class OutputFormat:
    width: int
    height: int
    fps: Fraction
    sample_rate: int = SAMPLE_RATE

    @property
    def fps_text(self) -> str:
        return f"{self.fps.numerator}/{self.fps.denominator}"


@dataclass(frozen=True)
class ClipInput:
    clip_id: str
    path: Path
    seek_ms: int
    length_ms: int

    def args(self) -> list[str]:
        return ["-ss", seconds(self.seek_ms), "-t", seconds(self.length_ms), "-i", str(self.path)]


@dataclass(frozen=True)
class EditGraph:
    inputs: list[ClipInput]
    filters: list[str]
    video: str  # output label of the edited video
    audio: str  # output label of the edited game audio
    frames: int
    samples: int
    duration_ms: int
    skipped: list[str] = field(default_factory=list)  # clips shorter than one frame

    def script(self) -> str:
        return ";\n".join(self.filters) + "\n"

    def input_args(self) -> list[str]:
        return [arg for clip in self.inputs for arg in clip.args()]


def seconds(ms: int) -> str:
    """Exact seconds text for ffmpeg ("12.345")."""
    sign = "-" if ms < 0 else ""
    ms = abs(ms)
    return f"{sign}{ms // 1000}.{ms % 1000:03d}"


def even(value: int) -> int:
    return value - value % 2


def output_format(project: Project) -> OutputFormat:
    """Frame size and rate from ``project.export`` (decision 1: "match" is the frame
    rate of the first track-0 clip whose source is not a bookend; 30 when none)."""
    settings = project.export
    height = even(settings.height)
    width = even(round_half_up(height * OUTPUT_ASPECT))
    if settings.fps != "match":
        fps = Fraction(repr(float(settings.fps)))
    else:
        sources = {s.id: s for s in project.sources}
        fps = FALLBACK_FPS
        for span in clip_spans(project.clips):
            clip = project.clips[span.index]
            source = sources.get(clip.source_id)
            if source is not None and not source.external:
                fps = Fraction(source.fps_num, source.fps_den)
                break
    if fps <= 0:
        raise ExportError("the export frame rate must be above 0")
    return OutputFormat(width=width, height=height, fps=fps)


def frame_count(ms: int, fmt: OutputFormat) -> int:
    """Output frames that start before ``ms`` (round half up of ms * fps)."""
    return round_half_up(Fraction(ms) * fmt.fps / 1000)


def sample_count(ms: int, rate: int = SAMPLE_RATE) -> int:
    return round_half_up(Fraction(ms * rate, 1000))


def atempo_chain(speed: float) -> list[str]:
    """``atempo`` factors (each 0.5 to 2) whose product is the speed; [] at 1x."""
    rest = speed_fraction(speed)
    factors: list[Fraction] = []
    while rest > ATEMPO_MAX:
        factors.append(ATEMPO_MAX)
        rest /= ATEMPO_MAX
    while rest < ATEMPO_MIN:
        factors.append(ATEMPO_MIN)
        rest /= ATEMPO_MIN
    if rest != 1:
        factors.append(rest)
    return [f"atempo={_decimal(f)}" for f in factors]


def _decimal(value: Fraction) -> str:
    text = f"{float(value):.9f}".rstrip("0").rstrip(".")
    return text or "0"


def build_edit_graph(
    project: Project,
    source_paths: Mapping[str, Path],
    fmt: OutputFormat,
    *,
    first_input: int = 0,
    total_ms: int | None = None,
) -> EditGraph:
    """The edit graph of the project's track-0 clips. ``source_paths`` maps a source
    id to its file on disk; ``first_input`` is the ffmpeg input index of the first
    clip (inputs given before the clips, such as the avatar pipe, come first).
    ``total_ms`` past the end of the footage (lane or audio clips run on, M8-2) pads
    the edit with black frames and silence up to it."""
    sources = {s.id: s for s in project.sources}
    w, h = fmt.width, fmt.height
    inputs: list[ClipInput] = []
    filters: list[str] = []
    pads: list[str] = []
    skipped: list[str] = []
    spans = clip_spans(project.clips)
    for span in spans:
        clip = project.clips[span.index]
        source = sources.get(clip.source_id)
        path = source_paths.get(clip.source_id)
        if source is None or path is None:
            raise ExportError(f"the footage of clip {clip.id} cannot be found")
        frames = frame_count(span.end_ms, fmt) - frame_count(span.start_ms, fmt)
        samples = sample_count(span.end_ms, fmt.sample_rate) - sample_count(
            span.start_ms, fmt.sample_rate
        )
        if frames <= 0:
            skipped.append(clip.id)
            continue
        k = len(inputs)
        index = first_input + k
        frozen = clip.freeze_ms is not None
        if frozen:
            # A freeze frame: decode a moment from its frame, keep that one frame and
            # clone it to the clip's length below; its sound is silence.
            inputs.append(ClipInput(clip.id, path, clip.freeze_ms or 0, FREEZE_READ_MS))
        else:
            inputs.append(
                ClipInput(clip.id, path, clip.in_ms, clip.out_ms - clip.in_ms)
            )
        speed = speed_fraction(clip.speed)
        try:
            effects = [video_filter_for(e.type, e.params) for e in clip.effects]
        except ClipEffectError as exc:
            raise ExportError(str(exc)) from exc
        video = [
            *(["trim=end_frame=1"] if frozen else []),
            f"setpts=(PTS-STARTPTS)*{speed.denominator}/{speed.numerator}",
            f"fps={fmt.fps_text}",
            f"scale={w}:{h}:force_original_aspect_ratio=decrease",
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black",
            "setsar=1",
            "format=yuv420p",
            *effects,
            f"tpad=stop_mode=clone:stop={frames}",
            f"trim=end_frame={frames}",
            "setpts=PTS-STARTPTS",
        ]
        filters.append(f"[{index}:v:0]" + ",".join(video) + f"[v{k}]")
        tail = [
            f"aresample={fmt.sample_rate}",
            "aformat=sample_fmts=fltp:channel_layouts=stereo",
            "apad",
            f"atrim=end_sample={samples}",
            "asetpts=PTS-STARTPTS",
        ]
        if source.audio_tracks > 0 and not frozen:
            audio = ["asetpts=PTS-STARTPTS", *atempo_chain(clip.speed), *tail]
            filters.append(f"[{index}:a:0]" + ",".join(audio) + f"[a{k}]")
        else:
            filters.append(
                f"anullsrc=r={fmt.sample_rate}:cl=stereo,atrim=end_sample={samples}[a{k}]"
            )
        pads.append(f"[v{k}][a{k}]")
    if not inputs:
        raise ExportError("the timeline has no clips to export")
    footage_ms = spans[-1].end_ms
    total = footage_ms if total_ms is None else max(total_ms, footage_ms)
    concat = f"concat=n={len(inputs)}:v=1:a=1"
    if total > footage_ms:
        extra = frame_count(total, fmt) - frame_count(footage_ms, fmt)
        filters.append("".join(pads) + f"{concat}[vcat][acat]")
        filters.append(
            f"[vcat]tpad=stop_mode=add:stop={extra}:color=black[{VIDEO_LABEL}]"
        )
        filters.append(
            f"[acat]apad=whole_len={sample_count(total, fmt.sample_rate)}[{AUDIO_LABEL}]"
        )
    else:
        filters.append("".join(pads) + f"{concat}[{VIDEO_LABEL}][{AUDIO_LABEL}]")
    return EditGraph(
        inputs=inputs,
        filters=filters,
        video=VIDEO_LABEL,
        audio=AUDIO_LABEL,
        frames=frame_count(total, fmt),
        samples=sample_count(total, fmt.sample_rate),
        duration_ms=total,
        skipped=skipped,
    )


def limit_clips(project: Project, limit_ms: int) -> Project:
    """A copy of the project whose track-0 clips stop at ``limit_ms`` of the timeline (a
    short test export). Clips after the limit are dropped; the clip across it is cut,
    its source out point scaled by its speed. Other tracks and everything else stay."""
    if limit_ms <= 0:
        raise ExportError("the export length must be above 0")
    spans = {span.index: span for span in clip_spans(project.clips)}
    kept = []
    for index, clip in enumerate(project.clips):
        span = spans.get(index)
        if span is None:
            kept.append(clip)
            continue
        if span.start_ms >= limit_ms:
            continue
        if span.end_ms > limit_ms:
            source_ms = round_half_up((limit_ms - span.start_ms) * speed_fraction(clip.speed))
            clip = clip.model_copy(update={"out_ms": max(clip.in_ms + 1, clip.in_ms + source_ms)})
        kept.append(clip)
    return project.model_copy(update={"clips": kept})


def edited_video_args(
    ffmpeg: Path, graph: EditGraph, script_path: Path, dest: Path, fmt: OutputFormat
) -> list[str]:
    """One ffmpeg run writing only the edited video (no avatar, no voice). The graph
    is read from ``script_path`` (``-/filter_complex``), so its length never hits the
    Windows command-line limit."""
    return [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-y",
        *graph.input_args(),
        "-/filter_complex",
        str(script_path),
        "-map",
        f"[{graph.video}]",
        "-map",
        f"[{graph.audio}]",
        "-r",
        fmt.fps_text,
        *VIDEO_ENCODE_ARGS,
        *AUDIO_ENCODE_ARGS,
        "-movflags",
        "+faststart",
        str(dest),
    ]
