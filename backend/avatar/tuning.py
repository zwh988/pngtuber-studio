"""Every tunable number of the avatar (M5-2 to M5-4) in one place.

All are starting guesses to tune by eye (task file, "Risks"). Changing one changes
what the solver draws but never the project data. The envelope settings also name
the cached envelope files, so changing them makes fresh ones.
"""

# --- loudness envelope (M5-2) ------------------------------------------------------
ENVELOPE_HOP_MS = 10  # one value every 10 ms (about 100 Hz)
ENVELOPE_WINDOW_MS = 20  # RMS over 20 ms centred on each hop
ENVELOPE_FLOOR_DB = -100.0  # silence
ENVELOPE_VERSION = 1

# --- mouth (M5-3) --------------------------------------------------------------------
# Processed takes are loudness-normalised, so absolute thresholds work.
MOUTH_OPEN_DB = -32.0  # opens at or above this
MOUTH_CLOSE_DB = -38.0  # closes below this (the gap is the hysteresis)
MOUTH_MIN_HOLD_MS = 70  # a mouth state lasts at least this long

# --- blink (M5-3) --------------------------------------------------------------------
BLINK_CLOSED_MS = 120
BLINK_GAP_MIN_MS = 2000  # gap between blinks at blink rate 1.0
BLINK_GAP_MAX_MS = 6000
BLINK_IDLE_STEP_MS = 500  # how far to look ahead while the blink rate is 0

# --- bounce (M5-4): a spring pushed by the voice level --------------------------------
BOUNCE_HEIGHT = 0.03  # fraction of the frame height at full level and bounce 1.0
BOUNCE_LEVEL_FLOOR_DB = -50.0  # level 0 at or below this
BOUNCE_LEVEL_CEIL_DB = -15.0  # level 1 at or above this
BOUNCE_STIFFNESS = 400.0  # spring constant (1/s^2)
BOUNCE_DAMPING = 18.0  # damping (1/s)

# --- idle float (M5-4) -----------------------------------------------------------------
FLOAT_HEIGHT = 0.01  # fraction of the frame height at float_amp 1.0
FLOAT_BASE_HZ = 0.25  # cycles per second at float_speed 1.0
FRAME_ASPECT = 16 / 9  # width / height of the output frame (sideways float in pixels)

# --- reactions (M5-4) -------------------------------------------------------------------
SHAKE_X = 0.012  # fraction of the frame width at intensity 1
SHAKE_DEG = 4.0
SHAKE_HZ = 9.0
HOP_HEIGHT = 0.06  # fraction of the frame height
POP_OVERSHOOT = 1.70158  # "back" easing constant
SQUISH_AMOUNT = 0.18  # squash at intensity 1 (x grows, y shrinks)

# --- frame track for the preview (S10a uses it) ------------------------------------
SOLVER_STEP_MS = ENVELOPE_HOP_MS  # resolution of the precomputed tracks
