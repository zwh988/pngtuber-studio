"""Pure time mapping between source time and timeline time.

The timeline is track 0 of ``Project.clips``: a gapless sequence in list
order (there are no start times). Clips on other tracks are ignored here.

All times are integer milliseconds. Rounding is always half up (never Python's
banker's rounding, never floor), computed with exact integer/Fraction math so
results are deterministic. This module does no file or network access.

Rules (see PROJECT_STATE.md decision log, M2-S1):
- A clip's timeline length is ``round((out - in) / speed)``.
- Source -> timeline: ``start + round((source_ms - in) / speed)``.
- Timeline -> source: ``in + round((t - start) * speed)``, clamped to
  ``out - 1`` so the result is always a valid anchor.
- An anchor is valid when ``in <= source_ms < out``; ``source_ms == out`` is
  accepted by ``to_timeline`` and maps to the clip's end.
- Cut points and trims snap to the source's frame grid (``snap_to_frame``);
  playheads and anchors never snap.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import floor

from backend.project.schema import Anchor, Clip

TIMELINE_TRACK = 0


# --------------------------------------------------------------------------
# Rounding and frame helpers
# --------------------------------------------------------------------------


def round_half_up(value: Fraction | int) -> int:
    """Round to the nearest integer, ties toward +infinity."""
    return floor(Fraction(value) + Fraction(1, 2))


def speed_fraction(speed: float) -> Fraction:
    """Exact decimal value of a speed (``repr`` is the shortest round-trip text)."""
    return Fraction(repr(float(speed)))


def ms_to_frame(ms: int, fps_num: int, fps_den: int) -> int:
    """Nearest frame index for a time (ties round up)."""
    return round_half_up(Fraction(ms * fps_num, 1000 * fps_den))


def frame_to_ms(frame: int, fps_num: int, fps_den: int) -> int:
    """Time in ms of a frame index, rounded to the nearest ms (ties round up)."""
    return round_half_up(Fraction(frame * 1000 * fps_den, fps_num))


def snap_to_frame(ms: int, fps_num: int, fps_den: int) -> int:
    """Snap a time to the nearest frame of a source with the given frame rate."""
    return frame_to_ms(ms_to_frame(ms, fps_num, fps_den), fps_num, fps_den)


# --------------------------------------------------------------------------
# Spans
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ClipSpan:
    """Where one clip sits on the timeline."""

    clip_id: str
    index: int  # position in the ``clips`` list that was passed in
    start_ms: int
    end_ms: int
    in_ms: int
    out_ms: int
    speed: float

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def clip_duration_ms(clip: Clip) -> int:
    """Timeline length of a clip at its speed."""
    return round_half_up(Fraction(clip.out_ms - clip.in_ms) / speed_fraction(clip.speed))


def clip_spans(clips: Sequence[Clip]) -> list[ClipSpan]:
    """Timeline start and end of every track-0 clip, in list order."""
    spans: list[ClipSpan] = []
    cursor = 0
    for index, clip in enumerate(clips):
        if clip.track != TIMELINE_TRACK:
            continue
        end = cursor + clip_duration_ms(clip)
        spans.append(
            ClipSpan(
                clip_id=clip.id,
                index=index,
                start_ms=cursor,
                end_ms=end,
                in_ms=clip.in_ms,
                out_ms=clip.out_ms,
                speed=clip.speed,
            )
        )
        cursor = end
    return spans


def timeline_duration(clips: Sequence[Clip]) -> int:
    """Total length of the timeline in ms (0 when empty)."""
    spans = clip_spans(clips)
    return spans[-1].end_ms if spans else 0


# --------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------


def to_timeline(
    clips: Sequence[Clip],
    anchor: Anchor,
    *,
    spans: Sequence[ClipSpan] | None = None,
) -> int | None:
    """Timeline time of an anchor, or ``None``.

    ``None`` means the clip is not on track 0 of this list, or ``source_ms``
    lies outside ``[in_ms, out_ms]`` (the anchor's footage was cut away).
    Pass ``spans`` (from ``clip_spans``) to avoid recomputing them.
    """
    if spans is None:
        spans = clip_spans(clips)
    for span in spans:
        if span.clip_id != anchor.clip_id:
            continue
        if not span.in_ms <= anchor.source_ms <= span.out_ms:
            return None
        offset = Fraction(anchor.source_ms - span.in_ms) / speed_fraction(span.speed)
        return span.start_ms + round_half_up(offset)
    return None


def to_source(
    clips: Sequence[Clip],
    timeline_ms: int,
    *,
    spans: Sequence[ClipSpan] | None = None,
) -> Anchor | None:
    """Anchor for a timeline time, or ``None``.

    ``None`` when ``timeline_ms`` is outside ``[0, duration)`` (the very end
    of the timeline belongs to no clip). At a boundary the time belongs to the
    clip that starts there.
    """
    if spans is None:
        spans = clip_spans(clips)
    for span in spans:
        if not span.start_ms <= timeline_ms < span.end_ms:
            continue
        offset = Fraction(timeline_ms - span.start_ms) * speed_fraction(span.speed)
        source_ms = min(span.in_ms + round_half_up(offset), span.out_ms - 1)
        return Anchor(clip_id=span.clip_id, source_ms=source_ms)
    return None
