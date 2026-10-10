"""M0-2 spike: Chatterbox cloned-voice smoke test. Throwaway, but reusable findings."""
import argparse
import time
from pathlib import Path

import soundfile as sf
import torch

LINES = [
    ("neutral", 0.50, 0.50, "Okay, nine ball, rack looks clean. Let's see if I can run this table."),
    ("excited", 0.75, 0.35, "Oh, that is a perfect break! Three balls dropped, I cannot believe it!"),
    ("nervous", 0.65, 0.40, "Okay, okay, this shot is tight. Please, please don't scratch."),
]
SEED = 1234


def gib(n_bytes: float) -> str:
    return f"{n_bytes / 1024**3:.2f} GiB"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True, help="path to reference WAV (10-20 s)")
    parser.add_argument("--out", default="scripts/spike/out", help="output folder (git-ignored)")
    args = parser.parse_args()

    ref = Path(args.ref)
    out_dir = Path(args.out)
    if not ref.is_file():
        raise SystemExit(f"Reference clip not found: {ref}")
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    from chatterbox.tts import ChatterboxTTS  # slow import, timed on purpose

    print(f"import time: {time.perf_counter() - t0:.1f} s")

    torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    model = ChatterboxTTS.from_pretrained(device="cuda")
    torch.cuda.synchronize()
    print(f"model load time: {time.perf_counter() - t0:.1f} s")
    print(f"sample rate: {model.sr}")
    print(f"VRAM after load: allocated {gib(torch.cuda.memory_allocated())}, "
          f"peak {gib(torch.cuda.max_memory_allocated())}")

    torch.cuda.reset_peak_memory_stats()
    for i, (name, exag, cfg, text) in enumerate(LINES, start=1):
        torch.manual_seed(SEED)
        t0 = time.perf_counter()
        wav = model.generate(
            text,
            audio_prompt_path=str(ref),
            exaggeration=exag,
            cfg_weight=cfg,
        )
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0
        samples = wav.squeeze().cpu().numpy()
        duration = len(samples) / model.sr
        path = out_dir / f"line{i}_{name}_ex{exag:.2f}_cfg{cfg:.2f}.wav"
        sf.write(str(path), samples, model.sr)
        print(f"[{name}] ex={exag} cfg={cfg} seed={SEED}: "
              f"{elapsed:.1f} s to generate, {duration:.1f} s of audio -> {path}")

    free, total = torch.cuda.mem_get_info()
    print(f"peak VRAM during generation (torch): {gib(torch.cuda.max_memory_allocated())}")
    print(f"device VRAM in use now (all processes): {gib(total - free)} of {gib(total)}")


if __name__ == "__main__":
    main()