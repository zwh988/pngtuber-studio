"""Clip-key evaluation (keyframes task, step 6) against the shared case table.

``frontend/src/clipKeys.test.ts`` checks the preview's TypeScript evaluation against the
same table, so the preview and the export compute the same values (rule 5).
"""

import json
from pathlib import Path

import pytest

from backend.export.clip_keys import clip_values_at, keyed_props
from backend.project.schema import LaneClip

TABLE = json.loads(
    (Path(__file__).parent / "fixtures" / "clip_key_cases.json").read_text(encoding="utf-8")
)
CASES = TABLE["cases"]


def make_clip(spec: dict) -> LaneClip:
    return LaneClip(
        id="3" * 12, lane_id="1" * 12, image_id="2" * 12, out_ms=4000, **spec
    )


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_matches_the_shared_table(case: dict) -> None:
    clip = make_clip(case["clip"])
    for sample in case["samples"]:
        got = clip_values_at(clip, sample["t"])
        for prop, want in sample["expect"].items():
            assert getattr(got, prop) == pytest.approx(want, abs=1e-12), (sample["t"], prop)


def test_table_values_by_hand() -> None:
    """A few table entries worked out from the curve formulas, so the table is not
    just the code checking itself."""
    by_name = {c["name"]: c for c in CASES}
    fade = {s["t"]: s["expect"]["opacity"] for s in by_name["linear opacity fade in, held before and after"]["samples"]}
    assert (fade[0], fade[1250], fade[1500], fade[4000]) == (0.0, 0.25, 0.5, 1.0)
    each = {s["t"]: s["expect"] for s in by_name["each easing on its own property"]["samples"]}
    assert each[1000]["x"] == pytest.approx(0.1 + 0.8 * 0.5)  # in-out, halfway
    assert each[1000]["y"] == pytest.approx(0.2 + 0.6 * (1 - 0.5**3))  # out, strength 2
    assert each[1000]["scale"] == pytest.approx(0.5 + (0.5 - 0.125))  # in, strength 0.5
    hold = {s["t"]: s["expect"]["x"] for s in by_name["hold jumps at the next key"]["samples"]}
    assert (hold[1499], hold[1500]) == (0.2, 0.7)


def test_keyed_props() -> None:
    assert keyed_props(make_clip(CASES[0]["clip"])) == set()
    assert keyed_props(make_clip(CASES[2]["clip"])) == {"x", "y", "scale", "opacity"}
