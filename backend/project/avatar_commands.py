"""Avatar commands (M5-1, M5-5): art folder, settings, keyframes and reactions. Pure.

Keyframes and reactions are anchored to footage (rule 4): a command takes a
**timeline** time, turns it into an anchor (clip id plus source time) on the first
``apply`` and reuses that anchor on redo, like the placement commands. Cuts that
remove the footage under them flag and park them (the M2 parking code already
covers ``Keyframe`` and ``Reaction``); moving an orphan settles it.

Values are checked against the lane table (``backend/avatar/lanes.py``): numeric lanes
take a number inside the lane's range, the expression lane a non-empty name, which
is resolved against the art only when drawn (so a key survives a change of art).
"""

import math
from typing import Literal

from backend.avatar.lanes import EXPRESSION, LANES_BY_ID, Lane, LaneKey
from backend.avatar.solver import REACTIONS
from backend.edl.timemap import to_source, to_timeline
from backend.project.commands import Command, CommandError
from backend.project.line_commands import NoChange
from backend.project.schema import (
    Anchor,
    AvatarSettings,
    Keyframe,
    Project,
    Reaction,
    new_id,
)

Interpolation = Literal["hold", "smooth"]
KeyValue = float | str

# New transform keys ease (decision 14); expression keys always hold.
SMOOTH_BY_DEFAULT = frozenset({"x", "y", "scale", "rotation"})
REACTION_MAX_MS = 10_000
REACTION_MAX_INTENSITY = 3.0


class SetAvatarArtFolder(Command):
    """Point the project at an avatar art folder (stored path) or clear it (None)."""

    def __init__(self, art_folder: str | None) -> None:
        self.art_folder = art_folder
        self._old: str | None = None
        self._applied = False

    @property
    def label(self) -> str:
        return "Clear avatar art" if self.art_folder is None else "Set avatar art"

    def apply(self, project: Project) -> None:
        if project.avatar.art_folder == self.art_folder:
            raise NoChange("the project already uses that art folder")
        try:
            AvatarSettings(art_folder=self.art_folder)
        except ValueError as exc:
            raise CommandError(f"invalid art folder path: {exc}") from exc
        self._old = project.avatar.art_folder
        project.avatar.art_folder = self.art_folder
        self._applied = True

    def revert(self, project: Project) -> None:
        if not self._applied:
            raise CommandError("nothing to restore: command was not applied")
        project.avatar.art_folder = self._old


# --- helpers -------------------------------------------------------------------------


def _anchor_at(project: Project, timeline_ms: int) -> Anchor:
    if timeline_ms < 0:
        raise CommandError("timeline time must not be negative")
    anchor = to_source(project.clips, timeline_ms)
    if anchor is None:
        raise CommandError(f"there is no footage at {timeline_ms} ms on the timeline")
    return anchor


def default_interpolation(lane_id: str) -> Interpolation:
    return "smooth" if lane_id in SMOOTH_BY_DEFAULT else "hold"


def check_value(lane_id: str, value: KeyValue) -> KeyValue:
    """The value as stored, or ``CommandError`` (unknown lane, wrong type, range)."""
    spec = LANES_BY_ID.get(lane_id)
    if spec is None:
        raise CommandError(f"unknown lane {lane_id!r}")
    if spec.kind == "enum":
        if not isinstance(value, str) or not value.strip():
            raise CommandError("an expression key needs an expression name")
        return value.strip()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CommandError(f"the {spec.label} lane needs a number")
    number = float(value)
    if not math.isfinite(number) or not spec.minimum <= number <= spec.maximum:
        raise CommandError(
            f"{spec.label} must be between {spec.minimum:g} and {spec.maximum:g}"
        )
    return round(number, 4)


def _check_interpolation(lane_id: str, interpolation: Interpolation) -> Interpolation:
    if interpolation not in ("hold", "smooth"):
        raise CommandError("interpolation must be hold or smooth")
    if lane_id == EXPRESSION and interpolation != "hold":
        raise CommandError("expression keys always hold")
    return interpolation


def _find_key(project: Project, keyframe_id: str) -> tuple[int, Keyframe]:
    for index, key in enumerate(project.keyframes):
        if key.id == keyframe_id:
            return index, key
    raise CommandError(f"unknown keyframe id {keyframe_id!r}")


def _find_reaction(project: Project, reaction_id: str) -> tuple[int, Reaction]:
    for index, reaction in enumerate(project.reactions):
        if reaction.id == reaction_id:
            return index, reaction
    raise CommandError(f"unknown reaction id {reaction_id!r}")


