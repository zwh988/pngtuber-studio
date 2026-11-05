r"""M4 S3c check: drive the voice chain API against a real project, then undo it all.

Close the app first. Run from the repo root:

    uv run python scripts\spike\m4_fx_check.py --project "D:\path\to\project"

It applies a different preset, changes the game audio level, fetches processed audio
under the new chain, tries two invalid edits, and finally undoes every change it made.
The last line says whether the project is back to how it started. If the script dies
half way, open the project in the app and press Undo until the voice chain is as it
was (processed files it made are harmless and can be re-created).
"""

import argparse
import io
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import soundfile
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.audio.trim import samples_to_ms
from backend.project.session import Session

problems: list[str] = []


def check(ok: bool, message: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + message)
    if not ok:
        problems.append(message)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()

    session = Session()
    session.open_project(args.project)
    client = TestClient(create_app(session=session))

    def get(url: str) -> Any:
        response = client.get(url)
        assert response.status_code == 200, (url, response.text[:200])
        return response.json()

    before = get("/api/fx")
    names = [p["name"] for p in before["presets"]]
    print(
        f"start: fx_version {before['fx_version']}, "
        f"game audio {before['game_audio_db']} dB, presets {names}"
    )
    print(f"       processing {before['processing']}, undo {before['undo_label']!r}")
    applied = 0
    try:
        preset = next(
            (p for p in before["presets"] if p["chain"] != before["chain"]), None
        )
        if preset is None:
            print("no preset differs from the current chain; nothing to try")
            return
        print(f"\napply preset {preset['name']!r}")
        body = {"ops": [{"op": "set_fx_chain", "chain": preset["chain"]}]}
        response = client.post("/api/fx/edit", json=body)
        check(response.status_code == 200, f"edit accepted, {response.status_code}")
        applied += 1
        after = response.json()
        check(after["chain"] == preset["chain"], "the chain is the preset's")
        check(after["can_undo"], "undo is available")
        print(f"       fx_version {before['fx_version']} -> {after['fx_version']}")
        check(
            after["fx_version"] != before["fx_version"],
            "the version changed (it stays if the preset sounds the same)",
        )

        again = client.post("/api/fx/edit", json=body).json()
        same = again["fx_version"] == after["fx_version"]
        check(same, "the same chain again: no change")

        timeline = get("/api/timeline")
        same = timeline["fx_version"] == after["fx_version"]
        check(same, "the timeline has the new version")

        print("\nprocessed audio under the new chain")
        for item in timeline["placements"]:
            if item["take_id"] is None:
                continue
            url = (
                f"/media/take/{item['take_id']}?processed=1"
                f"&stretch={item['stretch']}&v={after['fx_version']}"
            )
            start = time.perf_counter()
            served = client.get(url)
            took = (time.perf_counter() - start) * 1000
            ok = served.status_code == 200
            name = item["line_text"][:30]
            check(ok, f"{name!r} HTTP {served.status_code}, {took:.0f} ms")
            if ok:
                info = soundfile.info(io.BytesIO(served.content))
                ms = samples_to_ms(int(info.frames), int(info.samplerate))
                check(ms == item["duration_ms"], f"length {ms} ms = timeline")
        done = get("/api/fx")["processing"]
        check(done["ready"] == done["total"], f"processing is complete {done}")

        print("\ngame audio level")
        level = client.post(
            "/api/fx/edit", json={"ops": [{"op": "set_game_audio_db", "db": -6}]}
        )
        check(level.status_code == 200, f"level accepted (HTTP {level.status_code})")
        applied += 1
        check(get("/api/timeline")["game_audio_db"] == -6.0, "timeline carries -6 dB")

        print("\ninvalid edits")
        bad_chain = dict(preset["chain"], eq_bass_db=99.0)
        refused = client.post(
            "/api/fx/edit", json={"ops": [{"op": "set_fx_chain", "chain": bad_chain}]}
        )
        check(refused.status_code == 400, f"EQ 99 dB refused, {refused.status_code}")
        print(f"       message: {refused.json().get('detail')}")
        loud = client.post(
            "/api/fx/edit", json={"ops": [{"op": "set_game_audio_db", "db": 99}]}
        )
        check(loud.status_code == 400, f"level 99 dB refused, {loud.status_code}")
        unchanged = get("/api/fx")
        check(
            unchanged["fx_version"] == after["fx_version"]
            and unchanged["game_audio_db"] == -6.0,
            "refused edits changed nothing",
        )
    finally:
        print(f"\nundo {applied} change(s)")
        for _ in range(applied):
            client.post("/api/timeline/undo")

    end = get("/api/fx")
    restored = (
        end["fx_version"] == before["fx_version"]
        and end["game_audio_db"] == before["game_audio_db"]
        and end["chain"] == before["chain"]
    )
    check(restored, "the project is back to how it started")
    print("ALL OK" if not problems else f"{len(problems)} PROBLEM(S)")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
