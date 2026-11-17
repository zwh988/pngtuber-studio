r"""M6 S6 check: a real export of a project, before the export screen exists.

Close the app first (it would save the same project.json). Run from the repo root:

    uv run python scripts\spike\m6_export_check.py --project "D:\path\to\project" --seconds 60

Prints the pre-flight, then writes voice_processed.wav, voice_raw.wav, lines\,
final_1080p.mp4 and video_edited.mp4 into <project>\exports\<date time> (check)\, or
into --out. --seconds exports only the start of the timeline (leave it out for all of
it). Footage is only read. Prints how long each step took.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.export.bundle import mark_incomplete
from backend.export.errors import ExportError
from backend.export.pipeline import ExportOptions, run_export
from backend.export.tools import default_ffmpeg_path, encoder_problem
from backend.export.voicetrack import VoiceCue
from backend.project.session import Session, SessionError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--seconds", type=float, default=None, help="export only this much")
    parser.add_argument("--out", default=None, help="folder to write to (default: the project's exports)")
    parser.add_argument("--overlay", action="store_true", help="also write the avatar PNG sequence")
    parser.add_argument("--no-raw-link", action="store_true", help="no video_raw hard links")
    args = parser.parse_args()

    session = Session()
    session.open_project(args.project)
    tools = encoder_problem()
    report = session.export_preflight(tools_problem=tools)
    print(f"pre-flight: {report.error_count} errors, {report.warning_count} warnings")
    for issue in report.issues:
        when = "" if issue.t_ms is None else f" at {issue.t_ms / 1000:.1f} s"
        print(f"  {issue.severity:7} {issue.kind}{when}: {issue.message}")
    if not report.ok:
        print("stopping: fix the errors first")
        return 1

    stamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
    out = Path(args.out) if args.out else Path(args.project) / "exports" / f"{stamp} (check)"
    started = time.perf_counter()
    marks: dict[str, float] = {}
    last_print = [0.0]

    def on_report(stage: str, fraction: float) -> None:
        now = time.perf_counter()
        marks.setdefault(stage, now)
        if now - last_print[0] > 2 or stage == "done":
            print(f"  {stage:7} {fraction * 100:5.1f}%  ({now - started:6.1f} s)", flush=True)
            last_print[0] = now

    def processed_for(cue: VoiceCue) -> Path:
        path = session.processed_take_path(cue.take_id, cue.stretch)
        if path is None:
            raise ExportError(f"take {cue.take_id} has no file")
        return path

    def raw_for(cue: VoiceCue) -> tuple[np.ndarray, int]:
        found = session.aligned_raw_take(cue.take_id, cue.stretch)
        if found is None:
            raise ExportError(f"take {cue.take_id} has no file")
        return found

    inputs = session.export_inputs()
    limit = None if args.seconds is None else round(args.seconds * 1000)
    try:
        result = run_export(
            inputs,
            out,
            ffmpeg=default_ffmpeg_path(),
            processed_for=processed_for,
            raw_for=raw_for,
            report=on_report,
            options=ExportOptions(
                include_overlay=args.overlay or inputs.project.export.include_avatar_overlay,
                include_raw_links=not args.no_raw_link and inputs.project.export.include_raw_video_link,
                limit_ms=limit,
            ),
        )
    except (ExportError, SessionError) as exc:
        print(f"export failed: {exc}")
        print(f"left in {mark_incomplete(out)}")
        return 1
    total = time.perf_counter() - started
    length_s = result.render.frames / float(result.fmt.fps)
    print(f"written to {out}")
    print(
        f"{result.fmt.width}x{result.fmt.height} at {result.fmt.fps_text} fps, {result.render.frames} frames "
        f"({length_s:.1f} s), avatar {'yes' if result.with_avatar else 'no'} ({result.render.avatar_frames} frames fed)"
    )
    print(
        f"voice: {result.voice.lines} lines, peak {result.voice.peak:.3f}, cut {result.voice.cut_ms} ms; "
        f"render {result.render.seconds:.1f} s; total {total:.1f} s "
        f"({length_s / max(result.render.seconds, 0.001):.2f}x realtime)"
    )
    print(f"avatar PNG frames: {result.overlay_frames}; raw video linked: {result.raw.linked}, listed: {result.raw.listed}")
    manifest = json.loads((out / "export.json").read_text(encoding="utf-8"))
    print(f"step seconds: {manifest['seconds']}")
    for name in ("final_1080p.mp4", "video_edited.mp4", "voice_processed.wav", "voice_raw.wav"):
        path = out / name
        size = path.stat().st_size / 1e6 if path.exists() else 0
        print(f"  {name:20} {size:8.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
