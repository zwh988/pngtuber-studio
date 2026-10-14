"""Generation planning (M3-4): which inputs, which seed, which cache key. Pure.

The worker (M3-3) never decides any of this. The flow for one request is:

1. ``plan_generation``: resolve the line's parameters, pick the seed, compute the
   raw key and the text chunks.
2. ``Session.reuse_take(plan.new_take)``: if a take with that key exists, stop
   (rule 3: no GPU time on an existing key).
3. Otherwise the worker generates, and ``Session.add_take`` stores the result.

Seed policy (M3 decision 3): the first generation uses ``base_seed``; a reroll
uses the lowest ``base + k`` whose key is not already one of the line's takes.
"""

from dataclasses import dataclass

from backend.project.schema import Project
from backend.voice.chunking import plan_chunks
from backend.voice.keys import base_seed, next_unused_seed, normalize_text, raw_key
from backend.voice.presets import EmotionPreset, PresetError, resolve_params
from backend.voice.takes import NewTake


class GenerationError(ValueError):
    """A line cannot be generated as it is (no text, unknown emotion, ...)."""


@dataclass(frozen=True)
class GenerationPlan:
    new_take: NewTake
    # Pieces to generate in order (one piece for lines up to MAX_CHUNK_CHARS).
    # Chunk ``i`` uses ``chunk_seed(new_take.seed, i)``.
    chunks: tuple[str, ...]
    reference_path: str  # passed through for the worker; not part of the key
    reroll: bool


def plan_generation(
    project: Project,
    line_id: str,
    presets: dict[str, EmotionPreset],
    *,
    voice_profile_id: str,
    reference_hash: str,
    reference_path: str,
    model_version: str,
    reroll: bool = False,
) -> GenerationPlan:
    line = next((item for item in project.lines if item.id == line_id), None)
    if line is None:
        raise GenerationError(f"unknown line id {line_id!r}")
    text = normalize_text(line.text)
    if not text:
        raise GenerationError("the line has no text to generate")
    try:
        exaggeration, cfg_weight = resolve_params(
            line.emotion, line.exaggeration, line.cfg_weight, presets
        )
    except PresetError as exc:
        raise GenerationError(str(exc)) from exc

    def key_for(seed: int) -> str:
        return raw_key(
            text=text,
            voice_profile_id=voice_profile_id,
            reference_hash=reference_hash,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            seed=seed,
            model_version=model_version,
        )

    base = base_seed(project.seed, line_id)
    try:
        seed = base
        if reroll:
            existing = [t.raw_key for t in project.takes if t.line_id == line_id]
            seed = next_unused_seed(base, key_for, existing)
        key = key_for(seed)
    except ValueError as exc:
        raise GenerationError(str(exc)) from exc

    return GenerationPlan(
        new_take=NewTake(
            line_id=line_id,
            seed=seed,
            text=text,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            voice_profile_id=voice_profile_id,
            model_version=model_version,
            raw_key=key,
        ),
        chunks=tuple(plan_chunks(text)),
        reference_path=reference_path,
        reroll=reroll,
    )
