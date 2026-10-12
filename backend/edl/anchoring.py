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
    """One broken reference. ``owner_id`` is the clip or item that holds it and
    ``missing_id`` the source or clip it points at."""

    kind: Literal["clip_missing_source", "item_missing_clip"]
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
