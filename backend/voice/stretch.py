"""Pure maths for Tighten (M3-9): how long a stretched line plays, and how much
stretch clears an overflow. No I/O; the audio itself is rendered elsewhere.

``stretch`` is a speed-up factor: 1.08 plays 8 percent faster, so the line is
``duration / 1.08`` long. Pitch is kept (the renderer is a time-stretch).
"""

import math
from fractions import Fraction
from math import floor

STRETCH_AUTO_MAX = 1.08  # the one-click Tighten never goes past this (about 8 percent)
STRETCH_WARN = 1.15  # above this the UI warns that the voice may sound unnatural


def stretched_duration_ms(duration_ms: int, stretch: float) -> int:
    """Length in ms of ``duration_ms`` of audio played at ``stretch`` (round half up).

    Exact decimal math (``repr`` of the float) so results never depend on float noise.
    """
    if duration_ms < 0:
        raise ValueError("duration must not be negative")
    if not stretch > 0:
        raise ValueError("stretch must be positive")
    return floor(Fraction(duration_ms) / Fraction(repr(float(stretch))) + Fraction(1, 2))


def fit_stretch(raw_ms: int, playing_ms: int, overflow_ms: int) -> float | None:
    """The smallest stretch (3 decimals, rounded up) that removes the overflow.

    ``raw_ms`` is the take's real length, ``playing_ms`` how long it plays now
    (already stretched), ``overflow_ms`` how far it runs past the next line.
    Gives None when there is no overflow or no stretch could clear it. The result
    may exceed the allowed maximum; the caller decides what to do about that.
    """
    if overflow_ms <= 0 or raw_ms <= 0:
        return None
    target = playing_ms - overflow_ms
    if target <= 0:
        return None
    return math.ceil(Fraction(raw_ms, target) * 1000) / 1000


def stretched_name(stem: str, stretch: float) -> str:
    """File name of a stretched copy of the take file ``stem`` (``abc`` -> ``abc_x1083.wav``).

    The stretch is rounded to 3 decimals, as the command stores it, so the same
    stretch always gives the same name and an existing file is reused.
    """
    return f"{stem}_x{round(stretch * 1000)}.wav"
