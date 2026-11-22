"""Audio clip FX (M8-4): the processing spec and cache key of a clip's chain. Pure.

A clip's chain (``ClipFx``) runs on its whole decoded file (``media/audio_decoded``)
once; the cut, fades, clip level and lane level come after it (decision 1 and the
stated assumption), so moving or trimming a clip never re-renders. The spec lists what
changes the audio: the EQ, compressor and effect stages (the voice chain's
``build_stages``) and the loudness settings when levelling is on. A chain that changes
nothing has no spec: the clip plays its file as it is (rule 3: a setting that does
nothing never changes the key).
"""

import hashlib
import math
from typing import Any

from backend.audio.chainspec import FxChainError, build_stages
from backend.audio.loudness import TARGET_MAX_LUFS, TARGET_MIN_LUFS, loudness_params
from backend.project.schema import ClipFx
from backend.voice.keys import canonical_json

CLIP_FX_VERSION = 1  # bump when the clip render code changes what a spec produces


def validate_clip_fx(fx: ClipFx) -> None:
    """Raise ``FxChainError`` when any part of the chain is unusable."""
    clip_processing_spec(fx)


def clip_processing_spec(fx: ClipFx | None) -> dict[str, Any] | None:
    """What the clip's chain does, or None when it does nothing."""
    if fx is None:
        return None
    stages = build_stages(fx)
    loudness: dict[str, Any] | None = None
    if fx.loudness_enabled:
        target = float(fx.loudness_target_lufs)
        if not math.isfinite(target) or not TARGET_MIN_LUFS <= target <= TARGET_MAX_LUFS:
            raise FxChainError(
                f"loudness target must be between {TARGET_MIN_LUFS} and {TARGET_MAX_LUFS} LUFS"
            )
        loudness = loudness_params(target)
    if not stages and loudness is None:
        return None
    return {"version": CLIP_FX_VERSION, "stages": stages, "loudness": loudness}


def clip_fx_key(file_id: str, spec: dict[str, Any]) -> str:
    """The processed file's key: the audio file and what the chain does (16 hex)."""
    text = canonical_json({"file_id": file_id, "spec": spec})
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def clip_fx_key_for(file_id: str, fx: ClipFx | None) -> str | None:
    """The key for a clip, None when it plays its file as it is or its chain is unusable."""
    try:
        spec = clip_processing_spec(fx)
    except FxChainError:
        return None
    return None if spec is None else clip_fx_key(file_id, spec)
