"""Keys on image lane clips (keyframes task, decisions 3 and 5; schema v9). Pure.

A key sits at ``t_ms`` from the clip's start on one of x, y, scale, opacity. The
commands take TIMELINE times (like the avatar keys) and store clip times. Each
command replaces the whole clip, so undo puts it back exactly.

- ``KeyLaneClip``: set a property at a time; changes that property's key within
  ``KEY_NEAR_MS`` (one frame) of it, else adds one.
- ``MoveClipKey``, ``SetClipKey`` (value, easing, strength), ``RemoveClipKey``.
  Removing a property's last key leaves the clip's own value at that key's value, so
  the picture does not jump.
"""

import math

from backend.avatar.lanes import (
    EASE_STRENGTH_MAX,
    EASE_STRENGTH_MIN,
    INTERPOLATIONS,
    Interpolation,
)
from backend.project.avatar_commands import KEY_NEAR_MS
from backend.project.commands import CommandError
from backend.project.line_commands import NoChange
from backend.project.schema import (
    CLIP_KEY_PROPERTIES,
    CLIP_KEY_RANGES,
    ClipKey,
    LaneClip,
    Project,
    new_id,
)
from backend.project.video_lane_commands import _build, _ReplaceLaneClip

# Opacity fades read best at a steady rate; moves and resizes ease (decision 3).
DEFAULT_CLIP_INTERPOLATION: dict[str, Interpolation] = {
    "x": "ease_in_out",
    "y": "ease_in_out",
    "scale": "ease_in_out",
    "opacity": "linear",
}


def _check_prop(prop: str) -> str:
    if prop not in CLIP_KEY_PROPERTIES:
        raise CommandError(f"a clip key is one of {', '.join(CLIP_KEY_PROPERTIES)}")
    return prop


def check_clip_value(prop: str, value: float) -> float:
    lo, hi = CLIP_KEY_RANGES[_check_prop(prop)]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandError("a clip key needs a number")
    number = float(value)
    if not math.isfinite(number) or not lo <= number <= hi:
        raise CommandError(f"{prop} must be between {lo:g} and {hi:g}")
    return round(number, 4)


def _check_keyable(clip: LaneClip) -> None:
    if clip.image_id is None:
        raise CommandError("only image clips can have keys for now")


def clip_key_near(clip: LaneClip, prop: str, clip_ms: int) -> ClipKey | None:
    """The property's key nearest a clip time, within ``KEY_NEAR_MS``; ties go to
    the earlier key."""
    best: ClipKey | None = None
    for key in clip.keys:
        if key.prop != prop:
            continue
        gap = abs(key.t_ms - clip_ms)
        if gap <= KEY_NEAR_MS and (best is None or gap < abs(best.t_ms - clip_ms)):
            best = key
    return best


def _find_key(clip: LaneClip, key_id: str) -> ClipKey:
    for key in clip.keys:
        if key.id == key_id:
            return key
    raise CommandError(f"unknown clip key id {key_id!r}")


def _sorted(keys: list[ClipKey]) -> list[dict[str, object]]:
    ordered = sorted(keys, key=lambda k: (CLIP_KEY_PROPERTIES.index(k.prop), k.t_ms, k.id))
    return [key.model_dump() for key in ordered]


class KeyLaneClip(_ReplaceLaneClip):
    """Set a clip property at a timeline time: edit the key there or add one."""

    def __init__(
        self,
        clip_id: str,
        prop: str,
        timeline_ms: int,
        value: float,
        *,
        key_id: str | None = None,
    ) -> None:
        self.clip_id = clip_id
        self.prop = _check_prop(prop)
        self.value = check_clip_value(prop, value)
        self.timeline_ms = timeline_ms
        self.key_id = key_id or new_id()

    @property
    def label(self) -> str:
        return "Key clip"

    def changed(self, project: Project, clip: LaneClip) -> LaneClip:
        _check_keyable(clip)
        clip_ms = self.timeline_ms - clip.timeline_ms
        if not 0 <= clip_ms <= clip.length_ms:
            raise CommandError("the playhead is not on the clip")
        near = clip_key_near(clip, self.prop, clip_ms)
        keys = list(clip.keys)
        if near is not None:
            if near.value == self.value:
                raise NoChange("the key already has that value")
            keys = [k.model_copy(update={"value": self.value}) if k is near else k for k in keys]
        else:
            keys.append(
                ClipKey(
                    id=self.key_id,
                    prop=self.prop,  # type: ignore[arg-type]
                    t_ms=clip_ms,
                    value=self.value,
                    interpolation=DEFAULT_CLIP_INTERPOLATION[self.prop],
                )
            )
        return _build(clip, keys=_sorted(keys))


