"""Take cache keys and seed policy (M3-4 groundwork). Pure, no I/O.

CLAUDE.md rule 3: raw take key = hash(text, voice profile id + reference clip hash,
exaggeration, cfg_weight, seed, model version). Same key means reuse, never regenerate.
Chunking constants are deliberately not part of the key (see PROJECT_STATE decisions).
"""

import hashlib
import json
import math
from collections.abc import Callable, Iterable

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
