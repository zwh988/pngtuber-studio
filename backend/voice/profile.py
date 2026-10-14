"""Voice profile: reference clip checks and the state shown to the UI (M3-1).

Pure: no file, network or audio access. ``backend/voice/reference.py`` does the
I/O (decode, hash, copy) and feeds the results in here.
"""

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, Field

from backend.project.schema import VoiceProfile

# Reference clips are copied here, inside the project folder (POSIX, relative).
VOICE_DIR = "media/voice"
ALLOWED_EXTENSIONS = (".wav", ".flac", ".ogg", ".mp3")

# Starting values, tune by ear.
MIN_REFERENCE_MS = 1_000  # shorter than this is refused
WARN_SHORT_MS = 5_000  # shorter than this is allowed with a warning
WARN_LONG_MS = 30_000
WARN_LOW_RATE_HZ = 16_000

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._ -]+")
_MAX_STEM = 40


@dataclass(frozen=True)
class AudioInfo:
    duration_ms: int
    sample_rate: int
    channels: int


@dataclass(frozen=True)
class ReferenceCheck:
    problems: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def _seconds(ms: int) -> str:
    return f"{ms / 1000:.1f} s"


def check_reference(info: AudioInfo) -> ReferenceCheck:
    """Judge a decoded reference clip. Problems block it; warnings do not."""
    problems: list[str] = []
    warnings: list[str] = []
    if info.sample_rate <= 0 or info.channels <= 0:
        problems.append("the audio format is not valid")
    elif info.duration_ms <= 0:
        problems.append("the clip is empty")
    elif info.duration_ms < MIN_REFERENCE_MS:
        problems.append(
            f"the clip is only {_seconds(info.duration_ms)} long; "
            f"use at least {_seconds(MIN_REFERENCE_MS)} (5 s or more is better)"
        )
    else:
        if info.duration_ms < WARN_SHORT_MS:
            warnings.append(
                f"the clip is short ({_seconds(info.duration_ms)}); "
                f"{_seconds(WARN_SHORT_MS)} or more usually clones better"
            )
        elif info.duration_ms > WARN_LONG_MS:
            warnings.append(
                f"the clip is long ({_seconds(info.duration_ms)}); only part of it "
                "may be used, so trim it if the voice sounds off"
            )
        if info.sample_rate < WARN_LOW_RATE_HZ:
            warnings.append(
                f"low sample rate ({info.sample_rate} Hz); expect a duller clone"
            )
    return ReferenceCheck(problems=tuple(problems), warnings=tuple(warnings))


def clean_stem(stem: str) -> str:
    """A safe, short file name stem (letters, digits, ``._ -``)."""
    text = _UNSAFE_CHARS.sub("_", stem).strip(" ._-")
    return text[:_MAX_STEM].strip(" ._-") or "reference"


def reference_filename(original_name: str, digest: str) -> str:
    """Name for the project copy: cleaned stem, 8 hash characters, extension.

    The hash in the name means the same file imported twice lands on the same
    name, and two different files never collide.
    """
    if len(digest) < 8 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("digest must be lowercase hex, at least 8 characters")
    path = PurePath(original_name)
    extension = path.suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(ALLOWED_EXTENSIONS)
        raise ValueError(
            f"unsupported audio type {extension or '(none)'}; use one of {allowed}"
        )
    return f"{clean_stem(path.stem)}-{digest[:8]}{extension}"


def reference_relpath(filename: str) -> str:
    return f"{VOICE_DIR}/{filename}"


# --------------------------------------------------------------------------
# State for the UI
# --------------------------------------------------------------------------

VoiceStatus = Literal[
    "no_profile", "no_reference", "file_missing", "unreadable", "invalid", "ready"
]


class VoiceState(BaseModel):
    status: VoiceStatus
    ready: bool = False
    profile_id: str | None = None
    name: str | None = None
    reference_path: str | None = None
    duration_ms: int | None = None
    sample_rate: int | None = None
    hash: str | None = None
    problems: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def build_voice_state(
    profile: VoiceProfile | None,
    *,
    exists: bool,
    info: AudioInfo | None,
    read_error: str | None,
    digest: str | None,
) -> VoiceState:
    """Combine a profile with what the caller found on disk (see ``Session``)."""
    if profile is None:
        return VoiceState(status="no_profile", problems=["no voice profile yet"])
    base = {"profile_id": profile.id, "name": profile.name}
    if not profile.reference_clips:
        return VoiceState(
            status="no_reference",
            problems=["no reference clip chosen"],
            **base,
        )
    path = profile.reference_clips[0]
    base["reference_path"] = path
    if not exists:
        return VoiceState(
            status="file_missing",
            problems=[f"reference clip not found: {path}"],
            **base,
        )
    if info is None:
        return VoiceState(
            status="unreadable",
            problems=[read_error or "cannot read the reference clip"],
            **base,
        )
    check = check_reference(info)
    return VoiceState(
        status="ready" if check.ok else "invalid",
        ready=check.ok,
        duration_ms=info.duration_ms,
        sample_rate=info.sample_rate,
        hash=digest,
        problems=list(check.problems),
        warnings=list(check.warnings),
        **base,
    )