def _check_reaction(type_: str, intensity: float, duration_ms: int) -> None:
    if type_ not in REACTIONS:
        raise CommandError(f"unknown reaction {type_!r}")
    if not (isinstance(intensity, (int, float)) and math.isfinite(intensity)):
        raise CommandError("intensity must be a number")
    if not 0.0 <= intensity <= REACTION_MAX_INTENSITY:
        raise CommandError(f"intensity must be between 0 and {REACTION_MAX_INTENSITY:g}")
    if not 1 <= duration_ms <= REACTION_MAX_MS:
        raise CommandError(f"a reaction lasts 1 to {REACTION_MAX_MS} ms")


# --- keyframes -----------------------------------------------------------------------


class AddKeyframe(Command):
    def __init__(
        self,
        lane_id: str,
        timeline_ms: int,
        value: KeyValue,
        interpolation: Interpolation | None = None,
        *,
        keyframe_id: str | None = None,
    ) -> None:
        self.lane_id = lane_id
        self.value = check_value(lane_id, value)
        self.interpolation = _check_interpolation(
            lane_id, interpolation or default_interpolation(lane_id)
        )
        self.timeline_ms = timeline_ms
        self.keyframe_id = keyframe_id if keyframe_id is not None else new_id()
        self._anchor: Anchor | None = None

    @property
    def label(self) -> str:
        return "Add expression key" if self.lane_id == EXPRESSION else "Add key"

    def apply(self, project: Project) -> None:
        if any(k.id == self.keyframe_id for k in project.keyframes):
            raise CommandError(f"keyframe id {self.keyframe_id!r} already exists")
        anchor = self._anchor or _anchor_at(project, self.timeline_ms)
        key = Keyframe(
            id=self.keyframe_id,
            lane_id=self.lane_id,
            anchor=anchor.model_copy(),
            value=self.value,
            interpolation=self.interpolation,
        )
        project.keyframes.append(key)
        self._anchor = anchor

    def revert(self, project: Project) -> None:
        index, _ = _find_key(project, self.keyframe_id)
        del project.keyframes[index]


class RemoveKeyframe(Command):
    def __init__(self, keyframe_id: str) -> None:
        self.keyframe_id = keyframe_id
        self._removed: Keyframe | None = None
        self._index = 0

    @property
    def label(self) -> str:
        return "Remove key"

    def apply(self, project: Project) -> None:
        index, key = _find_key(project, self.keyframe_id)
        self._removed = key.model_copy(deep=True)
        self._index = index
        del project.keyframes[index]

    def revert(self, project: Project) -> None:
        if self._removed is None:
            raise CommandError("nothing to restore: command was not applied")
        project.keyframes.insert(self._index, self._removed.model_copy(deep=True))


class _MoveAnchored(Command):
    """Shared by keyframe and reaction moves: a new anchor, and an orphan settles."""

    kind = ""

    def __init__(self, item_id: str, timeline_ms: int) -> None:
        self.item_id = item_id
        self.timeline_ms = timeline_ms
        self._anchor: Anchor | None = None
        self._old: tuple[Anchor, bool] | None = None

    def _find(self, project: Project) -> Keyframe | Reaction:
        raise NotImplementedError

    def apply(self, project: Project) -> None:
        item = self._find(project)
        anchor = self._anchor or _anchor_at(project, self.timeline_ms)
        if anchor == item.anchor and not item.orphaned:
            raise NoChange(f"the {self.kind} is already there")
        self._old = (item.anchor.model_copy(), item.orphaned)
        item.anchor = anchor.model_copy()
        item.orphaned = False
        self._anchor = anchor

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        item = self._find(project)
        item.anchor = self._old[0].model_copy()
        item.orphaned = self._old[1]


class MoveKeyframe(_MoveAnchored):
    kind = "key"

    @property
    def label(self) -> str:
        return "Move key"

    def _find(self, project: Project) -> Keyframe:
        return _find_key(project, self.item_id)[1]


class SetKeyframeValue(Command):
    def __init__(self, keyframe_id: str, value: KeyValue) -> None:
        self.keyframe_id = keyframe_id
        self.raw_value = value
        self._old: KeyValue | None = None

    @property
    def label(self) -> str:
        return "Change key"

    def apply(self, project: Project) -> None:
        _, key = _find_key(project, self.keyframe_id)
        value = check_value(key.lane_id, self.raw_value)
        if key.value == value:
            raise NoChange("the key already has that value")
        self._old = key.value
        key.value = value

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        _find_key(project, self.keyframe_id)[1].value = self._old


