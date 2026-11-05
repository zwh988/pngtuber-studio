"""Game audio level (M4-3): the one fixed dB level for the footage's own sound. Pure.

The level is stored in ``Project.game_audio_db`` and set through ``SetGameAudioDb``.
The slider in the editor spans about -30 to +6 dB; the limits here are wider on
purpose, so changing the slider range never needs a data change.
"""

import math
from typing import Any

GAME_AUDIO_MIN_DB = -60.0
GAME_AUDIO_MAX_DB = 12.0


def clean_game_audio_db(value: Any) -> float:
    """A valid level, rounded to 2 decimals. Raises ``ValueError`` otherwise."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("the game audio level must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("the game audio level must be a finite number")
    if not GAME_AUDIO_MIN_DB <= number <= GAME_AUDIO_MAX_DB:
        raise ValueError(
            f"the game audio level must be between {GAME_AUDIO_MIN_DB} "
            f"and {GAME_AUDIO_MAX_DB} dB"
        )
    # ``+ 0.0`` turns -0.0 into 0.0, so both spellings are the same level.
    return round(number, 2) + 0.0