class MoveClipKey(_ReplaceLaneClip):
    """Move a clip key to a timeline time (inside the clip)."""

    def __init__(self, clip_id: str, key_id: str, timeline_ms: int) -> None:
        self.clip_id = clip_id
        self.key_id = key_id
        self.timeline_ms = timeline_ms

    @property
    def label(self) -> str:
        return "Move clip key"

    def changed(self, project: Project, clip: LaneClip) -> LaneClip:
        key = _find_key(clip, self.key_id)
        clip_ms = self.timeline_ms - clip.timeline_ms
        if not 0 <= clip_ms <= clip.length_ms:
            raise CommandError("a clip key stays on its clip")
        if clip_ms == key.t_ms:
            raise NoChange("the key is already there")
        moved = [k.model_copy(update={"t_ms": clip_ms}) if k is key else k for k in clip.keys]
        return _build(clip, keys=_sorted(moved))


class SetClipKey(_ReplaceLaneClip):
    """Change a clip key's value, easing and/or ease strength (None: unchanged)."""

    def __init__(
        self,
        clip_id: str,
        key_id: str,
        *,
        value: float | None = None,
        interpolation: Interpolation | None = None,
        ease_strength: float | None = None,
    ) -> None:
        if value is None and interpolation is None and ease_strength is None:
            raise CommandError("nothing to change")
        if interpolation is not None and interpolation not in INTERPOLATIONS:
            raise CommandError(f"easing must be one of {', '.join(INTERPOLATIONS)}")
        if ease_strength is not None and not (
            math.isfinite(ease_strength)
            and EASE_STRENGTH_MIN <= ease_strength <= EASE_STRENGTH_MAX
        ):
            raise CommandError(
                f"ease strength must be {EASE_STRENGTH_MIN:g} to {EASE_STRENGTH_MAX:g}"
            )
        self.clip_id = clip_id
        self.key_id = key_id
        self.value = value
        self.interpolation = interpolation
        self.ease_strength = ease_strength

    @property
    def label(self) -> str:
        return "Change clip key" if self.value is not None else "Change clip key easing"

    def changed(self, project: Project, clip: LaneClip) -> LaneClip:
        key = _find_key(clip, self.key_id)
        update: dict[str, object] = {}
        if self.value is not None:
            update["value"] = check_clip_value(key.prop, self.value)
        if self.interpolation is not None:
            update["interpolation"] = self.interpolation
        if self.ease_strength is not None:
            update["ease_strength"] = float(self.ease_strength)
        if all(getattr(key, name) == wanted for name, wanted in update.items()):
            raise NoChange("the key already has that")
        keys = [k.model_copy(update=update) if k is key else k for k in clip.keys]
        return _build(clip, keys=_sorted(keys))


class RemoveClipKey(_ReplaceLaneClip):
    """Remove a clip key; the last one of a property leaves its value on the clip."""

    def __init__(self, clip_id: str, key_id: str) -> None:
        self.clip_id = clip_id
        self.key_id = key_id

    @property
    def label(self) -> str:
        return "Remove clip key"

    def changed(self, project: Project, clip: LaneClip) -> LaneClip:
        key = _find_key(clip, self.key_id)
        keys = [k for k in clip.keys if k is not key]
        changes: dict[str, object] = {"keys": _sorted(keys)}
        if not any(k.prop == key.prop for k in keys):
            changes[key.prop] = key.value
        return _build(clip, **changes)
