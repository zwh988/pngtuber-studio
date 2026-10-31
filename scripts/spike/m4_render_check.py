r"""M4 S3a check: render one real take through a voice preset and print the numbers.

Run from the repo root (PowerShell):

    uv run python scripts\spike\m4_render_check.py --raw "D:\path\to\take.wav" --preset Warm

Options: --stretch 1.08 (speed-up factor), --target -16 (loudness target in LUFS).
The take is copied into scripts/spike/out/m4_check/, so nothing in a project is
touched. The processed file is written there too, so you can listen to it.
"""

import argparse
import hashlib
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import pyloudnorm

from backend.audio.chainspec import processing_spec
from backend.audio.fxpresets import load_fx_presets_file
from backend.audio.loudness import peak_dbfs
from backend.audio.processed import (
    TrimCache,
    ensure_processed,
    processed_path,
    trim_bounds_for,
)
from backend.audio.render import read_mono
from backend.audio.trim import (
    processed_duration_ms,
    samples_to_ms,
    trimmed_duration_ms,
)


def lufs(samples: np.ndarray, rate: int) -> float | None:
    if samples.size < rate * 0.4:
        return None
    return float(pyloudnorm.Meter(rate).integrated_loudness(samples.astype(np.float64)))


def fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--preset", default="Clean")
    parser.add_argument("--stretch", type=float, default=1.0)
    parser.add_argument("--target", type=float, default=None)
    args = parser.parse_args()

    presets = load_fx_presets_file()
    if args.preset not in presets:
        sys.exit(f"unknown preset {args.preset!r}; choose from {sorted(presets)}")
    chain = presets[args.preset]
    if args.target is not None:
        chain = chain.model_copy(update={"loudness_target_lufs": args.target})
    spec = processing_spec(chain)

    work = ROOT / "scripts" / "spike" / "out" / "m4_check"
    raw = work / "media" / "takes_raw" / args.raw.name
    raw.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.raw, raw)
    raw_hash = hashlib.sha256(raw.read_bytes()).hexdigest()

    cache = TrimCache()
    start = time.perf_counter()
    bounds = trim_bounds_for(raw, cache)
    trim_s = time.perf_counter() - start
    rate = bounds.sample_rate

    dest = processed_path(raw, raw_hash, args.stretch, spec)
    dest.unlink(missing_ok=True)
    start = time.perf_counter()
    out = ensure_processed(raw, raw_hash, args.stretch, spec, cache=cache)
    first_s = time.perf_counter() - start
    start = time.perf_counter()
    ensure_processed(raw, raw_hash, args.stretch, spec, cache=cache)
    second_s = time.perf_counter() - start

    before, _ = read_mono(raw)
    after, out_rate = read_mono(out)
    expected_ms = processed_duration_ms(bounds, args.stretch)
    print(f"preset            {args.preset}  (target {chain.loudness_target_lufs} LUFS)")
    print(f"stretch           {args.stretch}")
    print(f"raw length        {samples_to_ms(bounds.total, rate)} ms")
    print(
        f"speech bounds     {samples_to_ms(bounds.start, rate)} .. "
        f"{samples_to_ms(bounds.end, rate)} ms  (silent={bounds.silent})"
    )
    print(f"trimmed length    {trimmed_duration_ms(bounds)} ms")
    print(f"expected length   {expected_ms} ms")
    print(f"processed length  {samples_to_ms(after.size, out_rate)} ms")
    print(f"LUFS before/after {fmt(lufs(before, rate))} / {fmt(lufs(after, out_rate))}")
    print(f"peak before/after {peak_dbfs(before):.2f} / {peak_dbfs(after):.2f} dBFS")
    print(f"measure trim      {trim_s * 1000:.0f} ms")
    print(f"first render      {first_s * 1000:.0f} ms")
    print(f"second call       {second_s * 1000:.0f} ms (reuse)")
    print(f"raw unchanged     {hashlib.sha256(raw.read_bytes()).hexdigest() == raw_hash}")
    print(f"listen to         {out}")


if __name__ == "__main__":
    main()