class SetKeyframeInterpolation(Command):
    def __init__(self, keyframe_id: str, interpolation: Interpolation) -> None:
        self.keyframe_id = keyframe_id
        self.interpolation = interpolation
        self._old: Interpolation | None = None

    @property
    def label(self) -> str:
        return "Change key easing"

    def apply(self, project: Project) -> None:
        _, key = _find_key(project, self.keyframe_id)
        wanted = _check_interpolation(key.lane_id, self.interpolation)
        if key.interpolation == wanted:
            raise NoChange("the key already has that easing")
        self._old = key.interpolation
        key.interpolation = wanted

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        _find_key(project, self.keyframe_id)[1].interpolation = self._old


class KeyLane(Command):
    """Set a lane's value at a timeline time: changes the key already exactly there
    (same lane, same anchor, not orphaned), else adds one. Used by the E hotkey and
    by dragging the avatar (decision 14)."""

    def __init__(
        self,
        lane_id: str,
        timeline_ms: int,
        value: KeyValue,
        *,
        keyframe_id: str | None = None,
    ) -> None:
        self.lane_id = lane_id
        self.timeline_ms = timeline_ms
        self.value = check_value(lane_id, value)
        self.keyframe_id = keyframe_id
        self._inner: Command | None = None

    @property
    def label(self) -> str:
        return "Add expression key" if self.lane_id == EXPRESSION else "Set key"

    def apply(self, project: Project) -> None:
        if self._inner is None:
            anchor = _anchor_at(project, self.timeline_ms)
            existing = next(
                (
                    k
                    for k in project.keyframes
                    if k.lane_id == self.lane_id and k.anchor == anchor and not k.orphaned
                ),
                None,
            )
            if existing is not None:
                self._inner = SetKeyframeValue(existing.id, self.value)
            else:
                add = AddKeyframe(
                    self.lane_id, self.timeline_ms, self.value, keyframe_id=self.keyframe_id
                )
                add._anchor = anchor
                self._inner = add
        self._inner.apply(project)

    def revert(self, project: Project) -> None:
        if self._inner is None:
            raise CommandError("nothing to restore: command was not applied")
        self._inner.revert(project)


def lane_value_at(project: Project, lane_id: str, timeline_ms: int) -> float:
    """A numeric lane's own value at a timeline time (keys mapped through the clip
    list, orphans left out), without motion or reactions: what a key would hold."""
    spec = LANES_BY_ID.get(lane_id)
    if spec is None or spec.kind != "number":
        raise CommandError(f"{lane_id!r} is not a numeric lane")
    base = {
        "x": project.avatar.x,
        "y": project.avatar.y,
        "scale": project.avatar.scale,
        "rotation": project.avatar.rotation_deg,
    }.get(lane_id, spec.default)
    keys = []
    for key in project.keyframes:
        if key.lane_id != lane_id or key.orphaned or isinstance(key.value, str):
            continue
        t = to_timeline(project.clips, key.anchor)
        if t is not None:
            keys.append(LaneKey(t, float(key.value), key.interpolation))
    return Lane(keys, base).value_at(timeline_ms)


class KeyLaneBy(Command):
    """Key a numeric lane at a time to (its value there) x ``factor`` + ``delta``,
    clamped to the lane's range. The avatar drag (x, y) and resize (scale) use it, so
    the browser never needs the lane maths (decision 14)."""

    def __init__(
        self, lane_id: str, timeline_ms: int, *, delta: float = 0.0, factor: float = 1.0
    ) -> None:
        if not (math.isfinite(delta) and math.isfinite(factor)) or factor <= 0:
            raise CommandError("the change must be a finite number (factor above 0)")
        self.lane_id = lane_id
        self.timeline_ms = timeline_ms
        self.delta = delta
        self.factor = factor
        self._inner: KeyLane | None = None

    @property
    def label(self) -> str:
        return "Set key"

    def apply(self, project: Project) -> None:
        if self._inner is None:
            spec = LANES_BY_ID.get(self.lane_id)
            current = lane_value_at(project, self.lane_id, self.timeline_ms)
            assert spec is not None
            value = min(spec.maximum, max(spec.minimum, current * self.factor + self.delta))
            self._inner = KeyLane(self.lane_id, self.timeline_ms, value)
        self._inner.apply(project)

    def revert(self, project: Project) -> None:
        if self._inner is None:
            raise CommandError("nothing to restore: command was not applied")
        self._inner.revert(project)


# --- reactions -----------------------------------------------------------------------


