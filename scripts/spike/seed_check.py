"""M3-S1 spike: does torch.manual_seed before generate() repeat the same audio? Throwaway."""
import argparse
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

TEXT = "Okay, nine ball, rack looks clean. Let's see if I can run this table."
EXAG = 0.50
CFG = 0.50
# Order matters: A and B are the same seed back to back, C is a different seed,
# D repeats the first seed after C, to show the result does not depend on call history.
RUNS = [("A", 1234), ("B", 1234), ("C", 99), ("D", 1234)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True, help="path to reference WAV (10-20 s)")
    parser.add_argument("--out", default="scripts/spike/out/seed_check", help="output folder (git-ignored)")
    parser.add_argument("--text", default=TEXT)
    args = parser.parse_args()

    ref = Path(args.ref)
    out_dir = Path(args.out)
    if not ref.is_file():
        raise SystemExit(f"Reference clip not found: {ref}")
    out_dir.mkdir(parents=True, exist_ok=True)

    from chatterbox.tts import ChatterboxTTS

    model = ChatterboxTTS.from_pretrained(device="cuda")

    # Warm-up run (first generation after load is slow); output discarded.
    torch.manual_seed(1)
    model.generate(args.text, audio_prompt_path=str(ref), exaggeration=EXAG, cfg_weight=CFG)
    torch.cuda.synchronize()

    results: dict[str, np.ndarray] = {}
    for label, seed in RUNS:
        torch.manual_seed(seed)
        t0 = time.perf_counter()
        wav = model.generate(args.text, audio_prompt_path=str(ref), exaggeration=EXAG, cfg_weight=CFG)
        torch.cuda.synchronize()
        samples = wav.squeeze().cpu().numpy()
        results[label] = samples
        sf.write(str(out_dir / f"run{label}_seed{seed}.wav"), samples, model.sr)
        print(f"run {label} seed={seed}: {time.perf_counter() - t0:.1f} s, "
              f"{len(samples)} samples ({len(samples) / model.sr:.2f} s)")

    def compare(x: str, y: str) -> None:
        a, b = results[x], results[y]
        if len(a) != len(b):
            print(f"{x} vs {y}: DIFFERENT LENGTH ({len(a)} vs {len(b)})")
            return
        diff = float(np.max(np.abs(a - b)))
        verdict = "IDENTICAL" if diff == 0.0 else ("near-identical" if diff < 1e-4 else "DIFFERENT")
        print(f"{x} vs {y}: max abs diff {diff:.6g} -> {verdict}")

    print()
    compare("A", "B")  # same seed, back to back
    compare("A", "D")  # same seed, after another seed ran in between
    compare("A", "C")  # different seed: should differ


if __name__ == "__main__":
    main()
