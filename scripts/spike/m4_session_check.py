r"""M4 S3b check: open a real project, compare timeline lengths with processed audio.

Close the app first (it would save the same project.json). Run from the repo root:

    uv run python scripts\spike\m4_session_check.py --project "D:\path\to\project"

Opening works like the app does: it saves only if it finds new footage. Processed
files are written to the project's media/takes_fx (they can be re-created). For every
placed line it prints the recorded length, the length the timeline now uses, and the
length of the processed file the media route serves; the last two must match.
"""

import argparse
import io
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import soundfile
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.audio.trim import samples_to_ms
from backend.project.session import Session


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()

    session = Session()
    session.open_project(args.project)
    timeline = session.timeline()
    print(f"fx_version {timeline.fx_version}   game audio {timeline.game_audio_db} dB")
    print(f"placements {len(timeline.placements)}")
    client = TestClient(create_app(session=session))

    bad = 0
    ranged = False
    for item in timeline.placements:
        label = f"{item.line_text[:28]!r:32} stretch {item.stretch:.3f}"
        if item.take_id is None or item.duration_ms is None:
            print(f"{label} no take to play")
            continue
        recorded = next(
            t.duration_ms for t in session.takes(item.line_id) if t.id == item.take_id
        )
        url = (
            f"/media/take/{item.take_id}?processed=1"
            f"&stretch={item.stretch}&v={timeline.fx_version}"
        )
        start = time.perf_counter()
        response = client.get(url)
        first = time.perf_counter() - start
        if response.status_code != 200:
            print(f"{label} HTTP {response.status_code}: {response.text[:100]}")
            bad += 1
            continue
        start = time.perf_counter()
        client.get(url)
        second = time.perf_counter() - start
        info = soundfile.info(io.BytesIO(response.content))
        served = samples_to_ms(int(info.frames), int(info.samplerate))
        verdict = "ok" if served == item.duration_ms else "MISMATCH"
        bad += verdict != "ok"
        print(
            f"{label} recorded {recorded} ms, timeline {item.duration_ms} ms, "
            f"served {served} ms [{verdict}]  first {first * 1000:.0f} ms, "
            f"again {second * 1000:.0f} ms"
        )
        if not ranged:
            ranged = True
            part = client.get(url, headers={"Range": "bytes=0-99"})
            size = len(part.content)
            print(f"   range request: HTTP {part.status_code}, {size} bytes")

    print("ALL MATCH" if bad == 0 else f"{bad} PROBLEM(S)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
