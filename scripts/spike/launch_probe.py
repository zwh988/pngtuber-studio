"""M3-3 probe: does the way the worker is launched change how long Chatterbox
takes to import?

The worker imports Chatterbox in about 5 s when run from a console, but far slower
when the backend launches it. This starts the same import in a child process with
one launch setting changed at a time and prints the wall-clock time of each, so
the setting that slows it down shows up.

    uv run python scripts\\spike\\launch_probe.py
    uv run python scripts\\spike\\launch_probe.py --timeout 200
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

CODE = "from chatterbox.tts import ChatterboxTTS"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
WORKER_ENV = {"PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def hidden_window() -> Any:
    """A STARTUPINFO that starts the child with its window hidden (Windows)."""
    startupinfo = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo is None:
        return None
    info = startupinfo()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = subprocess.SW_HIDE
    return info


def run_once(timeout_s: float, **kwargs: Any) -> str:
    started = time.perf_counter()
    try:
        subprocess.run(
            [sys.executable, "-c", CODE], timeout=timeout_s, check=False, **kwargs
        )
    except subprocess.TimeoutExpired:
        return f"TIMEOUT after {timeout_s:.0f} s"
    return f"{time.perf_counter() - started:5.1f} s"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--timeout", type=float, default=150.0)
    args = parser.parse_args()

    pipe = subprocess.PIPE
    env = {**os.environ, **WORKER_ENV}
    print(f"import: {CODE}\n(each run can take up to {args.timeout:.0f} s)")
    with (
        tempfile.TemporaryDirectory() as folder,
        (Path(folder) / "child.log").open("wb") as log,
    ):
        piped: dict[str, Any] = {"stdin": pipe, "stdout": pipe, "stderr": log}
        variants: list[tuple[str, dict[str, Any]]] = [
            ("1 warm-up, result ignored (fills the file cache)", {}),
            ("2 inherit everything, like tts_test", {}),
            ("3 stdin and stdout piped", {"stdin": pipe, "stdout": pipe}),
            ("4 piped, stderr to a file", piped),
            (
                "5 piped, stderr to a file, CREATE_NO_WINDOW",
                {**piped, "creationflags": NO_WINDOW},
            ),
            (
                "6 as 5, plus the worker's environment variables",
                {**piped, "creationflags": NO_WINDOW, "env": env},
            ),
            (
                "7 hidden window through STARTUPINFO, no CREATE_NO_WINDOW",
                {**piped, "startupinfo": hidden_window()},
            ),
        ]
        for name, kwargs in variants:
            print(f"{name:<62} ", end="", flush=True)
            print(run_once(args.timeout, **kwargs), flush=True)


if __name__ == "__main__":
    main()
