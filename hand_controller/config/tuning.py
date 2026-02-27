"""hand_controller/config/tuning.py

GOAL:
  Central place para sa mga "knobs" na pang-tune ng *feel* ng app.
  Para pag may gusto kang ayusin (mas mabilis mag-toggle, mas easy mag-type,
  less accidental triggers), dito ka lang mag-eedit.


HOW TO USE:
  1) Kung hirap mag-toggle mouse <-> keyboard
       -> adjust MODE_TOGGLE_* values.
  2) Kung hirap mag-type / masyadong strict ang pinch click
       -> adjust KEY_PINCH_* multipliers.

NOTE:
  Keep changes small (ex: +0.02 / -0.02) then test.
"""

###############################################################################
# MODE TOGGLE (mouse <-> keyboard)
###############################################################################
# Gesture-driven mode toggle = thumb + ring pinch HOLD.
#
# MODE_TOGGLE_HOLD_SECONDS:
#   Gaano katagal mo dapat i-hold yung toggle pinch bago mag-switch.
#   - Lower (0.20-0.25) = mas mabilis pero mas prone sa accidental toggle.
#   - Higher (0.35-0.50) = mas safe pero mas "matagal" mag-toggle.
MODE_TOGGLE_HOLD_SECONDS = 0.10

# MODE_TOGGLE_COOLDOWN_SECONDS:
#   After mag-toggle, ilang seconds bago payagan ulit mag-toggle.
#   Why: iwas spam kapag jittery ang kamay or nakahold pa.
MODE_TOGGLE_COOLDOWN_SECONDS = 0.80

# Safety: require palm facing while holding the toggle pinch.
#
# Why: para mabawasan ang accidental toggles (lalo na kung side view / back
# of hand ang nakikita ng camera).
MODE_TOGGLE_REQUIRE_PALM_FACING = True

# Safety: ignore low-confidence detections.
#
# For now (rule-based), confidence is usually 1.0.
# Later pag ML recognizer na, useful ito para hindi mag-toggle sa noisy frames.
MODE_TOGGLE_MIN_CONFIDENCE = 0.80


###############################################################################
# KEYBOARD PINCH "CLICK" FEEL (Hysteresis) 
###############################################################################
# Context:
#   We still have a base pinch threshold in app.py: PINCH_THRESHOLD (pixels).
#   - Mouse clicks use the *level* pinch check (dist < PINCH_THRESHOLD).
#   - Keyboard typing uses *edge* events (PINCH_*_DOWN) + hysteresis.
#
# Hysteresis idea (button-like feel):
#   press_th   = PINCH_THRESHOLD * KEY_PINCH_PRESS_MULTIPLIER
#   release_th = PINCH_THRESHOLD * KEY_PINCH_RELEASE_MULTIPLIER
#
#   - Press happens when dist <= press_th (one-shot "DOWN")
#   - Re-arm happens when dist >= release_th
#
# Why this helps:
#   Kung naka-close na yung fingers mo (short distance), dati mahirap mag-click
#   kasi wala nang OPEN->PINCHED transition. With hysteresis, konting "release"
#   lang then "press" ulit, register na.
#
# Tuning tips (Taglish):
#   - If hirap mag-type (masyadong strict):
#       increase KEY_PINCH_PRESS_MULTIPLIER slightly (ex: 0.85 -> 0.88)
#   - If nagdo-double type / spam dahil mabilis mag re-arm:
#       increase KEY_PINCH_RELEASE_MULTIPLIER (ex: 0.92 -> 0.95)
#     (meaning: kailangan mo lumayo nang konti bago ma-ready ulit)
#   - Keep RELEASE >= PRESS always (otherwise weird behavior).
KEY_PINCH_PRESS_MULTIPLIER = 0.50
KEY_PINCH_RELEASE_MULTIPLIER = 0.50
