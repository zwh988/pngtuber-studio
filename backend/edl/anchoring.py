"""Pure orphan and reference logic for anchored items (M2-5).

Placements, keyframes and reactions are anchored to (clip_id, source_ms). When
an edit cuts away the footage an item points at, the item is flagged
``orphaned`` and parked at the nearest surviving clip edge (see PROJECT_STATE.md
decision log, M2).

Nothing here changes a project or touches files: the functions only read and
compute. The commands apply the results (see ``backend/project/parking.py``).

"Nearest" is measured in the *old* timeline, from where the item used to be to
the two ends of the removed footage. A tie goes to the earlier edge. The
earlier edge is the last frame of the clip before the cut (``out_ms - 1``); the
later edge is the first frame of the clip after it (``in_ms``). After a ripple
edit both edges sit at the same new timeline time.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from backend.edl.timemap import ClipSpan, clip_spans
from backend.project.schema import (
    Anchor,
    Clip,
    Keyframe,
    Placement,
    Project,
    Reaction,
)

AnchoredItem = Placement | Keyframe | Reaction


# --------------------------------------------------------------------------
# Finding items
# --------------------------------------------------------------------------


def anchored_items(project: Project, clip_id: str | None = None) -> list[AnchoredItem]:
    """Every placement, keyframe and reaction (in that order), optionally only
    those anchored to ``clip_id``."""
    items: list[AnchoredItem] = [
        *project.placements,
        *project.keyframes,
        *project.reactions,
    ]
    if clip_id is None:
        return items
    return [item for item in items if item.anchor.clip_id == clip_id]


def items_in_source_range(
    project: Project, clip_id: str, lo: int, hi: int | None
) -> list[AnchoredItem]:
    """Items anchored to ``clip_id`` with ``lo <= source_ms < hi``.
    ``hi=None`` means no upper bound."""
    return [
        item
        for item in anchored_items(project, clip_id)
        if item.anchor.source_ms >= lo and (hi is None or item.anchor.source_ms < hi)
    ]


def item_kind(item: AnchoredItem) -> str:
    if isinstance(item, Placement):
        return "placement"
    if isinstance(item, Keyframe):
        return "keyframe"
    return "reaction"


def find_orphans(project: Project) -> list[AnchoredItem]:
    """Items currently flagged ``orphaned`` (for the export pre-flight)."""
    return [item for item in anchored_items(project) if item.orphaned]


# --------------------------------------------------------------------------
# Parking
# --------------------------------------------------------------------------


def edge_anchors(
    clips: Sequence[Clip],
    cut_ms: int,
    *,
    spans: Sequence[ClipSpan] | None = None,
) -> tuple[Anchor | None, Anchor | None]:
    """The surviving footage on each side of a cut at timeline time ``cut_ms``.

    Returns ``(before, after)``. ``before`` is the last valid source time of the
    last clip ending at or before the cut (``out_ms - 1``); ``after`` is the
    start of the first clip starting at or after it (``in_ms``). Either is
    ``None`` when there is no footage on that side. Pass ``spans`` (from
    ``clip_spans``) to avoid recomputing them.
    """
    if spans is None:
        spans = clip_spans(clips)
    before: Anchor | None = None
    after: Anchor | None = None
    for span in spans:
        if span.duration_ms <= 0:
            continue
        if span.end_ms <= cut_ms:
            before = Anchor(clip_id=span.clip_id, source_ms=span.out_ms - 1)
        elif span.start_ms >= cut_ms and after is None:
            after = Anchor(clip_id=span.clip_id, source_ms=span.in_ms)
    return before, after


def park_anchor(
    clips: Sequence[Clip],
    cut_ms: int,
    offset_ms: int,
    region_ms: int,
    *,
    spans: Sequence[ClipSpan] | None = None,
) -> Anchor | None:
    """Where an orphaned item should be parked, or ``None`` if no clip survives.

    ``clips`` is the list *after* the edit and ``cut_ms`` the timeline time of
    the cut. ``offset_ms`` is how far the item was from the start of the removed
    footage, and ``region_ms`` the length of the removed footage, both measured
    in the old timeline. The nearer edge wins; a tie goes to the earlier edge.
    """
    before, after = edge_anchors(clips, cut_ms, spans=spans)
    if before is None:
        return after
    if after is None:
        return before
    region = max(region_ms, 0)
    offset = min(max(offset_ms, 0), region)
    return before if offset <= region - offset else after


# --------------------------------------------------------------------------
# Reference check
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceProblem:
    """One broken reference. ``owner_id`` is the clip, item, line, take or
    placement that holds it and ``missing_id`` what it points at."""

    kind: Literal[
        "clip_missing_source",
        "item_missing_clip",
        "take_missing_line",
        "line_missing_take",
        "placement_missing_line",
        "placement_missing_take",
    ]
    owner_id: str
    missing_id: str
    message: str


def check_references(project: Project) -> list[ReferenceProblem]:
    """List broken references. Reports only; never changes the project and never
    makes an old file unloadable."""
    problems: list[ReferenceProblem] = []
    source_ids = {source.id for source in project.sources}
    for clip in project.clips:
        if clip.source_id not in source_ids:
            problems.append(
                ReferenceProblem(
                    kind="clip_missing_source",
                    owner_id=clip.id,
                    missing_id=clip.source_id,
                    message=(
                        f"clip {clip.id} points at missing source {clip.source_id}"
                    ),
                )
            )
    clip_ids = {clip.id for clip in project.clips}
    for item in anchored_items(project):
        if item.anchor.clip_id not in clip_ids:
            problems.append(
                ReferenceProblem(
                    kind="item_missing_clip",
                    owner_id=item.id,
                    missing_id=item.anchor.clip_id,
                    message=(
                        f"{item_kind(item)} {item.id} is anchored to missing clip "
                        f"{item.anchor.clip_id}"
                    ),
                )
            )
    return problems


def check_voice_references(project: Project) -> list[ReferenceProblem]:
    """Broken links between lines, takes and placements (M3). Reports only.

    Kept apart from ``check_references`` so the M2 checks (and the tests that
    build placements without lines) are unchanged.
    """
    problems: list[ReferenceProblem] = []
    line_ids = {line.id for line in project.lines}
    takes = {take.id: take for take in project.takes}
    for take in project.takes:
        if take.line_id not in line_ids:
            problems.append(
                ReferenceProblem(
                    kind="take_missing_line",
                    owner_id=take.id,
                    missing_id=take.line_id,
                    message=f"take {take.id} belongs to missing line {take.line_id}",
                )
            )
    for line in project.lines:
        if line.active_take_id is None:
            continue
        active = takes.get(line.active_take_id)
        if active is None or active.line_id != line.id:
            problems.append(
                ReferenceProblem(
                    kind="line_missing_take",
                    owner_id=line.id,
                    missing_id=line.active_take_id,
                    message=(
                        f"line {line.id} has active take {line.active_take_id}, "
                        "which is missing or belongs to another line"
                    ),
                )
            )
    for placement in project.placements:
        if placement.line_id not in line_ids:
            problems.append(
                ReferenceProblem(
                    kind="placement_missing_line",
                    owner_id=placement.id,
                    missing_id=placement.line_id,
                    message=(
                        f"placement {placement.id} points at missing line "
                        f"{placement.line_id}"
                    ),
                )
            )
        override = placement.take_override_id
        if override is None:
            continue
        chosen = takes.get(override)
        if chosen is None or chosen.line_id != placement.line_id:
            problems.append(
                ReferenceProblem(
                    kind="placement_missing_take",
                    owner_id=placement.id,
                    missing_id=override,
                    message=(
                        f"placement {placement.id} overrides with take {override}, "
                        "which is missing or belongs to another line"
                    ),
                )
            )
    return problems
