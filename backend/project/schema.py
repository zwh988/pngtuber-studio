"""Pydantic v2 schema for ``project.json`` (schema version 1).

Conventions (see PROJECT_STATE.md decisions log):
- All times are integer milliseconds. Anchor times are in *source* time.
- Ids are 12-char lowercase hex strings.
- Paths stored in JSON are relative POSIX strings (forward slashes, no ``..``).
- ``orphaned`` flags are stored here; the logic that sets them lives in M2.

This module defines and validates data only. It does no file I/O.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

SCHEMA_VERSION = 1

# --------------------------------------------------------------------------
# Primitive types
# --------------------------------------------------------------------------

EntityId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12}$")]
Ms = Annotated[int, Field(ge=0)]
PositiveMs = Annotated[int, Field(gt=0)]


def new_id() -> str:
    """Return a new random 12-char hex id (the only impure helper here)."""
    return uuid.uuid4().hex[:12]


def _check_relative_posix(value: str) -> str:
    if not value:
        raise ValueError("path must not be empty")
    if "\\" in value:
        raise ValueError("path must use forward slashes")
    if value.startswith("/") or (len(value) >= 2 and value[1] == ":"):
        raise ValueError("path must be relative, not absolute")
    if ".." in value.split("/"):
        raise ValueError("path must not contain '..'")
    return value


RelPath = Annotated[str, AfterValidator(_check_relative_posix)]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _Model(BaseModel):
    # protected_namespaces=() because we have fields named ``model_version``.
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        protected_namespaces=(),
    )


# --------------------------------------------------------------------------
# Shared small models
# --------------------------------------------------------------------------


class Anchor(_Model):
    """A moment in footage: a clip plus a time in that clip's source."""

    clip_id: EntityId
    source_ms: Ms


class EffectSpec(_Model):
    """A pluggable effect instance (clip effects and voice FX slot).

    ``type`` is looked up in an effect registry later (CLAUDE.md rule 13).
    """

    type: str
    params: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Entities (spec section 5)
# --------------------------------------------------------------------------


