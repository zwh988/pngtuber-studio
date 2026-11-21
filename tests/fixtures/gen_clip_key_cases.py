"""Writes tests/fixtures/clip_key_cases.json from backend.export.clip_keys.

Run from the repo root after a deliberate change to the clip-key maths:
``uv run python tests/fixtures/gen_clip_key_cases.py``. The tests then check the
TypeScript twin (frontend/src/clipKeys.ts) against the new table.
"""
import json
from dataclasses import asdict
from pathlib import Path

from backend.export.clip_keys import clip_values_at
from backend.project.schema import LaneClip

LANE, IMG, CLIP = "1" * 12, "2" * 12, "3" * 12


def key(
    n: int, prop: str, t: int, value: float, interp: str = "linear", strength: float = 1.0
) -> dict[str, object]:
    return {"id": f"{n:012x}", "prop": prop, "t_ms": t, "value": value,
            "interpolation": interp, "ease_strength": strength}


CASES = [
    ("no keys: the clip's own values", 1000, [], [0, 1000, 2500, 9000]),
    ("linear opacity fade in, held before and after", 1000,
     [key(1, "opacity", 0, 0.0), key(2, "opacity", 1000, 1.0)],
     [0, 1000, 1250, 1500, 1999, 2000, 4000]),
    ("each easing on its own property", 0,
     [key(1, "x", 0, 0.1, "ease_in_out"), key(2, "x", 2000, 0.9),
      key(3, "y", 0, 0.2, "ease_out", 2.0), key(4, "y", 2000, 0.8),
      key(5, "scale", 0, 0.5, "ease_in", 0.5), key(6, "scale", 2000, 1.5),
      key(7, "opacity", 0, 1.0, "ease_in", 1.5), key(8, "opacity", 2000, 0.0)],
     [0, 250, 500, 1000, 1500, 1750, 2000]),
    ("hold jumps at the next key", 500,
     [key(1, "x", 0, 0.2, "hold"), key(2, "x", 1000, 0.7, "hold"), key(3, "x", 2000, 0.4)],
     [500, 1000, 1499, 1500, 2499, 2500, 3000]),
    ("two keys at one time: the last wins", 0,
     [key(1, "scale", 1000, 0.3), key(2, "scale", 1000, 0.6), key(3, "scale", 2000, 1.2)],
     [0, 1000, 1500, 2000]),
    ("a key before the clip start still shapes the curve (after a trim)", 2000,
     [key(1, "x", -1000, 0.0, "ease_in_out"), key(2, "x", 1000, 1.0)],
     [2000, 2500, 3000, 3500]),
    ("one key: a constant that overrides the clip value", 0,
     [key(1, "opacity", 700, 0.25)], [0, 700, 5000]),
    ("frame times that are not whole ms (30 fps export)", 0,
     [key(1, "y", 0, 0.0, "ease_out"), key(2, "y", 1000, 1.0)],
     [33.333333333333336, 66.66666666666667, 500.5, 966.6666666666666]),
]

out = []
for name, start, keys, samples in CASES:
    clip = LaneClip(id=CLIP, lane_id=LANE, image_id=IMG, timeline_ms=start, out_ms=4000,
                    x=0.5, y=0.4, scale=0.8, opacity=0.9, keys=keys)
    out.append({
        "name": name,
        "clip": {"timeline_ms": start, "x": 0.5, "y": 0.4, "scale": 0.8, "opacity": 0.9, "keys": keys},
        "samples": [{"t": t, "expect": asdict(clip_values_at(clip, t))} for t in samples],
    })
Path(__file__).with_name("clip_key_cases.json").write_text(
    json.dumps({"_note": "Generated from backend/export/clip_keys.py; checked by "
                "tests/test_clip_key_eval.py and frontend/src/clipKeys.test.ts.", "cases": out},
               indent=1) + "\n", encoding="utf-8")
print(len(out), "cases")
