"""Gesture recognition interfaces (Core file, Very Detailed Taglish).

Goal (bakit may "gestures" layer tayo):
    Gusto natin ihiwalay ang "pag-intindi" ng kamay (gestures) sa "pag-action"
    (mouse move/click at keyboard press).

    In short (pipeline):
        Vision/Tracker -> raw landmarks
        Gestures       -> meaning / events
        Controllers    -> decisions (what should happen)
        Executor       -> pyautogui side effects (move/click/type)

Why important:
    - Mas madali magpalit ng algorithm.
      Today: rule-based.
      Later: ML model ng groupmates mo.
      Basta pareho silang naglalabas ng GestureResult list, plug-and-play.

    - Mas madali mag-debug.
      Kapag "di nagta-type", check mo muna kung lumalabas yung gesture event.
      Kapag lumalabas naman, controller issue na.

Key Terms:
    1) Level gesture
        "Naka-pinch ba ngayon?" (True habang close ang fingers)
        Example: PINCH_THUMB_INDEX

    2) Event gesture
        "Kailan nag-click?" (True only sa exact moment ng press)
        Example: PINCH_THUMB_INDEX_DOWN

    Bakit kailangan ng event gestures?
        Kung level gesture lang, may risk na paulit-ulit mag-trigger bawat frame.
        Sa keyboard, ayaw natin na mag-type ng 30 letters dahil naka-hold yung pinch.

Notes about coordinates:
    Gesture distance computations usually happen in *frame pixels*.
    Example: thumb-index distance in the camera frame (FRAME_WIDTH x FRAME_HEIGHT).
    Later, pwede natin i-normalize by hand size if kailangan (optional).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


# ------------------------------------------------------------
# Gesture Names (string constants)
# ------------------------------------------------------------
# WHY strings?
#   - Pinaka simple for integration (lalo na pag ML output na).
#   - Madali i-log / i-print / i-debug.
#
# NOTE:
#   - Some are "level" gestures (continuous state)
#   - Some are "event" gestures (one-shot click-like)
GESTURE_PALM_FACING = "PALM_FACING"              # palm facing camera (used for safety + movement gating)
GESTURE_HAND_OPEN = "HAND_OPEN"                  # open hand (used for mouse movement gating)

# Mouse & Keyboard "pinch" states
GESTURE_PINCH_INDEX = "PINCH_THUMB_INDEX"        # level: thumb-index pinch (mouse left click level)
GESTURE_PINCH_MIDDLE = "PINCH_THUMB_MIDDLE"      # level: thumb-middle pinch (mouse right click level)
GESTURE_PINCH_RING = "PINCH_THUMB_RING"          # level: thumb-ring pinch (mode toggle hold)

# Keyboard "click" events (one-shot)
GESTURE_PINCH_INDEX_DOWN = "PINCH_THUMB_INDEX_DOWN"       # event: keypress trigger (pinch-to-type)
GESTURE_PINCH_MIDDLE_DOWN = "PINCH_THUMB_MIDDLE_DOWN"     # event: backspace trigger
GESTURE_PINCH_PINKY_DOWN = "PINCH_THUMB_PINKY_DOWN"       # event: shift one-shot trigger


@dataclass(slots=True)
class GestureResult:
    """A single detected gesture.

    Fields (Taglish explanation):
        name:
            Ano yung gesture (use the constants above).

        confidence:
            0..1 score. Rule-based usually 1.0.
            ML recognizers can output real probabilities.

        hand_label:
            "Left" or "Right". Useful kapag per-hand events (like typing with both hands).

        data:
            Optional extra info (ex: distances, thresholds used, debug metadata).
            Hindi required, pero helpful pag nagde-debug.
    """

    name: str
    confidence: float
    hand_label: Optional[str] = None  # "Left" / "Right" / None
    data: Dict[str, Any] = field(default_factory=dict)  # optional extra info


class GestureRecognizer(Protocol):
    """Interface for gesture recognizers (rule-based or ML).

    Contract (important):
        Implementations should not perform side effects.
        Meaning: bawal mag-pyautogui dito.

        Job lang nila is: 
            landmarks -> GestureResult list

    Why Protocol?
        Para kahit anong class (rule-based or ML), basta may recognize(...)
        method na tama ang signature, pwede na siyang ipasok.
    """

    def recognize(
        self,
        *,
        hands_list,
        frame_w: int,
        frame_h: int,
        pinch_threshold: float,
    ) -> List[GestureResult]:
        """Return a list of detected gestures for the current frame."""

        raise NotImplementedError
