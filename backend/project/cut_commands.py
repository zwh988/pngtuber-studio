"""Cut commands on timeline track 0 (M2-3, part 2): split, trim, ripple-delete.

Pure: mutates the in-memory ``Project`` only. Follows the command contract in
``commands.py`` (validate first, raise ``CommandError`` before changing
anything, record undo data, ``apply`` can run again after ``revert``).

Rules (see PROJECT_STATE.md decision log, M2):
- Cut points and trim edges snap to the nearest frame of the clip's source;
  the source's own start and end are never snapped.
- A clip must stay at least one source frame long.
- Splitting: the left half keeps the original clip id, the right half gets a
  new id. Anchored items at or after the cut move to the right half.
- Trimming or deleting footage that timed items are anchored to flags them
  ``orphaned`` and parks them at the nearest surviving clip edge
  (``backend/project/parking.py``). Undo restores anchors and flags exactly.
"""

from dataclasses import dataclass, field
from typing import Literal

from backend.edl.anchoring import AnchoredItem, anchored_items
from backend.edl.timemap import (
    clip_spans,
    snap_to_frame,
    timeline_duration,
    to_source,
    to_timeline,
)
from backend.project.clip_commands import _find_timeline_clip, _min_clip_ms
from backend.project.commands import Command, CommandError, _find_source
from backend.project.parking import (
    ParkedItem,
    collect_cut_away,
    park_cut_away,
    restore_parked,
)
from backend.project.schema import Anchor, Clip, Project, Source, new_id

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _snap_source(source: Source, ms: int) -> int:
    """Snap a source time to the frame grid. 0 and the source's end stay as is."""
    if ms <= 0:
        return 0
    if ms >= source.duration_ms:
        return source.duration_ms
    snapped = snap_to_frame(ms, source.fps_num, source.fps_den)
    return min(snapped, source.duration_ms)


def _clamped_cut(source: Source, clip: Clip, ms: int) -> int:
    """Snapped cut point, kept inside the clip's own ``[in_ms, out_ms]``."""
    return min(max(_snap_source(source, ms), clip.in_ms), clip.out_ms)


def _timeline_at(project: Project, clip_id: str, source_ms: int) -> int:
    """Timeline time of a source time in a track-0 clip (accepts ``out_ms``)."""
    when = to_timeline(project.clips, Anchor(clip_id=clip_id, source_ms=source_ms))
    if when is None:
        raise CommandError(f"source time {source_ms} is outside clip {clip_id!r}")
    return when


def _split_clip(
    project: Project,
    list_index: int,
    clip: Clip,
    left_out: int,
    right_in: int,
    right_id: str,
) -> list[AnchoredItem]:
    """Cut ``clip`` into ``[in, left_out)`` (keeps its id) and ``[right_in, out)``
    (new clip right after it). Items anchored at or after ``right_in`` move to the
    right half; the moved items are returned for undo."""
    right = clip.model_copy(deep=True, update={"id": right_id, "in_ms": right_in})
    moved = [
        item
        for item in anchored_items(project, clip.id)
        if item.anchor.source_ms >= right_in
    ]
    clip.out_ms = left_out
    project.clips.insert(list_index + 1, right)
    for item in moved:
        item.anchor.clip_id = right_id
    return moved


def _unsplit(
    project: Project,
    clip: Clip,
    right_id: str,
    old_out: int,
    moved: list[AnchoredItem],
) -> None:
    for item in moved:
        item.anchor.clip_id = clip.id
    for index, candidate in enumerate(project.clips):
        if candidate.id == right_id:
            del project.clips[index]
            break
    else:
        raise CommandError("right half not found: command was not applied")
    clip.out_ms = old_out


# --------------------------------------------------------------------------
# SplitClip
# --------------------------------------------------------------------------


class SplitClip(Command):
    """Split the clip under ``timeline_ms`` into two.

    Refused at an existing cut, outside the timeline, or when either half would
    be shorter than one source frame. Splitting orphans nothing: items move to
    the right half by source time.
    """

    def __init__(self, timeline_ms: int, *, right_clip_id: str | None = None) -> None:
        self.timeline_ms = timeline_ms
        self.right_clip_id = right_clip_id if right_clip_id is not None else new_id()
        self._left_id: str | None = None
        self._old_out = 0
        self._moved: list[AnchoredItem] = []

    @property
    def label(self) -> str:
        return "Split clip"

    def apply(self, project: Project) -> None:
        spans = clip_spans(project.clips)
        span = next(
            (s for s in spans if s.start_ms <= self.timeline_ms < s.end_ms), None
        )
        if span is None:
            raise CommandError(f"time {self.timeline_ms} ms is outside the timeline")
        if self.timeline_ms == span.start_ms:
            raise CommandError("there is already a cut at that time")
        if any(c.id == self.right_clip_id for c in project.clips):
            raise CommandError(f"clip id {self.right_clip_id!r} already exists")
        clip = project.clips[span.index]
        _, source = _find_source(project, clip.source_id)
        anchor = to_source(project.clips, self.timeline_ms, spans=spans)
        if anchor is None:
            raise CommandError(f"time {self.timeline_ms} ms is outside the timeline")
        point = _clamped_cut(source, clip, anchor.source_ms)
        minimum = _min_clip_ms(source)
        if point - clip.in_ms < minimum or clip.out_ms - point < minimum:
            raise CommandError("the split would leave less than one frame in a clip")
        self._left_id = clip.id
        self._old_out = clip.out_ms
        self._moved = _split_clip(
            project, span.index, clip, point, point, self.right_clip_id
        )

    def revert(self, project: Project) -> None:
        if self._left_id is None:
            raise CommandError("nothing to restore: command was not applied")
        _, clip = _find_timeline_clip(project, self._left_id)
        _unsplit(project, clip, self.right_clip_id, self._old_out, self._moved)


