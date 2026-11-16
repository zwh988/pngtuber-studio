"""From the project to what the preview draws (M5-6 backend, S10a). Pure.

``build_input`` turns the timeline state (anchors already mapped to timeline time),
the envelopes of the placed takes, the art and the emotion presets into a
``SolverInput``. ``input_version`` hashes everything that changes the picture, so the
browser and the server can tell when a frame track is stale (``avatar_version``).
``build_frame_track`` samples the solver at the preview frame rate into a compact,
quantised track: the canvas draws the nearest sample and never computes motion
(decision 13, rule 5). The export (M6) calls the same solver at its own frame rate.

Placement on the frame (decision 5): every sprite shares one full-frame canvas, so a
frame's transform applies to the whole sprite about its **bottom centre**: that point
sits at (x * width, y * height); at scale 1 the sprite is ``AVATAR_HEIGHT_FRACTION``
of the frame height tall; rotation turns it about the same point; squash makes it
(1 + squash) wider and (1 - squash) taller.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict

from pydantic import BaseModel, Field

from backend.avatar import tuning
from backend.avatar.art import AvatarArt, resolve_expression, sprite_for, state_code
from backend.avatar.autokey import auto_expression_keys
from backend.avatar.envelope import Envelope
from backend.avatar.lanes import EXPRESSION, NUMBER_LANES, ExpressionKey, LaneKey
from backend.avatar.solver import (
    BaseTransform,
    PlacedVoice,
    ReactionCue,
    Solver,
    SolverInput,
    build_solver,
)
from backend.project.schema import AvatarSettings, Project
from backend.project.timeline import TimelineState

TRACK_FPS = 30
AVATAR_HEIGHT_FRACTION = 0.6  # sprite height at scale 1, as a fraction of the frame
TRACK_VERSION = 1  # bump when the track format or the sampling changes


def build_input(
    project: Project,
    timeline: TimelineState,
    envelopes: Mapping[str, Envelope],
    art: AvatarArt | None,
    preset_expressions: Mapping[str, str],
) -> SolverInput:
    """``envelopes`` maps a placement id to the envelope of what it plays. Orphaned
    and unmappable items are left out (they are flagged in the UI, never dropped)."""
    avatar: AvatarSettings = project.avatar
    lanes: dict[str, list[LaneKey]] = {lane: [] for lane in NUMBER_LANES}
    manual: list[ExpressionKey] = []
    for key in timeline.keyframes:
        if key.orphaned or key.t_ms is None:
            continue
        if key.lane_id == EXPRESSION:
            if isinstance(key.value, str):
                name = key.value
                if art is not None:
                    name = resolve_expression(art, key.value)[0] or key.value
                manual.append(ExpressionKey(key.t_ms, name, manual=True))
        elif key.lane_id in lanes and not isinstance(key.value, str):
            interpolation = "smooth" if key.interpolation == "smooth" else "hold"
            lanes[key.lane_id].append(LaneKey(key.t_ms, float(key.value), interpolation))
    emotions = {line.id: line.emotion for line in project.lines}
    virtual = auto_expression_keys(
        timeline.placements,
        emotions,
        preset_expressions,
        art,
        enabled=avatar.auto_key_expression,
    )
    voices = [
        PlacedVoice(p.start_ms, envelopes[p.id])
        for p in timeline.placements
        if not p.orphaned and p.start_ms is not None and p.take_id is not None and p.id in envelopes
    ]
    reactions = [
        ReactionCue(r.t_ms, r.type, r.intensity, r.duration_ms)
        for r in timeline.reactions
        if not r.orphaned and r.t_ms is not None
    ]
    return SolverInput(
        duration_ms=timeline.duration_ms,
        seed=project.seed,
        base=BaseTransform(
            x=avatar.x,
            y=avatar.y,
            scale=avatar.scale,
            rotation_deg=avatar.rotation_deg,
            bounce=avatar.bounce,
            float_amp=avatar.float_amp,
            float_speed=avatar.float_speed,
            float_angle_deg=avatar.float_angle_deg,
            blink_rate=avatar.blink_rate,
            mouth_sensitivity=avatar.mouth_sensitivity,
        ),
        lanes={lane: keys for lane, keys in lanes.items() if keys},
        expression_keys=[*manual, *virtual],
        default_expression=None if art is None else art.default_expression,
        voices=voices,
        reactions=reactions,
    )


def input_version(inp: SolverInput, art: AvatarArt | None) -> str:
    """16 hex chars that change exactly when the picture can change: the solver
    input, the art's sprite files, the tuning constants and the track format."""
    sha = hashlib.sha256()

    def feed(obj: object) -> None:
        sha.update(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode())

    feed({"track": TRACK_VERSION, "fps": TRACK_FPS, "height": AVATAR_HEIGHT_FRACTION})
    feed({k: v for k, v in vars(tuning).items() if k.isupper()})
    feed([inp.duration_ms, inp.seed, asdict(inp.base), inp.default_expression])
    feed({lane: [asdict(k) for k in keys] for lane, keys in sorted(inp.lanes.items())})
    feed([asdict(k) for k in inp.expression_keys])
    feed([asdict(r) for r in inp.reactions])
    for voice in inp.voices:
        feed([voice.start_ms, voice.envelope.hop_ms])
        sha.update(json.dumps(voice.envelope.values).encode())
    if art is not None:
        feed([[e.id, sorted((state_code(s), p) for s, p in e.sprites.items())] for e in art.expressions])
    return sha.hexdigest()[:16]


