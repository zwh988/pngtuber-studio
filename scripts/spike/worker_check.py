"""M3-3 check: drive the real GPU worker without the app (no project, no UI).

Loads the model, generates the text twice (the second run shows steady-state
speed) and prints every event with timings, then the GPU memory in use. With
``--cancel-after N`` it sends a cancel after N finished pieces of the first run,
to see the job stop between pieces and leave no file.

    uv run python scripts\\spike\\worker_check.py --ref "<reference.wav>"
    uv run python scripts\\spike\\worker_check.py --ref "<ref.wav>" --text "<long text>"
    uv run python scripts\\spike\\worker_check.py --ref "<ref.wav>" --trace 20

While the model loads it prints a line every 10 s with the last line of the worker
log. ``--trace N`` makes the worker dump every thread's stack into that log every
N seconds, which shows where a stuck worker waits. ``--load-timeout`` (default
600 s) ends the run instead of waiting for ever.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.voice.chunking import chunk_seed, plan_chunks
from backend.voice.keys import normalize_text
from backend.voice.protocol import (
    CancelCommand,
    CancelledEvent,
    DoneEvent,
    ErrorEvent,
    GenerateCommand,
    LoadCommand,
    ProgressEvent,
    ReadyEvent,
)
from backend.voice.subprocess_worker import SubprocessWorker

DEFAULT_TEXT = (
    "Okay, nine ball, rack looks clean. Let's see if I can run this table. "
    "Oh, that is a perfect break! Three balls dropped, I cannot believe it. "
    "Please, please don't scratch."
)


def gpu_memory() -> str:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return "nvidia-smi not found"
    result = subprocess.run(
        [exe, "--query-gpu=memory.used,memory.total", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or result.stderr.strip()


def last_log_line(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = [line for line in text.splitlines() if line.strip()]
    except OSError:
        return ""
    return lines[-1][:150] if lines else ""


def run_job(
    worker: SubprocessWorker, command: GenerateCommand, cancel_after: int | None
) -> None:
    started = time.perf_counter()
    worker.send(command)
    cancelled = False
    while True:
        event = worker.next_event(1.0)
        if event is None:
            if not worker.alive:
                print("  the worker is gone")
                return
            continue
        elapsed = time.perf_counter() - started
        if isinstance(event, ProgressEvent):
            print(f"  {elapsed:6.1f} s  piece {event.chunks_done}/{event.chunk_count}")
            if (
                cancel_after is not None
                and not cancelled
                and event.chunks_done >= cancel_after
            ):
                print("  -> sending cancel")
                worker.send(CancelCommand(job_id=command.job_id))
                cancelled = True
        elif isinstance(event, DoneEvent):
            print(
                f"  {elapsed:6.1f} s  done: {event.duration_ms / 1000:.1f} s of audio "
                f"-> {event.output_path}"
            )
            return
        elif isinstance(event, CancelledEvent):
            exists = Path(command.output_path).exists()
            print(f"  {elapsed:6.1f} s  cancelled (output file exists: {exists})")
            return
        elif isinstance(event, ErrorEvent):
            print(f"  {elapsed:6.1f} s  ERROR: {event.message} (fatal={event.fatal})")
            return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ref", required=True, help="reference WAV (10-20 s)")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--exaggeration", type=float, default=0.5)
    parser.add_argument("--cfg", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--out", default="scripts/spike/out/worker_check")
    parser.add_argument("--cancel-after", type=int, default=None)
    parser.add_argument("--load-timeout", type=float, default=600.0)
    parser.add_argument(
        "--trace", type=float, default=0.0, help="dump worker stacks every N s"
    )
    args = parser.parse_args()

    ref = Path(args.ref).resolve()
    if not ref.is_file():
        raise SystemExit(f"Reference clip not found: {ref}")
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    chunks = tuple(plan_chunks(normalize_text(args.text)))
    seeds = tuple(chunk_seed(args.seed, i) for i in range(len(chunks)))
    print(f"{len(chunks)} piece(s): {[len(c) for c in chunks]} characters")

    log_path = out / "worker.log"
    if args.trace > 0:
        os.environ["PNGTUBER_WORKER_TRACE"] = str(args.trace)
    worker = SubprocessWorker(log_path=log_path)
    try:
        started = time.perf_counter()
        worker.start()
        worker.send(LoadCommand())
        print("loading the model (import, load and warm-up take about 45 s)...")
        next_beat = started + 10.0
        while True:
            event = worker.next_event(1.0)
            now = time.perf_counter()
            if event is None and now >= next_beat:
                last = last_log_line(log_path)
                print(f"  still loading, {now - started:.0f} s; log: {last}")
                next_beat += 10.0
            if now - started > args.load_timeout:
                raise SystemExit(
                    f"no ready after {args.load_timeout:.0f} s; see {log_path}"
                )
            if isinstance(event, ReadyEvent):
                took = time.perf_counter() - started
                print(f"ready after {took:.1f} s (load + warm-up)")
                print(f"model: {event.model_version}")
                break
            if isinstance(event, ErrorEvent):
                raise SystemExit(f"load failed: {event.message}")
            if event is None and not worker.alive:
                raise SystemExit(f"the worker exited; see {log_path}")
        print(f"GPU memory in use: {gpu_memory()}")

        for number in (1, 2):
            print(f"run {number}:")
            command = GenerateCommand(
                job_id=f"check{number}",
                chunks=chunks,
                seeds=seeds,
                reference_path=str(ref),
                output_path=str(out / f"check{number}.wav"),
                exaggeration=args.exaggeration,
                cfg_weight=args.cfg,
            )
            run_job(worker, command, args.cancel_after if number == 1 else None)
            print(f"  GPU memory in use: {gpu_memory()}")
    finally:
        worker.close()
    print(f"worker log: {log_path}")


if __name__ == "__main__":
    main()
