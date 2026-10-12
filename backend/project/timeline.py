"""Pure timeline state for the editor (M2-S6a).

``build_timeline`` turns a Project into what the editor draws: track-0 clips
with their timeline spans and source info, total duration, reference problems,
orphan count and undo/redo status. No file or network access: whether a source
file is missing on disk is passed in by the caller.
"""

from collections.abc import Collection

from pydantic import BaseModel, Field

from backend.edl.anchoring import check_references, find_orphans
from backend.edl.timemap import clip_spans, timeline_duration
from backend.project.schema import Project


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


class TimelineState(BaseModel):
    clips: list[TimelineClip] = Field(default_factory=list)
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
    # clip_spans covers track 0 only, in list order, so the loop counter is
    # the track-0 position.
    for position, span in enumerate(clip_spans(project.clips)):
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
