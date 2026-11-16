"""Loudness envelope of a processed take (M5-2): the mouth and the bounce follow it.

``compute_envelope`` is pure (numpy only). ``envelope_for`` is the cache in
``media/envelopes/``: one small JSON per processed file, named after it, so a change of
chain, stretch or trim (a new processed key, rule 3) gives a new envelope and the old
one is simply no longer asked for. CPU only.
"""

import contextlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from backend.avatar.tuning import (
    ENVELOPE_FLOOR_DB,
    ENVELOPE_HOP_MS,
    ENVELOPE_VERSION,
    ENVELOPE_WINDOW_MS,
)

ENVELOPE_DIR_NAME = "envelopes"


@dataclass(frozen=True)
class Envelope:
    """dBFS values, one per ``hop_ms`` from the start of the audio."""

    hop_ms: int
    values: tuple[float, ...]

    @property
    def duration_ms(self) -> int:
        return len(self.values) * self.hop_ms

    def at(self, ms: float) -> float:
        """Value of the hop that ``ms`` falls in; the floor outside the audio."""
        if ms < 0:
            return ENVELOPE_FLOOR_DB
        index = int(ms // self.hop_ms)
        return self.values[index] if index < len(self.values) else ENVELOPE_FLOOR_DB


def compute_envelope(
    samples: np.ndarray,
    sample_rate: int,
    *,
    hop_ms: int = ENVELOPE_HOP_MS,
    window_ms: int = ENVELOPE_WINDOW_MS,
    floor_db: float = ENVELOPE_FLOOR_DB,
) -> Envelope:
    """RMS level in dBFS over ``window_ms`` centred on every ``hop_ms`` (value k is
    centred on k * hop + hop / 2), rounded to 0.1 dB."""
    data = np.asarray(samples, dtype=np.float64)
    if data.ndim != 1:
        raise ValueError("samples must be mono (one dimension)")
    if sample_rate <= 0 or hop_ms <= 0 or window_ms <= 0:
        raise ValueError("sample rate, hop and window must be positive")
    if not np.all(np.isfinite(data)):
        raise ValueError("samples contain NaN or infinite values")
    total = data.size
    count = -(-total * 1000 // (sample_rate * hop_ms)) if total else 0
    if count == 0:
        return Envelope(hop_ms, ())
    sums = np.concatenate([[0.0], np.cumsum(data * data)])
    half = window_ms * sample_rate / 2000.0
    centres = (np.arange(count) * hop_ms + hop_ms / 2.0) * sample_rate / 1000.0
    lo = np.clip(np.floor(centres - half).astype(np.int64), 0, total)
    hi = np.clip(np.ceil(centres + half).astype(np.int64), 0, total)
    width = np.maximum(hi - lo, 1)
    mean_sq = np.maximum((sums[hi] - sums[lo]) / width, 0.0)
    floor_power = 10.0 ** (floor_db / 10.0)
    with np.errstate(divide="ignore"):
        db = 10.0 * np.log10(np.maximum(mean_sq, floor_power))
    return Envelope(hop_ms, tuple(round(float(v), 1) for v in db))


class EnvelopeReport(BaseModel):
    """``GET /api/takes/{id}/envelope``: dBFS every ``hop_ms`` of the processed take."""

    take_id: str
    stretch: float
    hop_ms: int
    values: list[float]


# --- cache -----------------------------------------------------------------------


def envelope_dir(processed_path: Path) -> Path:
    """``media/envelopes`` beside the ``media/takes_fx`` folder of a processed take."""
    return processed_path.parent.parent / ENVELOPE_DIR_NAME


def envelope_path(processed_path: Path) -> Path:
    return envelope_dir(processed_path) / f"{processed_path.stem}.env.json"


def _settings() -> dict[str, int | float]:
    return {
        "version": ENVELOPE_VERSION,
        "hop_ms": ENVELOPE_HOP_MS,
        "window_ms": ENVELOPE_WINDOW_MS,
        "floor_db": ENVELOPE_FLOOR_DB,
    }


def _decode(data: object) -> Envelope | None:
    if not isinstance(data, dict) or data.get("settings") != _settings():
        return None
    values = data.get("values")
    if not isinstance(values, list) or not all(
        isinstance(v, (int, float)) and not isinstance(v, bool) for v in values
    ):
        return None
    return Envelope(ENVELOPE_HOP_MS, tuple(float(v) for v in values))


def envelope_for(processed_path: Path) -> Envelope:
    """Envelope of a processed take file: from the cache, else computed and stored
    (best effort; a failed write never fails the caller)."""
    import soundfile  # here, so the pure part needs no audio library

    cache = envelope_path(processed_path)
    try:
        if cache.stat().st_mtime_ns >= processed_path.stat().st_mtime_ns:
            found = _decode(json.loads(cache.read_text(encoding="utf-8")))
            if found is not None:
                return found
    except (OSError, ValueError):
        pass
    data, rate = soundfile.read(str(processed_path), dtype="float32", always_2d=True)
    mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
    envelope = compute_envelope(mono, int(rate))
    tmp = cache.with_name(f"{cache.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps({"settings": _settings(), "values": list(envelope.values)}),
            encoding="utf-8",
        )
        os.replace(tmp, cache)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
    return envelope
