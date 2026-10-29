"""Pure timeline state for the editor (M2-S6a).

``build_timeline`` turns a Project into what the editor draws: track-0 clips
with their timeline spans and source info, total duration, reference problems,
orphan count and undo/redo status. No file or network access: whether a source
file is missing on disk is passed in by the caller.
"""

from collections.abc import Collection, Sequence

from pydantic import BaseModel, Field

from backend.edl.anchoring import check_references, find_orphans
from backend.edl.timemap import ClipSpan, clip_spans, timeline_duration, to_timeline
from backend.project.schema import Project
from backend.voice.overflow import PlacedLine, available_slack_ms, find_overflows
from backend.voice.stretch import fit_stretch, stretched_duration_ms


class TimelineSource(BaseModel):
    id: str
    external: bool
    fps_num: int
    fps_den: int
    fps: float
    width: int
    height: int
    duration_ms: int
    file_missing: bool


class TimelineClip(BaseModel):
    id: str
    # Position among track-0 clips (the unit the clip commands use).
    position: int
    source_id: str
    start_ms: int
    end_ms: int
    duration_ms: int
    in_ms: int
    out_ms: int
    speed: float
    overlay: bool
    # None when the clip points at a source that is not in the project.
    source: TimelineSource | None


class TimelineProblem(BaseModel):
    kind: str
    owner_id: str
    missing_id: str
    message: str


class TimelinePlacement(BaseModel):
    """A placed line as the editor draws it on the voice lane."""

    id: str
    line_id: str
    # Empty when the line no longer exists (reported by check_voice_references).
    line_text: str
    allow_overlap: bool
    # The take that plays: the placement's override, else the line's active take.
    # None when neither exists, so the block has no audio to show.
    take_id: str | None
    duration_ms: int | None
    # Timeline time of the anchor; None when its clip is not on track 0 or the
    # source time lies outside the clip (nothing to draw).
    start_ms: int | None
    end_ms: int | None
    anchor_clip_id: str
    anchor_source_ms: int
    orphaned: bool
    # How far this line's audio runs past the start of the next playable line
    # (ms); 0 when it does not. Set by ``mark_overflows``. The editor warns only
    # when this is above 0 and ``allow_overlap`` is false (CLAUDE.md rule 10).
    overflow_ms: int = 0
    overflow_next_id: str | None = None
    # How far earlier this line could start before it touches the previous playing
    # line (or the timeline start). Only filled in when ``overflow_ms`` is above 0.
    slack_ms: int = 0
    # Tighten (schema v2). ``duration_ms`` above is the length that PLAYS (the take's
    # length divided by ``stretch``); ``raw_duration_ms`` is the take as recorded.
    stretch: float = 1.0
    raw_duration_ms: int | None = None
    # The stretch that would remove this line's overflow exactly; None when it does
    # not overflow or no stretch can fix it. May be above the allowed maximum.
    fit_stretch: float | None = None


class TimelineState(BaseModel):
    clips: list[TimelineClip] = Field(default_factory=list)
    # Placed lines, ordered by start time (unmappable ones last).
    placements: list[TimelinePlacement] = Field(default_factory=list)
    duration_ms: int = 0
    # Clips on tracks other than 0: kept by every command, not shown in M2.
    other_track_clips: int = 0
    orphan_count: int = 0
    problems: list[TimelineProblem] = Field(default_factory=list)
    can_undo: bool = False
    can_redo: bool = False
    undo_label: str | None = None
    redo_label: str | None = None
    # Set by the session when the last automatic save failed.
    save_error: str | None = None


class EditResult(BaseModel):
    """Result of undo or redo: what was undone or redone, and the new state."""

    # None when there was nothing to undo or redo.
    label: str | None
    timeline: TimelineState


