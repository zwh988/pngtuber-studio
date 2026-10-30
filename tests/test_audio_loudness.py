"""Loudness maths (M4-1): gain planning, levels, short-take rule. No audio libraries."""

import math

import numpy as np
import pytest

from backend.audio import loudness
from backend.audio.loudness import (
    MAX_BOOST_DB,
    MAX_CUT_DB,
    db_to_linear,
    is_short,
    loudness_params,
    peak_dbfs,
    plan_gain,
    predicted_peak_db,
    rms_dbfs,
)


def test_gain_moves_the_level_to_the_target() -> None:
    plan = plan_gain(-20.0, -16.0, basis="lufs")
    assert plan.gain_db == pytest.approx(4.0)
    assert not plan.clamped and not plan.silent
    assert plan.measured_db == -20.0
    assert plan_gain(-10.0, -16.0, basis="lufs").gain_db == pytest.approx(-6.0)


def test_boost_and_cut_are_limited() -> None:
    boost = plan_gain(-60.0, -16.0, basis="lufs")
    assert boost.gain_db == MAX_BOOST_DB
    assert boost.clamped
    cut = plan_gain(20.0, -16.0, basis="lufs")
    assert cut.gain_db == -MAX_CUT_DB
    assert cut.clamped


def test_exactly_at_the_limit_is_not_flagged() -> None:
    plan = plan_gain(-16.0 - MAX_BOOST_DB, -16.0, basis="lufs")
    assert plan.gain_db == MAX_BOOST_DB
    assert not plan.clamped


@pytest.mark.parametrize("measured", [-math.inf, math.nan, math.inf, None, "loud", True])
def test_silence_or_junk_gives_no_gain(measured: object) -> None:
    plan = plan_gain(measured, -16.0, basis="lufs")
    assert plan.gain_db == 0.0
    assert plan.silent
    assert plan.measured_db is None


def test_rms_basis_uses_the_offset() -> None:
    plan = plan_gain(-22.0, -16.0, basis="rms")
    assert plan.basis == "rms"
    assert plan.gain_db == pytest.approx(6.0 - loudness.RMS_TO_LUFS_OFFSET_DB)


def test_bad_arguments() -> None:
    with pytest.raises(ValueError):
        plan_gain(-20.0, -16.0, basis="peak")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        plan_gain(-20.0, math.nan, basis="lufs")


def test_short_take_rule_is_400_ms() -> None:
    assert is_short(9599, 24000)
    assert not is_short(9600, 24000)
    assert not is_short(48000, 24000)
    assert is_short(0, 24000)
    with pytest.raises(ValueError):
        is_short(10, 0)


def test_levels() -> None:
    half = np.full(1000, 0.5, dtype=np.float32)
    assert peak_dbfs(half) == pytest.approx(-6.0206, abs=1e-3)
    assert rms_dbfs(half) == pytest.approx(-6.0206, abs=1e-3)
    t = np.arange(24000) / 24000
    sine = 0.1 * np.sin(2 * np.pi * 440 * t)
    assert peak_dbfs(sine) == pytest.approx(-20.0, abs=0.01)
    assert rms_dbfs(sine) == pytest.approx(-23.01, abs=0.02)


def test_levels_of_silence() -> None:
    assert peak_dbfs(np.zeros(100)) == -math.inf
    assert rms_dbfs(np.zeros(100)) == -math.inf
    assert peak_dbfs(np.zeros(0)) == -math.inf
    assert rms_dbfs(np.zeros(0)) == -math.inf


def test_db_to_linear_and_predicted_peak() -> None:
    assert db_to_linear(0.0) == 1.0
    assert db_to_linear(6.0206) == pytest.approx(2.0, abs=1e-3)
    assert predicted_peak_db(-6.0, 4.0) == pytest.approx(-2.0)
    assert predicted_peak_db(-math.inf, 4.0) == -math.inf


def test_params_include_the_target_and_all_constants() -> None:
    params = loudness_params(-14.0)
    assert params["target_lufs"] == -14.0
    assert set(params) == {
        "target_lufs",
        "ceiling_db",
        "short_take_ms",
        "max_boost_db",
        "max_cut_db",
        "rms_offset_db",
    }