# --------------------------------------------------------------------------
# TrimClip
# --------------------------------------------------------------------------


class TrimClip(Command):
    """Move a clip's ``in`` or ``out`` edge to a source time.

    The value is snapped to the source's frame grid (not at 0 or the source's
    end). Trimming can also extend a clip back out to reveal more footage. Later
    clips ripple. Items anchored in footage that is trimmed away are flagged
    orphaned and parked at the nearest surviving clip edge.
    """

    def __init__(
        self, clip_id: str, edge: Literal["in", "out"], source_ms: int
    ) -> None:
        self.clip_id = clip_id
        self.edge = edge
        self.source_ms = source_ms
        self._old: int | None = None
        self._parked: list[ParkedItem] = []

    @property
    def label(self) -> str:
        return "Trim clip"

    def apply(self, project: Project) -> None:
        if self.edge not in ("in", "out"):
            raise CommandError(f"edge must be 'in' or 'out', not {self.edge!r}")
        _, clip = _find_timeline_clip(project, self.clip_id)
        _, source = _find_source(project, clip.source_id)
        value = _snap_source(source, self.source_ms)
        minimum = _min_clip_ms(source)
        cut: tuple[int, int] | None  # source range that is trimmed away
        if self.edge == "in":
            if value > clip.out_ms - minimum:
                raise CommandError("the trim would leave less than one frame")
            if value == clip.in_ms:
                raise CommandError("the clip already starts there")
            cut = (clip.in_ms, value) if value > clip.in_ms else None
        else:
            if value < clip.in_ms + minimum:
                raise CommandError("the trim would leave less than one frame")
            if value == clip.out_ms:
                raise CommandError("the clip already ends there")
            cut = (value, clip.out_ms) if value < clip.out_ms else None

        cuts: list[tuple[str, int, int | None]] = []
        region_start = region_end = 0
        if cut is not None:
            region_start = _timeline_at(project, clip.id, cut[0])
            region_end = _timeline_at(project, clip.id, cut[1])
            cuts.append((clip.id, cut[0], cut[1]))
        cut_away = collect_cut_away(project, cuts, region_start)

        if self.edge == "in":
            self._old = clip.in_ms
            clip.in_ms = value
        else:
            self._old = clip.out_ms
            clip.out_ms = value
        self._parked = park_cut_away(
            project, cut_away, cut_ms=region_start, region_ms=region_end - region_start
        )

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        _, clip = _find_timeline_clip(project, self.clip_id)
        if self.edge == "in":
            clip.in_ms = self._old
        else:
            clip.out_ms = self._old
        restore_parked(self._parked)
        self._parked = []


# --------------------------------------------------------------------------
# RippleDelete
# --------------------------------------------------------------------------


@dataclass
class _Op:
    """One clip's part of a ripple-delete (also its undo data)."""

    kind: Literal["remove", "trim_in", "trim_out", "split"]
    clip: Clip
    list_index: int
    old_in: int
    old_out: int
    region_start: int  # old timeline ms where this clip's removed footage starts
    region_end: int  # old timeline ms where it ends
    cut_start: int = 0  # source ms where the removed footage starts
    cut_end: int = 0  # source ms where the removed footage ends
    moved: list[AnchoredItem] = field(default_factory=list)


