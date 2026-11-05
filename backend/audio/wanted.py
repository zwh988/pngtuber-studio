"""Which processed takes the project plays (M4-1): the (take, stretch) pairs. Pure.

A placed line that is not orphaned plays the placement's override take, else the
line's active take, sped up by the placement's stretch. This list drives the
"processing N of M" count, the prefetch, and the clean-up of ``takes_fx``.
"""

from dataclasses import dataclass

from backend.project.schema import Project


@dataclass(frozen=True)
class PlayedTake:
    take_id: str
    raw_file: str  # project-relative path of the raw take
    raw_key: str
    stretch: float


def played_takes(project: Project) -> list[PlayedTake]:
    """Distinct (take, stretch) pairs, in the order the placements are stored.

    Orphaned placements make no sound and are left out, as are placements with no
    take to play. Two placements of one take at the same stretch need one file.
    """
    takes = {take.id: take for take in project.takes}
    active = {line.id: line.active_take_id for line in project.lines}
    seen: set[tuple[str, float]] = set()
    found: list[PlayedTake] = []
    for placement in project.placements:
        if placement.orphaned:
            continue
        take = None
        if placement.take_override_id is not None:
            take = takes.get(placement.take_override_id)
        if take is None:
            active_id = active.get(placement.line_id)
            take = None if active_id is None else takes.get(active_id)
        if take is None:
            continue
        key = (take.id, placement.stretch)
        if key in seen:
            continue
        seen.add(key)
        found.append(
            PlayedTake(take.id, take.raw_file, take.raw_key, placement.stretch)
        )
    return found
