"""Pure Tighten maths (M3-9, S8c)."""

import pytest

from backend.voice.stretch import fit_stretch, stretched_duration_ms, stretched_name


def test_no_stretch_keeps_the_length() -> None:
    assert stretched_duration_ms(2000, 1.0) == 2000


def test_stretch_shortens_and_rounds_half_up() -> None:
    assert stretched_duration_ms(2000, 1.25) == 1600
    assert stretched_duration_ms(3, 2.0) == 2  # 1.5 rounds up
    assert stretched_duration_ms(1000, 1.08) == 926  # 925.93


def test_bad_input_is_refused() -> None:
    with pytest.raises(ValueError):
        stretched_duration_ms(-1, 1.0)
    with pytest.raises(ValueError):
        stretched_duration_ms(1000, 0)
    with pytest.raises(ValueError):
        stretched_duration_ms(1000, float("nan"))


def test_fit_stretch_removes_the_overflow() -> None:
    raw, overflow = 2000, 150
    stretch = fit_stretch(raw, raw, overflow)
    assert stretch is not None
    assert stretched_duration_ms(raw, stretch) <= raw - overflow


def test_fit_stretch_rounds_up_to_three_decimals() -> None:
    assert fit_stretch(1000, 1000, 70) == 1.076  # 1000 / 930 = 1.0752...


def test_fit_stretch_from_an_already_stretched_line() -> None:
    # raw 2000, plays 1852 at 1.08; still 100 over, so it must reach 1900 / ... less
    stretch = fit_stretch(2000, 1852, 100)
    assert stretch is not None and stretch > 1.08
    assert stretched_duration_ms(2000, stretch) <= 1752


def test_no_fit_when_nothing_overflows_or_nothing_can_help() -> None:
    assert fit_stretch(1000, 1000, 0) is None
    assert fit_stretch(1000, 1000, 1000) is None
    assert fit_stretch(0, 0, 10) is None


def test_stretched_name_is_stable_and_rounded() -> None:
    assert stretched_name("abc", 1.083) == "abc_x1083.wav"
    assert stretched_name("abc", 1.25) == "abc_x1250.wav"
    assert stretched_name("abc", 1.0830000001) == "abc_x1083.wav"
