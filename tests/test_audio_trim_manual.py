"""Manual take trim maths (M5-0): validation, region, measuring inside it, fades, key, sidecar."""

import json

import numpy as np
import pytest

from backend.audio.trim import (
    MANUAL_FADE_MS,
    ManualTrimError,
    TrimBounds,
    apply_edge_fades,
    bounds_from_data,
    bounds_to_data,
    edge_fades,
    find_speech_bounds,
    find_speech_bounds_in_region,
    manual_region,
    processed_duration_ms,
    spec_with_manual_trim,
    trim_params,
    trimmed_duration_ms,
    validate_manual_trim,
)
from backend.voice.keys import processed_key

SR = 8000  # 8 samples per ms; a 10 ms frame is 80 samples


def _tone(ms: int, amp: float = 0.5) -> np.ndarray:
    n = SR * ms // 1000
    return amp * np.sin(2 * np.pi * 440 * np.arange(n) / SR)


def _silence(ms: int) -> np.ndarray:
    return np.zeros(SR * ms // 1000)


def _take() -> np.ndarray:
    """500 ms silence, 500 ms tone, 500 ms silence (12000 samples)."""
    return np.concatenate([_silence(500), _tone(500), _silence(500)])


# --- validate_manual_trim ---------------------------------------------------------


def test_validate_no_cut_and_edge_cuts_normalise_to_none() -> None:
    assert validate_manual_trim(None, None, 3000) == (None, None)
    assert validate_manual_trim(0, None, 3000) == (None, None)
    assert validate_manual_trim(None, 3000, 3000) == (None, None)
    assert validate_manual_trim(0, 3000, 3000) == (None, None)


def test_validate_keeps_real_cuts() -> None:
    assert validate_manual_trim(100, 2900, 3000) == (100, 2900)
    assert validate_manual_trim(100, None, 3000) == (100, None)
    assert validate_manual_trim(None, 2900, 3000) == (None, 2900)


def test_validate_refuses_bad_cuts() -> None:
    bad = [
        (2900, 100),  # start after end
        (500, 500),  # nothing kept
        (100, 250),  # under the minimum kept
        (None, 3001),  # past the end
        (-1, None),
        (True, None),
        (1.5, None),
    ]
    for start, end in bad:
        with pytest.raises(ManualTrimError):
            validate_manual_trim(start, end, 3000)  # type: ignore[arg-type]
    with pytest.raises(ManualTrimError):
        validate_manual_trim(None, None, 0)


def test_validate_short_take_cannot_be_cut_but_no_cut_is_fine() -> None:
    assert validate_manual_trim(None, None, 100) == (None, None)
    with pytest.raises(ManualTrimError):
        validate_manual_trim(10, None, 100)


# --- manual_region ----------------------------------------------------------------


def test_region_without_cuts_is_the_whole_take() -> None:
    assert manual_region(12000, SR, None, None) == (0, 12000)


def test_region_converts_ms_to_samples_and_clamps() -> None:
    assert manual_region(12000, SR, 200, 1300) == (1600, 10400)
    assert manual_region(12000, SR, None, 5000) == (0, 12000)


def test_region_that_leaves_nothing_raises() -> None:
    with pytest.raises(ValueError):
        manual_region(12000, SR, 1500, 100)
    with pytest.raises(ValueError):
        manual_region(12000, SR, 2000, None)


def test_region_of_an_empty_take() -> None:
    assert manual_region(0, SR, None, None) == (0, 0)


# --- measuring inside the region -------------------------------------------------


def test_baseline_bounds_of_the_synthetic_take() -> None:
    bounds = find_speech_bounds(_take(), SR)
    assert (bounds.start, bounds.end) == (3680, 8640)


def test_region_over_the_whole_take_equals_the_plain_measure() -> None:
    take = _take()
    assert find_speech_bounds_in_region(take, SR, 0, take.size) == find_speech_bounds(take, SR)


def test_click_before_the_cut_is_ignored() -> None:
    take = _take()
    take[800:960] = 0.5  # a 20 ms click at 100 ms
    assert find_speech_bounds(take, SR).start == 480
    inside = find_speech_bounds_in_region(take, SR, 1600, 10400)  # cut from 200 ms
    assert (inside.start, inside.end) == (3680, 8640)
    assert inside.total == take.size
    assert not inside.silent


def test_padding_never_reaches_past_the_cut() -> None:
    take = _take()
    inside = find_speech_bounds_in_region(take, SR, 3840, take.size)  # 20 ms before speech
    assert inside.start == 3840
    assert inside.end == 8640


def test_region_with_nothing_loud_is_kept_whole() -> None:
    inside = find_speech_bounds_in_region(_take(), SR, 0, 3200)
    assert (inside.start, inside.end, inside.silent) == (0, 3200, True)
    assert inside.total == 12000


def test_bad_region_raises() -> None:
    with pytest.raises(ValueError):
        find_speech_bounds_in_region(_take(), SR, 100, 99999)
    with pytest.raises(ValueError):
        find_speech_bounds_in_region(_take(), SR, 500, 100)


# --- lengths follow the manual region --------------------------------------------


def test_lengths_use_the_kept_region() -> None:
    bounds = TrimBounds(1600, 10400, 12000, SR)
    assert trimmed_duration_ms(bounds) == 1100
    assert processed_duration_ms(bounds, 1.0) == 1100
    assert processed_duration_ms(bounds, 1.25) == 880


# --- fades --------------------------------------------------------------------------


def test_fades_only_where_the_kept_range_sits_on_a_cut() -> None:
    bounds = TrimBounds(1600, 10400, 12000, SR)
    assert edge_fades(bounds, 200, 1300) == (64, 64)
    assert edge_fades(bounds, None, 1300) == (0, 64)
    assert edge_fades(bounds, 200, None) == (64, 0)
    assert edge_fades(bounds, None, None) == (0, 0)


def test_no_fade_when_the_silence_trim_moved_the_edge_inside() -> None:
    bounds = TrimBounds(3680, 8640, 12000, SR)
    assert edge_fades(bounds, 200, 1300) == (0, 0)


def test_fades_never_exceed_the_kept_length() -> None:
    bounds = TrimBounds(1600, 1680, 20000, SR)  # 80 samples kept
    assert edge_fades(bounds, 200, 210) == (40, 40)


def test_apply_edge_fades_shape() -> None:
    original = np.ones(1000)
    faded = apply_edge_fades(original, 64, 64)
    assert faded is not original
    assert np.all(original == 1.0)
    assert faded[0] == 0.0 and faded[-1] == 0.0
    assert np.all(np.diff(faded[:65]) >= 0)
    assert np.all(np.diff(faded[-65:]) <= 0)
    assert np.all(faded[64:-64] == 1.0)


def test_apply_edge_fades_zero_is_a_copy_and_bad_input_raises() -> None:
    data = _tone(100)
    out = apply_edge_fades(data, 0, 0)
    assert np.array_equal(out, data) and out is not data
    with pytest.raises(ValueError):
        apply_edge_fades(np.ones(10), 6, 6)
    with pytest.raises(ValueError):
        apply_edge_fades(np.ones(10), -1, 0)


def test_apply_edge_fades_keeps_float32() -> None:
    assert apply_edge_fades(np.ones(100, dtype=np.float32), 10, 10).dtype == np.float32


# --- the processing spec and the key (rule 3) -------------------------------------


def _chain_spec() -> dict:
    return {"version": 1, "trim": trim_params(), "stages": [], "loudness": {"target": -16.0}}


def test_spec_without_a_cut_is_an_equal_copy() -> None:
    spec = _chain_spec()
    out = spec_with_manual_trim(spec, None, None)
    assert out == spec and out is not spec


def test_spec_with_a_cut_adds_the_entry_and_leaves_the_input_alone() -> None:
    spec = _chain_spec()
    out = spec_with_manual_trim(spec, 200, None)
    assert out["manual_trim"] == {"fade_ms": MANUAL_FADE_MS, "start_ms": 200}
    assert "manual_trim" not in spec
    json.dumps(out)  # plain data


def test_key_changes_with_the_cut_and_not_without_one() -> None:
    spec = _chain_spec()
    base = processed_key(raw_key="abc", stretch=1.0, spec=spec)
    same = processed_key(raw_key="abc", stretch=1.0, spec=spec_with_manual_trim(spec, None, None))
    assert base == same
    keys = {
        processed_key(raw_key="abc", stretch=1.0, spec=spec_with_manual_trim(spec, s, e))
        for s, e in [(200, None), (300, None), (None, 900), (200, 900)]
    }
    assert len(keys) == 4
    assert base not in keys


# --- sidecar ------------------------------------------------------------------------


def test_sidecar_round_trip_with_cuts() -> None:
    bounds = TrimBounds(1600, 10400, 12000, SR)
    data = json.loads(json.dumps(bounds_to_data(bounds, manual_start_ms=200, manual_end_ms=1300)))
    back = bounds_from_data(
        data, expect_total=12000, expect_manual_start_ms=200, expect_manual_end_ms=1300
    )
    assert back == bounds


def test_sidecar_for_other_cut_points_is_stale() -> None:
    bounds = TrimBounds(1600, 10400, 12000, SR)
    data = bounds_to_data(bounds, manual_start_ms=200, manual_end_ms=1300)
    assert bounds_from_data(data) is None  # expects no cut
    assert bounds_from_data(data, expect_manual_start_ms=200, expect_manual_end_ms=1301) is None
    assert bounds_from_data(data, expect_manual_start_ms=201, expect_manual_end_ms=1300) is None


def test_sidecar_written_before_m5_counts_as_no_cut() -> None:
    bounds = TrimBounds(3680, 8640, 12000, SR)
    data = bounds_to_data(bounds)
    del data["manual_start_ms"], data["manual_end_ms"]
    assert bounds_from_data(data, expect_total=12000) == bounds
    assert bounds_from_data(data, expect_manual_start_ms=200) is None


def test_sidecar_with_a_bool_cut_is_damaged() -> None:
    data = bounds_to_data(TrimBounds(0, 100, 100, SR))
    data["manual_start_ms"] = True
    assert bounds_from_data(data, expect_manual_start_ms=1) is None
    assert bounds_from_data(data) is None
