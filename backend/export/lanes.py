"""Video-lane clips in the export (M8-2). Pure: paths come in, argument lists and filter
text go out.

Every visible lane clip is its own ffmpeg input (an image looped for its length, a
recording opened with ``-ss`` / ``-t``, a freeze frame read for a moment and held). Its
picture is fitted into the frame like the main footage, scaled by the clip's ``scale``
around its centre at (``x``, ``y``) (``pip_rect``, the same maths as the preview's
``pipRect`` in ``frontend/src/videoLanes.ts``), given its opacity, and shifted to start
at the clip's timeline time. The clips are overlaid on the edited footage bottom lane
first; the lanes from ``Project.avatar_below_lane_id`` up go over the avatar, the rest
under it (``LaneLayer.over_avatar``). A recording's own sound (not muted, not a freeze
frame) is delayed to its start at the clip's level and joins the final mix.

Times follow the edit graph: a clip covers the output frames ``frame_count(start)`` to
``frame_count(end)``, so lane clips line up with the footage frame for frame.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from backend.edl.timemap import round_half_up, timeline_duration
from backend.export.editgraph import OutputFormat, frame_count, sample_count, seconds
from backend.export.errors import ExportError
from backend.project.schema import LaneClip, Project

# How much of the recording a freeze frame's input decodes (ms): enough for one frame.
FREEZE_READ_MS = 250


@dataclass(frozen=True)
class PipRect:
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class LaneInput:
    clip_id: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class LaneLayer:
    """One prepared lane clip picture, ready to overlay."""

    clip_id: str
    label: str
    left: int
    top: int
    start_frame: int
    end_frame: int
    over_avatar: bool


@dataclass(frozen=True)
class LaneGraph:
    inputs: list[LaneInput] = field(default_factory=list)
    filters: list[str] = field(default_factory=list)  # picture and sound preparation
    layers: list[LaneLayer] = field(default_factory=list)  # bottom lane first
    audio: list[str] = field(default_factory=list)  # labels of the sound chains

    def input_args(self) -> list[str]:
        return [arg for item in self.inputs for arg in item.args]


def program_end_ms(project: Project) -> int:
    """Where the timeline ends: the last of the main footage, the audio clips and the
    video-lane clips (as the preview's playhead, decision 2026-11-20)."""
    ends = [timeline_duration(project.clips)]
    ends += [clip.end_ms for clip in project.audio_clips]
    ends += [clip.end_ms for clip in project.lane_clips]
    return max(ends)


def pip_rect(
    frame_w: int,
    frame_h: int,
    media_w: int,
    media_h: int,
    x: float,
    y: float,
    scale: float,
) -> PipRect:
    """Where a lane clip's picture goes in the frame (pixels, rounded half up, at least
    2 x 2): fitted into the frame, times ``scale``, centred at (x, y) as fractions."""
    if frame_w <= 0 or frame_h <= 0 or media_w <= 0 or media_h <= 0:
        raise ExportError("a lane clip's picture has no size")
    fit = min(Fraction(frame_w, media_w), Fraction(frame_h, media_h)) * Fraction(
        repr(scale)
    )
    width = max(2, round_half_up(media_w * fit))
    height = max(2, round_half_up(media_h * fit))
    return PipRect(
        left=round_half_up(Fraction(repr(x)) * frame_w - Fraction(width, 2)),
        top=round_half_up(Fraction(repr(y)) * frame_h - Fraction(height, 2)),
        width=width,
        height=height,
    )


def _setpts_from(start_frame: int, fmt: OutputFormat) -> str:
    """Timestamps from 0, then shifted to the clip's first output frame."""
    return f"setpts=PTS-STARTPTS+{start_frame}*{fmt.fps.denominator}/{fmt.fps.numerator}/TB"


def build_lane_graph(
    project: Project,
    source_paths: Mapping[str, Path],
    image_paths: Mapping[str, Path],
    fmt: OutputFormat,
    total_ms: int,
    *,
    first_input: int,
) -> LaneGraph:
    """The lane clips of ``project`` up to ``total_ms``. ``first_input`` is the ffmpeg
    input index of the first lane clip (after the footage clips)."""
    graph = LaneGraph()
    lanes = {lane.id: (index, lane) for index, lane in enumerate(project.video_lanes)}
    over_from = len(project.video_lanes)
    if (
        project.avatar_below_lane_id is not None
        and project.avatar_below_lane_id in lanes
    ):
        over_from = lanes[project.avatar_below_lane_id][0]
    sources = {s.id: s for s in project.sources}
    images = {i.id: i for i in project.image_files}
    total_samples = sample_count(total_ms, fmt.sample_rate)

    def order(clip: LaneClip) -> tuple[int, int]:
        return (lanes[clip.lane_id][0], clip.timeline_ms)

    shown = [
        c
        for c in project.lane_clips
        if c.lane_id in lanes
        and not lanes[c.lane_id][1].hidden
        and c.timeline_ms < total_ms
    ]
    for clip in sorted(shown, key=order):
        end_ms = min(clip.end_ms, total_ms)
        start_frame = frame_count(clip.timeline_ms, fmt)
        frames = frame_count(end_ms, fmt) - start_frame
        if frames <= 0:
            continue
        length_ms = end_ms - clip.timeline_ms
        if clip.image_id is not None:
            image = images.get(clip.image_id)
            path = image_paths.get(clip.image_id)
            if image is None or path is None:
                raise ExportError(f"the image of lane clip {clip.id} cannot be found")
            media = (image.width, image.height)
            args: tuple[str, ...] = (
                "-loop", "1", "-framerate", fmt.fps_text,
                "-t", seconds(length_ms), "-i", str(path),
            )  # fmt: skip
            has_sound = False
        else:
            source = sources.get(clip.source_id or "")
            path = source_paths.get(clip.source_id or "")
            if source is None or path is None:
                raise ExportError(
                    f"the recording of lane clip {clip.id} cannot be found"
                )
            media = (source.width, source.height)
            if clip.freeze_ms is not None:
                args = (
                    "-ss",
                    seconds(clip.freeze_ms),
                    "-t",
                    seconds(FREEZE_READ_MS),
                    "-i",
                    str(path),
                )
            else:
                args = (
                    "-ss",
                    seconds(clip.in_ms),
                    "-t",
                    seconds(length_ms),
                    "-i",
                    str(path),
                )
            has_sound = (
                source.audio_tracks > 0 and not clip.mute and clip.freeze_ms is None
            )
        k = len(graph.inputs)
        index = first_input + k
        graph.inputs.append(LaneInput(clip.id, args))
        rect = pip_rect(
            fmt.width, fmt.height, media[0], media[1], clip.x, clip.y, clip.scale
        )
        chain = [
            *(["trim=end_frame=1"] if clip.freeze_ms is not None else []),
            "setpts=PTS-STARTPTS",
            f"fps={fmt.fps_text}",
            f"scale={rect.width}:{rect.height}",
            "setsar=1",
            "format=rgba",
            *([f"colorchannelmixer=aa={clip.opacity:.4f}"] if clip.opacity < 1 else []),
            # One spare frame: the overlay ends a stream at its last frame's time, so
            # without it the clip's last frame would not show; ``enable`` hides the spare.
            f"tpad=stop_mode=clone:stop={frames + 1}",
            f"trim=end_frame={frames + 1}",
            _setpts_from(start_frame, fmt),
        ]
        label = f"lane{k}"
        graph.filters.append(f"[{index}:v:0]" + ",".join(chain) + f"[{label}]")
        graph.layers.append(
            LaneLayer(
                clip_id=clip.id,
                label=label,
                left=rect.left,
                top=rect.top,
                start_frame=start_frame,
                end_frame=start_frame + frames,
                over_avatar=lanes[clip.lane_id][0] >= over_from,
            )
        )
        if has_sound:
            start = sample_count(clip.timeline_ms, fmt.sample_rate)
            length = sample_count(end_ms, fmt.sample_rate) - start
            sound = [
                "asetpts=PTS-STARTPTS",
                f"aresample={fmt.sample_rate}",
                "aformat=sample_fmts=fltp:channel_layouts=stereo",
                f"volume={clip.gain_db:.2f}dB",
                "apad",
                f"atrim=end_sample={length}",
                f"adelay=delays={start}S:all=1",
                "apad",
                f"atrim=end_sample={total_samples}",
            ]
            audio_label = f"lanea{k}"
            graph.filters.append(
                f"[{index}:a:0]" + ",".join(sound) + f"[{audio_label}]"
            )
            graph.audio.append(audio_label)
    return graph


def overlay_steps(
    base: str, layers: list[LaneLayer], out: str, fmt: OutputFormat, prefix: str
) -> list[str]:
    """Filters that draw ``layers`` in order over ``[base]``, ending in ``[out]``
    (a plain copy when there are none). Each layer shows only over its own frames."""
    if not layers:
        return [f"[{base}]null[{out}]"]
    steps: list[str] = []
    current = base
    for n, layer in enumerate(layers):
        target = out if n == len(layers) - 1 else f"{prefix}{n}"
        start = f"{layer.start_frame}*{fmt.fps.denominator}/{fmt.fps.numerator}"
        end = f"{layer.end_frame}*{fmt.fps.denominator}/{fmt.fps.numerator}"
        steps.append(
            f"[{current}][{layer.label}]overlay=x={layer.left}:y={layer.top}:"
            f"eof_action=pass:format=auto:enable='gte(t,{start})*lt(t,{end})'[{target}]"
        )
        current = target
    return steps
