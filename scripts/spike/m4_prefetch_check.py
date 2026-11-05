r"""M4 S3d check: prefetch and clean-up on a real project.

Close the app first. Run from the repo root:

    uv run python scripts\spike\m4_prefetch_check.py --project "D:\path\to\project"

It first deletes the processed files in the project's media/takes_fx (they can all be
re-created; raw takes are never touched), then:
  1. opens the project with prefetch on and times how long the placed lines take to
     be rendered in the background;
  2. applies a different preset and times that again;
  3. undoes it, and runs the clean-up with no age limit to show which files go (only
     the ones the current chain no longer wants);
  4. confirms the raw takes are all still there.
Every change it makes is undone at the end.
"""

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.audio.cleanup import run_cleanup
from backend.project.fx_ops import SetFxChainOp
from backend.project.session import Session

PROCESSED = re.compile(r"^[0-9a-f]{16}\.wav$")
problems: list[str] = []


def check(ok: bool, message: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + message)
    if not ok:
        problems.append(message)


def wait_until_ready(session: Session, limit: float = 60.0) -> tuple[float, str]:
    start = time.perf_counter()
    while True:
        processing = session.fx().processing
        elapsed = time.perf_counter() - start
        if processing.error:
            return elapsed, f"error: {processing.error}"
        if processing.ready >= processing.total:
            return elapsed, f"{processing.ready}/{processing.total} ready"
        if elapsed > limit:
            return elapsed, f"gave up at {processing.ready}/{processing.total}"
        time.sleep(0.02)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()

    folder = Path(args.project)
    fx_dir = folder / "media" / "takes_fx"
    raw_dir = folder / "media" / "takes_raw"
    raw_before = sorted(p.name for p in raw_dir.glob("*.wav"))
    removed = 0
    for path in fx_dir.glob("*.wav") if fx_dir.is_dir() else []:
        if PROCESSED.match(path.name):
            path.unlink()
            removed += 1
    print(f"removed {removed} processed file(s), {len(raw_before)} raw take(s) kept")

    session = Session()
    applied = 0
    try:
        session.open_project(args.project)
        session.enable_prefetch()
        elapsed, state = wait_until_ready(session)
        print(f"\nafter open: {state} in {elapsed * 1000:.0f} ms (with library load)")
        check("ready" in state, "placed lines rendered in the background")
        wanted = {p.name for p in fx_dir.glob("*.wav")}
        print(f"       {len(wanted)} processed file(s) now exist")

        fx = session.fx()
        preset = next((p for p in fx.presets if p.chain != fx.chain), None)
        if preset is None:
            print("no preset differs from the current chain; skipping the change")
        else:
            session.edit_fx([SetFxChainOp(chain=preset.chain)])
            applied += 1
            elapsed, state = wait_until_ready(session)
            print(f"\nafter preset {preset.name!r}: {state} in {elapsed * 1000:.0f} ms")
            check("ready" in state, "a chain change re-renders every placed line")
            session.undo()
            applied -= 1
            elapsed, state = wait_until_ready(session)
            print(f"after undo: {state} in {elapsed * 1000:.0f} ms (already rendered)")
            check("ready" in state, "undo needs no new rendering")

        before = {p.name for p in fx_dir.glob("*.wav")}
        report = run_cleanup(fx_dir, raw_dir, wanted, min_age_s=0)
        after = {p.name for p in fx_dir.glob("*.wav")}
        print(f"\nclean-up with no age limit deleted {len(report.deleted)} file(s)")
        check(wanted <= after, "every file the current chain wants was kept")
        check(after == wanted, "the files of the other preset are gone")
        print(f"       before {len(before)} file(s), after {len(after)}")
    finally:
        for _ in range(applied):
            session.undo()
        session.shutdown_prefetch()

    raw_after = sorted(p.name for p in raw_dir.glob("*.wav"))
    check(raw_after == raw_before, "all raw takes are still there")
    print("ALL OK" if not problems else f"{len(problems)} PROBLEM(S)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