# --- the frame track ----------------------------------------------------------------


class FrameTrack(BaseModel):
    """``GET /api/avatar/track``. Frame k is at ``k * 1000 / fps`` ms.

    ``sprites`` is a table of sprite keys ``"<expression>/<state>"`` (state like
    ``oicm``); ``sprite_runs`` are ``[first frame, index into sprites]`` pairs, each
    run lasting until the next one starts (index -1: nothing to draw). The transform
    arrays have one value per frame: ``x`` and ``y`` in frame fractions, ``scale``,
    ``rotation`` in degrees, ``squash``.
    """

    version: str
    fps: int
    duration_ms: int
    frame_count: int
    height_fraction: float
    sprites: list[str] = Field(default_factory=list)
    sprite_runs: list[list[int]] = Field(default_factory=list)
    x: list[float] = Field(default_factory=list)
    y: list[float] = Field(default_factory=list)
    scale: list[float] = Field(default_factory=list)
    rotation: list[float] = Field(default_factory=list)
    squash: list[float] = Field(default_factory=list)


def sprite_key(expression: str, state: str) -> str:
    return f"{expression}/{state}"


def frame_time(k: int, fps: int = TRACK_FPS) -> float:
    return k * 1000.0 / fps


def build_frame_track(
    solver: Solver, art: AvatarArt | None, version: str, *, fps: int = TRACK_FPS
) -> FrameTrack:
    duration = max(solver.input.duration_ms, 0)
    count = max(1, math.floor(duration * fps / 1000) + 1) if duration else 0
    sprites: list[str] = []
    index_of: dict[str, int] = {}
    runs: list[list[int]] = []
    xs: list[float] = []
    ys: list[float] = []
    scales: list[float] = []
    rots: list[float] = []
    squashes: list[float] = []
    last = None
    keys_by_path = (
        {}
        if art is None
        else {
            path: sprite_key(e.id, state_code(state))
            for e in art.expressions
            for state, path in e.sprites.items()
        }
    )
    for k in range(count):
        frame = solver.query(frame_time(k, fps))
        current = -1
        if art is not None:
            path = sprite_for(art, frame.expression, (frame.eyes_open, frame.mouth_open))
            if path is not None:
                key = keys_by_path[path]
                if key not in index_of:
                    index_of[key] = len(sprites)
                    sprites.append(key)
                current = index_of[key]
        if current != last:
            runs.append([k, current])
            last = current
        xs.append(round(frame.x, 4))
        ys.append(round(frame.y, 4))
        scales.append(round(frame.scale, 4))
        rots.append(round(frame.rotation_deg, 2))
        squashes.append(round(frame.squash, 4))
    return FrameTrack(
        version=version,
        fps=fps,
        duration_ms=duration,
        frame_count=count,
        height_fraction=AVATAR_HEIGHT_FRACTION,
        sprites=sprites,
        sprite_runs=runs,
        x=xs,
        y=ys,
        scale=scales,
        rotation=rots,
        squash=squashes,
    )


def sprite_path_for_key(art: AvatarArt, expression: str, state: str) -> str | None:
    """The relative sprite file for a key from the track (None if the art lacks it)."""
    found = art.get(expression)
    if found is None:
        return None
    for s, path in found.sprites.items():
        if state_code(s) == state.lower():
            return path
    return None


def build_track(
    project: Project,
    timeline: TimelineState,
    envelopes: Mapping[str, Envelope],
    art: AvatarArt | None,
    preset_expressions: Mapping[str, str],
) -> FrameTrack:
    inp = build_input(project, timeline, envelopes, art, preset_expressions)
    return build_frame_track(build_solver(inp), art, input_version(inp, art))


def placement_ids_needing_envelopes(timeline: TimelineState) -> Sequence[tuple[str, str, float]]:
    """(placement id, take id, stretch) of the placements whose audio drives the mouth."""
    return [
        (p.id, p.take_id, p.stretch)
        for p in timeline.placements
        if not p.orphaned and p.start_ms is not None and p.take_id is not None
    ]
