"""M3-3 probe 2: which part of the worker's own setup slows the Chatterbox import?

launch_probe.py showed that the launch settings are innocent (7 to 8 s each). The
worker differs from that probe in three ways: a thread blocked reading stdin, our
own modules imported first, and fd 1 redirected to stderr. This runs the same
import with each of them added (the child times only the Chatterbox import) and
prints the time.

    uv run python scripts\\spike\\thread_probe.py
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

THREAD = (
    "import sys, threading\n"
    "threading.Thread(\n"
    "    target=lambda: [None for _ in iter(sys.stdin.buffer.readline, b'')],\n"
    "    daemon=True,\n"
    ").start()\n"
)
PRIVATE_THREAD = (
    "import os, sys, threading\n"
    "_fd = os.dup(0)\n"
    "_null = os.open(os.devnull, os.O_RDONLY)\n"
    "os.dup2(_null, 0)\n"
    "os.close(_null)\n"
    "_pipe = os.fdopen(_fd, 'rb')\n"
    "threading.Thread(\n"
    "    target=lambda: [None for _ in iter(_pipe.readline, b'')],\n"
    "    daemon=True,\n"
    ").start()\n"
)
MODULES = "import backend.voice.workerloop\n"
REDIRECT = "import os, sys\nos.dup2(2, 1)\nsys.stdout = sys.stderr\n"
TIMED = (
    "import sys, time\n"
    "_start = time.perf_counter()\n"
    "from chatterbox.tts import ChatterboxTTS\n"
    "print(f'import took {time.perf_counter() - _start:.1f} s', file=sys.stderr)\n"
)

VARIANTS = [
    ("1 control: nothing added", ""),
    ("2 a thread blocked reading stdin", THREAD),
    ("3 our modules imported first", MODULES),
    ("4 fd 1 redirected to stderr", REDIRECT),
    ("5 all three, like the worker", MODULES + REDIRECT + THREAD),
    ("6 FIX: reader on a private fd, fd 0 -> NUL", PRIVATE_THREAD),
    ("7 FIX with the rest, like the new worker", MODULES + REDIRECT + PRIVATE_THREAD),
]


def run_variant(prelude: str, timeout_s: float) -> str:
    process = subprocess.Popen(
        [sys.executable, "-c", prelude + TIMED],
        cwd=ROOT,
        stdin=subprocess.PIPE,  # held open, so a reading thread really blocks
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        return f"TIMEOUT after {timeout_s:.0f} s"
    finally:
        if process.stdin is not None:
            process.stdin.close()
    err = process.stderr.read() if process.stderr is not None else ""
    if process.stderr is not None:
        process.stderr.close()
    for line in reversed(err.splitlines()):
        if line.startswith("import took"):
            return line
    return "no timing printed: " + err.strip()[-200:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument(
        "--variants", type=int, nargs="*", help="only these numbers, e.g. 6 7"
    )
    args = parser.parse_args()
    print(f"(each run can take up to {args.timeout:.0f} s)")
    for name, prelude in VARIANTS:
        if args.variants and int(name.split()[0]) not in args.variants:
            continue
        print(f"{name:<40} ", end="", flush=True)
        print(run_variant(prelude, args.timeout), flush=True)


if __name__ == "__main__":
    main()