class AddReaction(Command):
    def __init__(
        self,
        type_: str,
        timeline_ms: int,
        intensity: float = 1.0,
        duration_ms: int = 500,
        *,
        reaction_id: str | None = None,
    ) -> None:
        _check_reaction(type_, intensity, duration_ms)
        self.type = type_
        self.timeline_ms = timeline_ms
        self.intensity = float(intensity)
        self.duration_ms = int(duration_ms)
        self.reaction_id = reaction_id if reaction_id is not None else new_id()
        self._anchor: Anchor | None = None

    @property
    def label(self) -> str:
        return "Add reaction"

    def apply(self, project: Project) -> None:
        if any(r.id == self.reaction_id for r in project.reactions):
            raise CommandError(f"reaction id {self.reaction_id!r} already exists")
        anchor = self._anchor or _anchor_at(project, self.timeline_ms)
        project.reactions.append(
            Reaction(
                id=self.reaction_id,
                type=self.type,  # type: ignore[arg-type]
                anchor=anchor.model_copy(),
                intensity=self.intensity,
                duration_ms=self.duration_ms,
            )
        )
        self._anchor = anchor

    def revert(self, project: Project) -> None:
        index, _ = _find_reaction(project, self.reaction_id)
        del project.reactions[index]


class RemoveReaction(Command):
    def __init__(self, reaction_id: str) -> None:
        self.reaction_id = reaction_id
        self._removed: Reaction | None = None
        self._index = 0

    @property
    def label(self) -> str:
        return "Remove reaction"

    def apply(self, project: Project) -> None:
        index, reaction = _find_reaction(project, self.reaction_id)
        self._removed = reaction.model_copy(deep=True)
        self._index = index
        del project.reactions[index]

    def revert(self, project: Project) -> None:
        if self._removed is None:
            raise CommandError("nothing to restore: command was not applied")
        project.reactions.insert(self._index, self._removed.model_copy(deep=True))


class MoveReaction(_MoveAnchored):
    kind = "reaction"

    @property
    def label(self) -> str:
        return "Move reaction"

    def _find(self, project: Project) -> Reaction:
        return _find_reaction(project, self.item_id)[1]


class SetReaction(Command):
    """Change a reaction's type, intensity and/or duration (None keeps a field)."""

    def __init__(
        self,
        reaction_id: str,
        *,
        type_: str | None = None,
        intensity: float | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self.reaction_id = reaction_id
        self.type = type_
        self.intensity = intensity
        self.duration_ms = duration_ms
        self._old: tuple[str, float, int] | None = None

    @property
    def label(self) -> str:
        return "Change reaction"

    def apply(self, project: Project) -> None:
        _, reaction = _find_reaction(project, self.reaction_id)
        old = (reaction.type, reaction.intensity, reaction.duration_ms)
        new = (
            old[0] if self.type is None else self.type,
            old[1] if self.intensity is None else float(self.intensity),
            old[2] if self.duration_ms is None else int(self.duration_ms),
        )
        _check_reaction(*new)
        if new == old:
            raise NoChange("the reaction already has those settings")
        self._old = old
        self._write(reaction, new)

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        self._write(_find_reaction(project, self.reaction_id)[1], self._old)

    @staticmethod
    def _write(reaction: Reaction, values: tuple[str, float, int]) -> None:
        reaction.type = values[0]  # type: ignore[assignment]
        reaction.intensity = values[1]
        reaction.duration_ms = values[2]


# --- settings ------------------------------------------------------------------------

SETTING_LANES = {"x": "x", "y": "y", "scale": "scale", "rotation_deg": "rotation"}


class SetAvatarSettings(Command):
    """Change the base transform and/or the auto-key switch (None keeps a field).
    Numbers use the matching lane's range."""

    def __init__(self, **changes: float | bool | None) -> None:
        allowed = {*SETTING_LANES, "auto_key_expression"}
        unknown = set(changes) - allowed
        if unknown:
            raise CommandError(f"unknown avatar setting(s): {', '.join(sorted(unknown))}")
        self.changes: dict[str, float | bool] = {}
        for name, value in changes.items():
            if value is None:
                continue
            if name == "auto_key_expression":
                if not isinstance(value, bool):
                    raise CommandError("auto_key_expression must be true or false")
                self.changes[name] = value
            else:
                self.changes[name] = float(check_value(SETTING_LANES[name], value))
        self._old: dict[str, float | bool] | None = None

    @property
    def label(self) -> str:
        return "Change avatar settings"

    def apply(self, project: Project) -> None:
        avatar = project.avatar
        old = {name: getattr(avatar, name) for name in self.changes}
        if old == self.changes:
            raise NoChange("the avatar already has those settings")
        for name, value in self.changes.items():
            setattr(avatar, name, value)
        self._old = old

    def revert(self, project: Project) -> None:
        if self._old is None:
            raise CommandError("nothing to restore: command was not applied")
        for name, value in self._old.items():
            setattr(project.avatar, name, value)
