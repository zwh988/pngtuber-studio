"""Speech engines behind the GPU worker (M3-3).

``Engine`` is what ``WorkerLoop`` needs from a TTS model. ``ChatterboxEngine`` is
the real one (torch and chatterbox are imported only when it loads, so importing
this module is cheap). ``ToneEngine`` makes sine tones with no GPU; it backs the
worker's ``--engine tone`` mode for end-to-end tests.
"""

import gc
import time
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Protocol

import numpy as np


def chatterbox_model_version() -> str:
    """The model version that goes into every raw cache key.

    Read from package metadata (no torch import), so the backend can plan a
    generation and reuse a take without starting the worker. The worker reports
    the same string when it is ready.
    """
    try:
        version = metadata.version("chatterbox-tts")
    except metadata.PackageNotFoundError:
        version = "unknown"
    return f"chatterbox-tts {version}"


@dataclass(frozen=True)
class EngineInfo:
    model_version: str  # goes into every raw cache key
    sample_rate: int


class Engine(Protocol):
    def load(self, device: str) -> EngineInfo:
        """Load the model onto ``device``."""

    def warm_up(self) -> None:
        """Run a throwaway generation so the first real job is not slow."""

    def synthesize(
        self,
        text: str,
        *,
        seed: int,
        reference_path: str,
        exaggeration: float,
        cfg_weight: float,
    ) -> np.ndarray:
        """One piece of text as mono float32 samples at the model's sample rate."""

    def unload(self) -> None:
        """Free the model and its VRAM."""


class ToneEngine:
    """Sine tones, pitch from the seed, length from the text. No GPU."""

    def __init__(
        self, *, delay_s: float = 0.0, noisy: bool = False, sample_rate: int = 24000
    ) -> None:
        self._delay_s = delay_s
        self._noisy = noisy
        self._sample_rate = sample_rate

    def load(self, device: str) -> EngineInfo:
        del device
        if self._noisy:
            print("tone engine: loading")  # must not reach the protocol pipe
        return EngineInfo(model_version="tone-engine 1", sample_rate=self._sample_rate)

    def warm_up(self) -> None:
        """Nothing to warm up."""

    def synthesize(
        self,
        text: str,
        *,
        seed: int,
        reference_path: str,
        exaggeration: float,
        cfg_weight: float,
    ) -> np.ndarray:
        del reference_path, exaggeration, cfg_weight  # the tone ignores them
        if self._noisy:
            print(f"tone engine: synthesizing {text!r}")
        if self._delay_s > 0:
            time.sleep(self._delay_s)
        count = round(max(0.2, 0.03 * len(text)) * self._sample_rate)
        t = np.arange(count) / self._sample_rate
        frequency = 220 + seed % 200
        return (0.1 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)

    def unload(self) -> None:
        """Nothing to free."""


class ChatterboxEngine:
    """Original ``ChatterboxTTS`` (M0 findings). Generation follows the spike:
    ``torch.manual_seed(seed)`` before each ``generate`` call."""

    def __init__(self) -> None:
        self._model: Any = None

    def load(self, device: str) -> EngineInfo:
        from chatterbox.tts import ChatterboxTTS  # slow import, only here

        self._model = ChatterboxTTS.from_pretrained(device=device)
        return EngineInfo(
            model_version=chatterbox_model_version(),
            sample_rate=int(self._model.sr),
        )

    def warm_up(self) -> None:
        import torch

        model = self._require_model()
        torch.manual_seed(0)
        model.generate("Warming up.")  # the model's built-in voice
        if torch.cuda.is_available():
            torch.cuda.synchronize()

    def synthesize(
        self,
        text: str,
        *,
        seed: int,
        reference_path: str,
        exaggeration: float,
        cfg_weight: float,
    ) -> np.ndarray:
        import torch

        model = self._require_model()
        torch.manual_seed(seed)
        try:
            wav = model.generate(
                text,
                audio_prompt_path=reference_path,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
            )
            if torch.cuda.is_available():
                torch.cuda.synchronize()
        except torch.cuda.OutOfMemoryError as exc:
            torch.cuda.empty_cache()
            raise RuntimeError(
                "the GPU ran out of memory (close other GPU programs and retry)"
            ) from exc
        return np.asarray(wav.squeeze().cpu().numpy(), dtype=np.float32).reshape(-1)

    def unload(self) -> None:
        self._model = None
        gc.collect()
        try:
            import torch
        except ImportError:
            return
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _require_model(self) -> Any:
        if self._model is None:
            raise RuntimeError("the model is not loaded")
        return self._model
