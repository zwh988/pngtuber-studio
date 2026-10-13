"""Long-text chunking and crossfade join (M3-5). Pure: strings and numpy only.

Lines up to ``MAX_CHUNK_CHARS`` stay one chunk (so short lines behave exactly like the
M0 spike). Longer lines are split at sentence boundaries, packed greedily up to the
limit, generated piece by piece (cancel can happen between pieces) and joined with a
short equal-power crossfade.
"""

import re
from collections.abc import Sequence

import numpy as np

from backend.voice.keys import SEED_MODULUS, normalize_text

MAX_CHUNK_CHARS = 200
CROSSFADE_MS = 40
MIN_MAX_CHARS = 20

_SENTENCE_END = re.compile(r"""([.!?…]+["'”’)\]]*)\s+""")
_ABBREVIATIONS = frozenset(
    {"mr", "mrs", "ms", "dr", "vs", "st", "jr", "sr", "prof", "e.g", "i.e"}
)
_OPENERS = "\"'“‘(["


def _ends_with_abbreviation(candidate: str) -> bool:
    token = candidate.split()[-1]
    if not token.endswith(".") or token.endswith(".."):
        return False
    core = token.rstrip(".").lstrip(_OPENERS).lower()
    if core in _ABBREVIATIONS:
        return True
    # A lone initial ("J. Smith"); "I" and "a" can genuinely end a sentence.
    return len(core) == 1 and core.isalpha() and core not in {"i", "a"}


def split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation followed by whitespace.

    Whitespace is normalized first. Common abbreviations and lone initials do not end a
    sentence; decimals like ``3.5`` never match because no whitespace follows the dot.
    """
    normalized = normalize_text(text)
    if not normalized:
        return []
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(normalized):
        candidate = normalized[start : match.end(1)]
        if _ends_with_abbreviation(candidate):
            continue
        sentences.append(candidate.strip())
        start = match.end()
    tail = normalized[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _best_cut(text: str, max_chars: int) -> int:
    window = text[: max_chars + 1]
    comma = max((m.start() + 1 for m in re.finditer(r"[,;:](?=\s)", window)), default=-1)
    if comma >= max_chars // 3:
        return comma
    space = window.rfind(" ")
    if space >= 1:
        return space
    return max_chars  # one giant word: hard cut


def _split_long(sentence: str, max_chars: int) -> list[str]:
    parts: list[str] = []
    rest = sentence
    while len(rest) > max_chars:
        cut = _best_cut(rest, max_chars)
        parts.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        parts.append(rest)
    return parts


def plan_chunks(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Return the pieces to generate, in order. Empty text gives an empty list."""
    if max_chars < MIN_MAX_CHARS:
        raise ValueError(f"max_chars must be at least {MIN_MAX_CHARS}")
    normalized = normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]
    pieces: list[str] = []
    for sentence in split_sentences(normalized):
        pieces.extend(_split_long(sentence, max_chars))
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + 1 + len(piece) <= max_chars:
            current = f"{current} {piece}"
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


def chunk_seed(seed: int, index: int) -> int:
    """Seed for chunk ``index`` of a take. Chunk 0 uses the take seed unchanged."""
    return (int(seed) + int(index)) % SEED_MODULUS


def crossfade_join(
    chunks: Sequence[np.ndarray],
    sample_rate: int,
    crossfade_ms: int = CROSSFADE_MS,
) -> np.ndarray:
    """Join mono float chunks with an equal-power crossfade of ``crossfade_ms``.

    The fade is shortened to half of the shorter neighbour so a very short chunk is never
    eaten. Output length is the sum of the chunk lengths minus the overlaps.
    """
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if crossfade_ms < 0:
        raise ValueError("crossfade_ms must not be negative")
    arrays = [np.asarray(chunk, dtype=np.float32) for chunk in chunks]
    for array in arrays:
        if array.ndim != 1:
            raise ValueError("chunks must be 1-D mono arrays")
    if not arrays:
        return np.zeros(0, dtype=np.float32)

    fade = round(sample_rate * crossfade_ms / 1000)
    out = arrays[0]
    prev_len = len(arrays[0])
    for nxt in arrays[1:]:
        n = min(fade, prev_len // 2, len(nxt) // 2)
        if n == 0:
            out = np.concatenate([out, nxt])
        else:
            angle = np.linspace(0.0, np.pi / 2, n, dtype=np.float32)
            blended = out[-n:] * np.cos(angle) + nxt[:n] * np.sin(angle)
            out = np.concatenate([out[:-n], blended, nxt[n:]])
        prev_len = len(nxt)
    return out.astype(np.float32, copy=False)