class RippleDelete(Command):
    """Delete the timeline range ``[start_ms, end_ms)`` and close the gap.

    Clips fully inside the range are removed, partly covered clips are trimmed,
    and a clip that strictly contains the range is split in two (the left half
    keeps the id, the right half gets ``right_clip_id``). Items anchored in the
    removed footage are flagged orphaned and parked at the nearest surviving
    clip edge; items after a split move to the right half.
    """

    def __init__(
        self, start_ms: int, end_ms: int, *, right_clip_id: str | None = None
    ) -> None:
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.right_clip_id = right_clip_id if right_clip_id is not None else new_id()
        self._ops: list[_Op] = []
        self._parked: list[ParkedItem] = []

    @property
    def label(self) -> str:
        return "Ripple delete"

    def apply(self, project: Project) -> None:
        spans = clip_spans(project.clips)
        total = timeline_duration(project.clips)
        if not 0 <= self.start_ms < self.end_ms <= total:
            raise CommandError(
                f"range {self.start_ms}..{self.end_ms} ms must be non-empty and "
                f"lie within 0..{total} ms"
            )
        if any(c.id == self.right_clip_id for c in project.clips):
            raise CommandError(f"clip id {self.right_clip_id!r} already exists")

        def point(source: Source, clip: Clip, timeline_ms: int) -> int:
            anchor = to_source(project.clips, timeline_ms, spans=spans)
            if anchor is None:
                raise CommandError(f"time {timeline_ms} ms is outside the timeline")
            return _clamped_cut(source, clip, anchor.source_ms)

        sliver = (
            "deleting this range would leave less than one frame of a clip; "
            "extend the range to cover it or shorten it"
        )
        ops: list[_Op] = []
        cuts: list[tuple[str, int, int | None]] = []
        for span in spans:
            if span.end_ms <= self.start_ms or span.start_ms >= self.end_ms:
                continue
            clip = project.clips[span.index]
            _, source = _find_source(project, clip.source_id)
            minimum = _min_clip_ms(source)
            covers_left = self.start_ms <= span.start_ms
            covers_right = self.end_ms >= span.end_ms
            if covers_left and covers_right:
                cuts.append((clip.id, 0, None))
                ops.append(
                    _Op(
                        "remove",
                        clip,
                        span.index,
                        clip.in_ms,
                        clip.out_ms,
                        region_start=span.start_ms,
                        region_end=span.end_ms,
                    )
                )
            elif covers_left:
                cut_end = point(source, clip, self.end_ms)
                if cut_end <= clip.in_ms:
                    continue  # less than one frame of this clip: nothing to remove
                if clip.out_ms - cut_end < minimum:
                    raise CommandError(sliver)
                cuts.append((clip.id, clip.in_ms, cut_end))
                ops.append(
                    _Op(
                        "trim_in",
                        clip,
                        span.index,
                        clip.in_ms,
                        clip.out_ms,
                        region_start=span.start_ms,
                        region_end=_timeline_at(project, clip.id, cut_end),
                        cut_end=cut_end,
                    )
                )
            elif covers_right:
                cut_start = point(source, clip, self.start_ms)
                if cut_start >= clip.out_ms:
                    continue
                if cut_start - clip.in_ms < minimum:
                    raise CommandError(sliver)
                cuts.append((clip.id, cut_start, clip.out_ms))
                ops.append(
                    _Op(
                        "trim_out",
                        clip,
                        span.index,
                        clip.in_ms,
                        clip.out_ms,
                        region_start=_timeline_at(project, clip.id, cut_start),
                        region_end=span.end_ms,
                        cut_start=cut_start,
                    )
                )
            else:
                cut_start = point(source, clip, self.start_ms)
                cut_end = point(source, clip, self.end_ms)
                if cut_end <= cut_start:
                    continue
                if (
                    cut_start - clip.in_ms < minimum
                    or clip.out_ms - cut_end < minimum
                ):
                    raise CommandError(sliver)
                cuts.append((clip.id, cut_start, cut_end))
                ops.append(
                    _Op(
                        "split",
                        clip,
                        span.index,
                        clip.in_ms,
                        clip.out_ms,
                        region_start=_timeline_at(project, clip.id, cut_start),
                        region_end=_timeline_at(project, clip.id, cut_end),
                        cut_start=cut_start,
                        cut_end=cut_end,
                    )
                )
        if not ops:
            raise CommandError(
                "the range is shorter than one frame of the footage; "
                "nothing to delete"
            )

        # Validation is done. The removed footage is one contiguous stretch of
        # the old timeline; items inside it are collected before anything moves.
        region_start = ops[0].region_start
        region_end = ops[-1].region_end
        cut_away = collect_cut_away(project, cuts, region_start)

        # Apply from the highest list index down so the recorded indices stay
        # valid.
        for op in reversed(ops):
            if op.kind == "remove":
                del project.clips[op.list_index]
            elif op.kind == "trim_in":
                op.clip.in_ms = op.cut_end
            elif op.kind == "trim_out":
                op.clip.out_ms = op.cut_start
            else:
                op.moved = _split_clip(
                    project,
                    op.list_index,
                    op.clip,
                    op.cut_start,
                    op.cut_end,
                    self.right_clip_id,
                )
        self._ops = ops
        self._parked = park_cut_away(
            project, cut_away, cut_ms=region_start, region_ms=region_end - region_start
        )

    def revert(self, project: Project) -> None:
        if not self._ops:
            raise CommandError("nothing to restore: command was not applied")
        # Exact reverse of the order used in apply: lowest list index first.
        for op in self._ops:
            if op.kind == "remove":
                project.clips.insert(op.list_index, op.clip)
            elif op.kind == "trim_in":
                op.clip.in_ms = op.old_in
            elif op.kind == "trim_out":
                op.clip.out_ms = op.old_out
            else:
                _unsplit(project, op.clip, self.right_clip_id, op.old_out, op.moved)
        restore_parked(self._parked)
        self._parked = []