class Source(_Model):
    id: EntityId
    path: RelPath
    duration_ms: Ms
    fps_num: int = Field(gt=0)
    fps_den: int = Field(gt=0, default=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    audio_tracks: int = Field(ge=0, default=0)

    @property
    def fps(self) -> float:
        return self.fps_num / self.fps_den


class Clip(_Model):
    id: EntityId
    source_id: EntityId
    in_ms: Ms
    out_ms: Ms
    speed: float = Field(default=1.0, ge=0.25, le=8.0)
    track: int = Field(default=0, ge=0)
    overlay: bool = True
    effects: list[EffectSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _out_after_in(self) -> "Clip":
        if self.out_ms <= self.in_ms:
            raise ValueError("out_ms must be greater than in_ms")
        return self


class Line(_Model):
    id: EntityId
    text: str = ""
    emotion: str = "neutral"
    exaggeration: float | None = Field(default=None, ge=0.0, le=2.0)
    cfg_weight: float | None = Field(default=None, ge=0.0, le=1.0)
    active_take_id: EntityId | None = None
    allow_overlap: bool = False


class Take(_Model):
    id: EntityId
    line_id: EntityId
    seed: int
    # Snapshot of the inputs used, so the take stays valid if the line is edited.
    text: str
    exaggeration: float = Field(ge=0.0, le=2.0)
    cfg_weight: float = Field(ge=0.0, le=1.0)
    voice_profile_id: EntityId
    model_version: str
    raw_key: str  # raw cache key (CLAUDE.md rule 3)
    raw_file: RelPath
    duration_ms: Ms
    starred: bool = False
    created: datetime = Field(default_factory=_utcnow)


class Placement(_Model):
    id: EntityId
    line_id: EntityId
    anchor: Anchor
    take_override_id: EntityId | None = None
    orphaned: bool = False


class Keyframe(_Model):
    id: EntityId
    lane_id: str
    anchor: Anchor
    # Numeric lanes use float; the expression lane uses an expression name.
    value: float | str
    interpolation: Literal["hold", "smooth"] = "hold"
    orphaned: bool = False


class Reaction(_Model):
    id: EntityId
    type: Literal["shake", "hop", "pop_in", "squish"]
    anchor: Anchor
    intensity: float = Field(default=1.0, ge=0.0)
    duration_ms: PositiveMs = 500
    orphaned: bool = False


class VoiceProfile(_Model):
    id: EntityId
    name: str
    reference_clips: list[str] = Field(default_factory=list)
    # Reserved for later (backlog): per-emotion reference clips.
    emotion_reference_clips: dict[str, str] = Field(default_factory=dict)


class CompressorSettings(_Model):
    enabled: bool = False
    threshold_db: float = -18.0
    ratio: float = Field(default=3.0, ge=1.0)
    attack_ms: float = Field(default=10.0, gt=0)
    release_ms: float = Field(default=100.0, gt=0)


class FxChain(_Model):
    eq_bass_db: float = 0.0
    eq_mid_db: float = 0.0
    eq_treble_db: float = 0.0
    compressor: CompressorSettings = Field(default_factory=CompressorSettings)
    effects: list[EffectSpec] = Field(default_factory=list)
    loudness_target_lufs: float = -16.0


class AvatarSettings(_Model):
    art_folder: RelPath | None = None
    # Position as a fraction of the frame (0..1); rotation in degrees.
    x: float = 0.85
    y: float = 0.75
    scale: float = Field(default=1.0, gt=0)
    rotation_deg: float = 0.0
    auto_key_expression: bool = True


class ExportSettings(_Model):
    height: int = Field(default=1080, gt=0)
    fps: Literal["match"] | float = "match"
    include_avatar_overlay: bool = False
    include_raw_video_link: bool = True
    unload_tts_before_export: bool = False


class BookendRef(_Model):
    """A template bookend clip. First draft; finalized with M1-5."""

    path: str  # may be absolute: template assets live outside the project


class ChannelTemplate(_Model):
    """First draft; finalized with M1-5."""

    name: str = "Default"
    intro: BookendRef | None = None
    outro: BookendRef | None = None
    voice_profile: VoiceProfile | None = None
    fx_chain: FxChain = Field(default_factory=FxChain)
    avatar: AvatarSettings = Field(default_factory=AvatarSettings)
    export: ExportSettings = Field(default_factory=ExportSettings)
    game_audio_db: float = 0.0


# --------------------------------------------------------------------------
# Root
# --------------------------------------------------------------------------


def _new_seed() -> int:
    return uuid.uuid4().int % (2**31)


class Project(_Model):
    schema_version: int = Field(default=SCHEMA_VERSION, ge=1)
    name: str
    seed: int = Field(default_factory=_new_seed)

    sources: list[Source] = Field(default_factory=list)
    clips: list[Clip] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    takes: list[Take] = Field(default_factory=list)
    placements: list[Placement] = Field(default_factory=list)
    keyframes: list[Keyframe] = Field(default_factory=list)
    reactions: list[Reaction] = Field(default_factory=list)
    voice_profiles: list[VoiceProfile] = Field(default_factory=list)

    fx_chain: FxChain = Field(default_factory=FxChain)
    game_audio_db: float = 0.0
    avatar: AvatarSettings = Field(default_factory=AvatarSettings)
    export: ExportSettings = Field(default_factory=ExportSettings)

    @model_validator(mode="after")
    def _unique_ids(self) -> "Project":
        collections = {
            "sources": self.sources,
            "clips": self.clips,
            "lines": self.lines,
            "takes": self.takes,
            "placements": self.placements,
            "keyframes": self.keyframes,
            "reactions": self.reactions,
            "voice_profiles": self.voice_profiles,
        }
        for name, items in collections.items():
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate ids in {name}")
        return self
