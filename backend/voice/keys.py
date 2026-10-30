"""Take cache keys and seed policy (M3-4 groundwork). Pure, no I/O.

CLAUDE.md rule 3: raw take key = hash(text, voice profile id + reference clip hash,
exaggeration, cfg_weight, seed, model version). Same key means reuse, never regenerate.
Chunking constants are deliberately not part of the key (see PROJECT_STATE decisions).
"""

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Mapping
from typing import Any

SEED_MODULUS = 2**31  # matches Project.seed (``uuid4().int % 2**31``)


def normalize_text(text: str) -> str:
    """Collapse all whitespace runs to one space and strip the ends.

    Edits that only change spacing or line breaks must not cost a GPU run.
    """
    return " ".join(text.split())


def _param(value: float, label: str) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    # ``+ 0.0`` turns -0.0 into 0.0 so both spellings give the same key.
    return f"{round(number, 4) + 0.0:.4f}"


def raw_key(
    *,
    text: str,
    voice_profile_id: str,
    reference_hash: str,
    exaggeration: float,
    cfg_weight: float,
    seed: int,
    model_version: str,
) -> str:
    """Return the raw cache key as a 64-char lowercase hex string (SHA-256)."""
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("text must not be empty")
    if not voice_profile_id:
        raise ValueError("voice_profile_id must not be empty")
    if not reference_hash:
        raise ValueError("reference_hash must not be empty")
    if not model_version:
        raise ValueError("model_version must not be empty")
    payload = {
        "text": normalized,
        "voice": voice_profile_id,
        "ref": reference_hash,
        "exag": _param(exaggeration, "exaggeration"),
        "cfg": _param(cfg_weight, "cfg_weight"),
        "seed": int(seed),
        "model": model_version,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def base_seed(project_seed: int, line_id: str) -> int:
    """Deterministic first seed for a line: a hash of the project seed and the line id."""
    digest = hashlib.sha256(f"{int(project_seed)}:{line_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % SEED_MODULUS


def next_unused_seed(
    base: int,
    key_for_seed: Callable[[int], str],
    existing_keys: Iterable[str],
) -> int:
    """Lowest seed in ``base, base+1, ...`` whose key is not among ``existing_keys``.

    ``key_for_seed`` computes the raw key for a seed with every other input fixed, so a
    reroll skips seeds already used for the same text, parameters and voice.
    """
    existing = set(existing_keys)
    for offset in range(len(existing) + 1):
        seed = (int(base) + offset) % SEED_MODULUS
        if key_for_seed(seed) not in existing:
            return seed
    raise ValueError("no unused seed found: key_for_seed does not depend on the seed")


# --- Processed takes (M4-1) -------------------------------------------------


def canonical_json(value: Any) -> str:
    """Compact, key-sorted JSON of plain data that is stable across float noise.

    Numbers (ints and floats alike) become 4-decimal strings, so ``3`` and ``3.00001``
    give the same text. Dicts need string keys; lists, tuples, strings, bools and None
    are accepted. Anything else raises ``TypeError``; NaN or infinity raises ``ValueError``.
    """
    return json.dumps(
        _canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def _canonical(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, (int, float)):
        return _param(value, "number")
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("keys must be strings")
            out[key] = _canonical(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    raise TypeError(f"cannot canonicalize a {type(value).__name__}")


def processed_key(*, raw_key: str, stretch: float, spec: Mapping[str, Any]) -> str:
    """Processed take key: hash(raw key, stretch, processing spec), 64 hex chars.

    ``spec`` is the plain-data processing spec from ``backend.audio.chainspec``: trim
    settings, the plugin stages and the loudness settings. Anything that changes the
    audio is in it, so the same key always means the same file (CLAUDE.md rule 3).
    """
    if not raw_key:
        raise ValueError("raw_key must not be empty")
    if not float(stretch) > 0:
        raise ValueError("stretch must be positive")
    payload = {
        "raw": raw_key,
        "stretch": _param(stretch, "stretch"),
        "spec": _canonical(spec),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def processed_name(key: str) -> str:
    """File name of a processed take in ``media/takes_fx/`` (first 16 hex chars + ``.wav``)."""
    if len(key) < 16:
        raise ValueError("key is too short")
    return f"{key[:16]}.wav"


def fx_version(spec: Mapping[str, Any]) -> str:
    """Short hash (8 hex chars) of a processing spec, for the UI to tell chains apart."""
    return hashlib.sha256(canonical_json(spec).encode("utf-8")).hexdigest()[:8]
