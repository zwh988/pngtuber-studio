"""Keyed values of an image lane clip (keyframes task, step 6). Pure.

A clip property (x, y, scale, opacity) with keys follows them; one without keys keeps
the clip's own value. Keys are in ms from the clip start and are evaluated with the
avatar lane maths (``backend.avatar.lanes.Lane``: hold before the first key and after
the last, the key's easing and strength in between, the last of two keys at one time
wins). ``frontend/src/clipKeys.ts`` is the same evaluation for the preview; both are
checked against ``tests/fixtures/clip_key_cases.json`` (rule 5: preview equals export).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from backend.avatar.lanes import Lane, LaneKey
from backend.project.schema import CLIP_KEY_PROPERTIES, ClipKey, LaneClip


@dataclass(frozen=True)
class ClipValues:
    x: float
    y: float
    scale: float
    opacity: float


def clip_lane(keys: Sequence[ClipKey], prop: str, base: float) -> Lane:
    """One property's keys as a lane in clip time (keys in their stored order)."""
    return Lane(
        [
            LaneKey(key.t_ms, key.value, key.interpolation, key.ease_strength)
            for key in keys
            if key.prop == prop
        ],
        base,
    )


def clip_values_at(clip: LaneClip, timeline_ms: float) -> ClipValues:
    """The clip's x, y, scale and opacity at a timeline time."""
    clip_ms = timeline_ms - clip.timeline_ms
    values = {
        prop: clip_lane(clip.keys, prop, getattr(clip, prop)).value_at(clip_ms)
        for prop in CLIP_KEY_PROPERTIES
    }
    return ClipValues(**values)


def keyed_props(clip: LaneClip) -> set[str]:
    """The properties that change over the clip (the export animates only these)."""
    return {key.prop for key in clip.keys}