def build_timeline(
    project: Project,
    *,
    can_undo: bool = False,
    can_redo: bool = False,
    undo_label: str | None = None,
    redo_label: str | None = None,
    missing_source_ids: Collection[str] = (),
) -> TimelineState:
    missing = set(missing_source_ids)
    sources = {
        source.id: TimelineSource(
            id=source.id,
            external=source.external,
            fps_num=source.fps_num,
            fps_den=source.fps_den,
            fps=source.fps,
            width=source.width,
            height=source.height,
            duration_ms=source.duration_ms,
            file_missing=source.id in missing,
        )
        for source in project.sources
    }
    by_id = {clip.id: clip for clip in project.clips}
    clips: list[TimelineClip] = []
    spans = clip_spans(project.clips)
    # clip_spans covers track 0 only, in list order, so the loop counter is
    # the track-0 position.
    for position, span in enumerate(spans):
        clip = by_id[span.clip_id]
        clips.append(
            TimelineClip(
                id=clip.id,
                position=position,
                source_id=clip.source_id,
                start_ms=span.start_ms,
                end_ms=span.end_ms,
                duration_ms=span.duration_ms,
                in_ms=clip.in_ms,
                out_ms=clip.out_ms,
                speed=clip.speed,
                overlay=clip.overlay,
                source=sources.get(clip.source_id),
            )
        )
    return TimelineState(
        clips=clips,
        placements=_build_placements(project, spans),
        duration_ms=timeline_duration(project.clips),
        other_track_clips=sum(1 for clip in project.clips if clip.track != 0),
        orphan_count=len(find_orphans(project)),
        problems=[
            TimelineProblem(
                kind=str(problem.kind),
                owner_id=problem.owner_id,
                missing_id=problem.missing_id,
                message=problem.message,
            )
            for problem in check_references(project)
        ],
        can_undo=can_undo,
        can_redo=can_redo,
        undo_label=undo_label,
        redo_label=redo_label,
    )


def _build_placements(
    project: Project, spans: Sequence[ClipSpan]
) -> list[TimelinePlacement]:
    lines = {line.id: line for line in project.lines}
    takes = {take.id: take for take in project.takes}
    shown: list[TimelinePlacement] = []
    for placement in project.placements:
        line = lines.get(placement.line_id)
        take = None
        if placement.take_override_id is not None:
            take = takes.get(placement.take_override_id)
        if take is None and line is not None and line.active_take_id is not None:
            take = takes.get(line.active_take_id)
        start = to_timeline(project.clips, placement.anchor, spans=spans)
        raw_duration = None if take is None else take.duration_ms
        duration = (
            None
            if raw_duration is None
            else stretched_duration_ms(raw_duration, placement.stretch)
        )
        end = None if start is None or duration is None else start + duration
        shown.append(
            TimelinePlacement(
                id=placement.id,
                line_id=placement.line_id,
                line_text="" if line is None else line.text,
                allow_overlap=False if line is None else line.allow_overlap,
                take_id=None if take is None else take.id,
                duration_ms=duration,
                start_ms=start,
                end_ms=end,
                anchor_clip_id=placement.anchor.clip_id,
                anchor_source_ms=placement.anchor.source_ms,
                orphaned=placement.orphaned,
                stretch=placement.stretch,
                raw_duration_ms=raw_duration,
            )
        )
    shown.sort(key=lambda p: (p.start_ms is None, p.start_ms or 0, p.id))
    return mark_overflows(shown)


def mark_overflows(placements: Sequence[TimelinePlacement]) -> list[TimelinePlacement]:
    """Copy of the placements with ``overflow_ms`` set where a line runs into the next.

    Only lines that play count: orphaned blocks, blocks without a take and blocks
    that cannot be mapped to the timeline are left out of the comparison (they make
    no sound, see ``planVoices``). Lines with ``allow_overlap`` still get the number;
    the caller decides whether to warn.
    """
    items = [
        PlacedLine(p.id, p.start_ms, p.duration_ms, p.allow_overlap)
        for p in placements
        if p.start_ms is not None and p.duration_ms is not None and not p.orphaned
    ]
    found = {o.placement_id: o for o in find_overflows(items)}
    return [
        p.model_copy(
            update={
                "overflow_ms": found[p.id].overflow_ms,
                "overflow_next_id": found[p.id].next_placement_id,
                "slack_ms": available_slack_ms(items, p.id),
                "fit_stretch": (
                    None
                    if p.raw_duration_ms is None or p.duration_ms is None
                    else fit_stretch(
                        p.raw_duration_ms, p.duration_ms, found[p.id].overflow_ms
                    )
                ),
            }
        )
        if p.id in found
        else p
        for p in placements
    ]
