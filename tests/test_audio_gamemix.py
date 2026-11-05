"""Game audio level limits (M4-3, S3c)."""

import math

import pytest

from backend.audio.gamemix import (
    GAME_AUDIO_MAX_DB,
    GAME_AUDIO_MIN_DB,
    clean_game_audio_db,
)


def test_a_valid_level_is_rounded_to_two_decimals() -> None:
    assert clean_game_audio_db(-6) == -6.0
    assert clean_game_audio_db(-6.004) == -6.0
    assert clean_game_audio_db(3.456) == 3.46


def test_the_limits_are_inclusive() -> None:
    assert clean_game_audio_db(GAME_AUDIO_MIN_DB) == GAME_AUDIO_MIN_DB
    assert clean_game_audio_db(GAME_AUDIO_MAX_DB) == GAME_AUDIO_MAX_DB


def test_negative_zero_is_zero() -> None:
    assert math.copysign(1.0, clean_game_audio_db(-0.0)) == 1.0


@pytest.mark.parametrize(
    "bad",
    [
        GAME_AUDIO_MIN_DB - 0.1,
        GAME_AUDIO_MAX_DB + 0.1,
        math.nan,
        math.inf,
        "3",
        None,
        True,
    ],
)
def test_bad_levels_are_refused(bad: object) -> None:
    with pytest.raises(ValueError, match="game audio level"):
        clean_game_audio_db(bad)
