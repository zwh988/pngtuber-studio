"""M0-2 follow-up: same line across a settings grid, per reference clip. Throwaway."""
import argparse
import time
from pathlib import Path

import soundfile as sf
import torch

TEXT = "Oh, that is a perfect break! Three balls dropped, I cannot believe it!"
GRID = [(0.5, 0.5), (0.8, 0.3), (1.0, 0.3), (1.2, 0.2)]
SEED = 1234


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True, nargs="+", help="one or more reference WAVs")
    parser.add_argument("--out", default="scripts/spike/out/grid")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    from chatterbox.tts import ChatterboxTTS

    model = ChatterboxTTS.from_pretrained(device="cuda")
    for ref_str in args.ref:
        ref = Path(ref_str)
        if not ref.is_file():
            print(f"skip, not found: {ref}")
            continue
        for exag, cfg in GRID:
            torch.manual_seed(SEED)
            t0 = time.perf_counter()
            wav = model.generate(TEXT, audio_prompt_path=str(ref), exaggeration=exag, cfg_weight=cfg)
            torch.cuda.synchronize()
            samples = wav.squeeze().cpu().numpy()
            name = f"{ref.stem[:30]}_ex{exag:.2f}_cfg{cfg:.2f}.wav"
            sf.write(str(out_dir / name), samples, model.sr)
            print(f"{name}: {time.perf_counter() - t0:.1f} s, {len(samples) / model.sr:.1f} s audio")


if __name__ == "__main__":
    main()