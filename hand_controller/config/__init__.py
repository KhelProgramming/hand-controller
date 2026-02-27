"""hand_controller/config (Hybrid Taglish)

Purpose:
  Dito natin nilalagay ang mga tunable constants ("feel knobs") ng app.
  Para kapag may gustong i-adjust na behavior/UX, hindi na kailangan maghanap
  sa maraming files.

How to use:
  - Usually, edit `tuning.py`.
  - Controllers/gestures import these constants to keep logic clean.
"""

from .tuning import (  # noqa: F401
    MODE_TOGGLE_HOLD_SECONDS,
    MODE_TOGGLE_COOLDOWN_SECONDS,
    MODE_TOGGLE_REQUIRE_PALM_FACING,
    MODE_TOGGLE_MIN_CONFIDENCE,
    KEY_PINCH_PRESS_MULTIPLIER,
    KEY_PINCH_RELEASE_MULTIPLIER,
)
