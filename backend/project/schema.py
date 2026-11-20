"""Pydantic v2 schema for ``project.json`` (see ``SCHEMA_VERSION``).

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
    ValidationInfo,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = 6

# Picture-in-picture limits of a video-lane clip (schema v6, M8-2).
LANE_SCALE_MIN = 0.05
LANE_SCALE_MAX = 4.0

# Level range of audio lanes and audio clips (schema v5, M8-1), in dB.
AUDIO_GAIN_MIN_DB = -60.0
AUDIO_GAIN_MAX_DB = 12.0

# Placement.stretch is a speed-up factor for a placed line (Tighten, M3-9):
# 1.0 plays the take as it is, 1.25 plays it 25 percent faster (shorter).
STRETCH_MIN = 1.0
STRETCH_MAX = 1.25

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


def _check_absolute_posix(value: str) -> str:
    if not value:
        raise ValueError("path must not be empty")
    if "\\" in value:
        raise ValueError("path must use forward slashes")
    is_drive = len(value) >= 3 and value[1] == ":" and value[2] == "/"
    if not (value.startswith("/") or is_drive):
        raise ValueError("external path must be absolute")
    if ".." in value.split("/"):
        raise ValueError("path must not contain '..'")
    return value


RelPath = Annotated[str, AfterValidator(_check_relative_posix)]


def _check_any_posix(value: str) -> str:
    """A relative POSIX path, or an absolute one (``/x`` or ``D:/x``)."""
    if value.startswith("/") or (len(value) >= 3 and value[1:3] == ":/"):
        return _check_absolute_posix(value)
    return _check_relative_posix(value)


# Relative to the project folder, or absolute POSIX for things kept outside it
# (shared avatar art, M5-1).
AnyPath = Annotated[str, AfterValidator(_check_any_posix)]


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
    # ``external`` must stay declared before ``path``: the path validator reads it.
    external: bool = False
    # Relative POSIX path, or an absolute POSIX path when ``external`` is true
    # (template bookend clips live outside the project folder).
    path: str
    duration_ms: Ms
    fps_num: int = Field(gt=0)
    fps_den: int = Field(gt=0, default=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    audio_tracks: int = Field(ge=0, default=0)

    @field_validator("path")
    @classmethod
    def _check_path(cls, value: str, info: ValidationInfo) -> str:
        if info.data.get("external", False):
            return _check_absolute_posix(value)
        return _check_relative_posix(value)

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
    # Manual trim (schema v3, M5-0): cut points in raw take time; None means no
    # cut on that side. Metadata only: the raw file is never touched (rule 1).
    trim_start_ms: Ms | None = None
    trim_end_ms: PositiveMs | None = None

    @model_validator(mode="after")
    def _check_trim(self) -> "Take":
        start, end = self.trim_start_ms, self.trim_end_ms
        if start is not None and end is not None and start >= end:
            raise ValueError("trim_start_ms must be before trim_end_ms")
        return self


class Placement(_Model):
    id: EntityId
    line_id: EntityId
    anchor: Anchor
    take_override_id: EntityId | None = None
    orphaned: bool = False
    # Speed-up of the take's audio, pitch kept (schema v2). Duration on the
    # timeline is take length / stretch.
    stretch: float = Field(default=STRETCH_MIN, ge=STRETCH_MIN, le=STRETCH_MAX)


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


AudioGain = Annotated[float, Field(ge=AUDIO_GAIN_MIN_DB, le=AUDIO_GAIN_MAX_DB)]


class AudioFile(_Model):
    """A music or sound-effect file copied into the project's ``audio/`` folder (v5).

    ``name`` and ``size_bytes`` describe the file that was dropped, so dropping the
    same file again reuses this copy instead of copying it twice.
    """

    id: EntityId
    path: RelPath
    name: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    duration_ms: PositiveMs
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)


class AudioLane(_Model):
    id: EntityId
    name: str = Field(default="Audio 1", min_length=1)
    gain_db: AudioGain = 0.0
    mute: bool = False
    solo: bool = False


class AudioClip(_Model):
    """A stretch of an audio file on an audio lane (v5).

    Not anchored to footage (decision 2, 2026-11-20, the exception to rule 4): it
    starts at ``timeline_ms`` and no video edit moves or cuts it. ``in_ms`` and
    ``out_ms`` are times in the file.
    """

    id: EntityId
    lane_id: EntityId
    file_id: EntityId
    timeline_ms: Ms
    in_ms: Ms = 0
    out_ms: PositiveMs
    gain_db: AudioGain = 0.0
    fade_in_ms: Ms = 0
    fade_out_ms: Ms = 0

    @model_validator(mode="after")
    def _check_times(self) -> "AudioClip":
        if self.out_ms <= self.in_ms:
            raise ValueError("out_ms must be greater than in_ms")
        if self.fade_in_ms + self.fade_out_ms > self.out_ms - self.in_ms:
            raise ValueError("the fades must fit inside the clip")
        return self

    @property
    def length_ms(self) -> int:
        return self.out_ms - self.in_ms

    @property
    def end_ms(self) -> int:
        """Timeline time where the clip stops (exclusive)."""
        return self.timeline_ms + self.length_ms


class ImageFile(_Model):
    """A still image copied into the project's ``images/`` folder (v6, M8-2).

    ``name`` and ``size_bytes`` describe the dropped file, so dropping it again
    reuses the copy.
    """

    id: EntityId
    path: RelPath
    name: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class VideoLane(_Model):
    """A video lane above the main footage (v6). ``Project.video_lanes`` is bottom to
    top: the first lane draws just above the main footage. A hidden lane is neither
    shown nor exported; a locked lane refuses edits to its clips."""

    id: EntityId
    name: str = Field(default="Video 2", min_length=1)
    hidden: bool = False
    locked: bool = False


class LaneClip(_Model):
    """A recording or a still on a video lane (v6, M8-2).

    Not anchored to footage (decision 4, the exception to rule 4): it starts at
    ``timeline_ms`` and plays at 1x; no edit of the main footage moves or cuts it.
    Exactly one of ``source_id`` (a recording in ``footage/``) and ``image_id`` is
    set. ``in_ms``/``out_ms`` are times in the recording; a still has ``in_ms`` 0
    and ``out_ms`` its length on the timeline.

    Picture-in-picture: the picture is fitted into the frame like the main footage
    (``scale`` 1 = full frame), scaled by ``scale`` around its centre, which sits at
    (``x``, ``y``) as fractions of the frame width and height, at ``opacity``.
    A recording's own sound plays at ``gain_db`` unless ``mute``.
    """

    id: EntityId
    lane_id: EntityId
    source_id: EntityId | None = None
    image_id: EntityId | None = None
    timeline_ms: Ms
    in_ms: Ms = 0
    out_ms: PositiveMs
    x: float = Field(default=0.5, ge=-1.0, le=2.0)
    y: float = Field(default=0.5, ge=-1.0, le=2.0)
    scale: float = Field(default=1.0, ge=LANE_SCALE_MIN, le=LANE_SCALE_MAX)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    gain_db: AudioGain = 0.0
    mute: bool = False

    @model_validator(mode="after")
    def _check(self) -> "LaneClip":
        if (self.source_id is None) == (self.image_id is None):
            raise ValueError("a lane clip shows exactly one recording or image")
        if self.out_ms <= self.in_ms:
            raise ValueError("out_ms must be greater than in_ms")
        if self.image_id is not None and self.in_ms != 0:
            raise ValueError("a still starts at in_ms 0")
        return self

    @property
    def length_ms(self) -> int:
        return self.out_ms - self.in_ms

    @property
    def end_ms(self) -> int:
        return self.timeline_ms + self.length_ms


def _default_audio_lanes() -> list[AudioLane]:
    return [AudioLane(id=new_id(), name="Audio 1")]


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
    # Shared art lives outside the project (``avatars/<name>/``, M5-1): an absolute
    # POSIX path, or a path relative to the project folder. Never copied (decision 2).
    art_folder: AnyPath | None = None
    # Position as a fraction of the frame (0..1); rotation in degrees.
    x: float = 0.85
    y: float = 0.75
    scale: float = Field(default=1.0, gt=0)
    rotation_deg: float = 0.0
    auto_key_expression: bool = True
    # Base motion (schema v4, M5 S11): the value of each motion lane where it has no
    # keys. Ranges match backend/avatar/lanes.py. ``float_angle_deg`` is the direction
    # of the idle float: 0 = up and down, 90 = left and right.
    bounce: float = Field(default=1.0, ge=0.0, le=3.0)
    float_amp: float = Field(default=1.0, ge=0.0, le=3.0)
    float_speed: float = Field(default=1.0, ge=0.0, le=4.0)
    float_angle_deg: float = Field(default=0.0, ge=-180.0, le=180.0)
    blink_rate: float = Field(default=1.0, ge=0.0, le=4.0)
    mouth_sensitivity: float = Field(default=1.0, ge=0.25, le=4.0)


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
    # Schema v5 (M8-1): music and sound effects on audio lanes.
    audio_files: list[AudioFile] = Field(default_factory=list)
    audio_lanes: list[AudioLane] = Field(default_factory=_default_audio_lanes)
    audio_clips: list[AudioClip] = Field(default_factory=list)
    # Schema v6 (M8-2): video lanes above the main footage, bottom to top.
    image_files: list[ImageFile] = Field(default_factory=list)
    video_lanes: list[VideoLane] = Field(default_factory=list)
    lane_clips: list[LaneClip] = Field(default_factory=list)

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
            "audio_files": self.audio_files,
            "audio_lanes": self.audio_lanes,
            "audio_clips": self.audio_clips,
            "image_files": self.image_files,
            "video_lanes": self.video_lanes,
            "lane_clips": self.lane_clips,
        }
        for name, items in collections.items():
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate ids in {name}")
        return self
