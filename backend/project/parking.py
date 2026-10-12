"""Orphan parking for the clip commands (M2-5).

Pure in the sense of CLAUDE.md: it changes in-memory ``Project`` objects only
and does no file or network access. The decisions about *where* to park live in
``backend/edl/anchoring.py``; this module collects the affected items, applies
the result, and keeps what is needed to undo it exactly.

How a command uses it:
1. Before changing any clip: ``collect_cut_away`` (needs the old timeline).
2. Change the clips.
3. ``park_cut_away`` (needs the new clip list). Keep the returned list.
4. On revert, put the clips back and call ``restore_parked`` with that list.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from backend.edl.anchoring import AnchoredItem, items_in_source_range, park_anchor
from backend.edl.timemap import clip_spans, to_timeline
from backend.project.schema import Anchor, Project


@dataclass
class ParkedItem:
    """An item that was flagged and parked, with its state from before."""

    item: AnchoredItem
    old_anchor: Anchor
    old_orphaned: bool


@dataclass(frozen=True)
class CutAway:
    """Items about to lose their footage.

    ``offsets[i]`` is how far (old timeline ms) ``items[i]`` sat from the start
    of the removed footage.
    """

    items: tuple[AnchoredItem, ...]
    offsets: tuple[int, ...]


def collect_cut_away(
    project: Project,
    cuts: Sequence[tuple[str, int, int | None]],
    region_start_ms: int,
) -> CutAway:
    """Find the items anchored in the source ranges that are about to be cut.

    ``cuts`` holds ``(clip_id, lo, hi)`` source ranges (``lo`` inclusive, ``hi``
    exclusive, ``None`` for no upper bound). ``region_start_ms`` is the old
    timeline time where the removed footage starts. Call this *before* the clips
    change.
    """
    spans = clip_spans(project.clips)
    items: list[AnchoredItem] = []
    offsets: list[int] = []
    for clip_id, lo, hi in cuts:
        for item in items_in_source_range(project, clip_id, lo, hi):
            when = to_timeline(project.clips, item.anchor, spans=spans)
            items.append(item)
            offsets.append(0 if when is None else max(0, when - region_start_ms))
    return CutAway(items=tuple(items), offsets=tuple(offsets))


def park_cut_away(
    project: Project,
    cut_away: CutAway,
    *,
    cut_ms: int,
    region_ms: int,
) -> list[ParkedItem]:
    """Flag every collected item ``orphaned`` and move it to its nearest edge.

    Call this *after* the clips changed. ``cut_ms`` is the timeline time of the
    cut (the old start of the removed footage) and ``region_ms`` the length of
    the removed footage in the old timeline. When no clip survives, the item
    keeps its anchor and is only flagged (``check_references`` reports it).
    """
    spans = clip_spans(project.clips)
    parked: list[ParkedItem] = []
    for item, offset in zip(cut_away.items, cut_away.offsets, strict=True):
        target = park_anchor(project.clips, cut_ms, offset, region_ms, spans=spans)
        parked.append(ParkedItem(item, item.anchor.model_copy(), item.orphaned))
        if target is not None:
            item.anchor = target
        item.orphaned = True
    return parked


def restore_parked(parked: Sequence[ParkedItem]) -> None:
    """Put every parked item back exactly as it was."""
    for entry in reversed(parked):
        entry.item.anchor = entry.old_anchor.model_copy()
        entry.item.orphaned = entry.old_orphaned
