"""hand_controller.controllers.keyboard_controller

PURPOSE:

    Kapag mode == "keyboard":
      - Hindi ginagalaw ang mouse cursor.
      - Pinapakita natin ang virtual keyboard sa overlay.
      - Ang "pointer" (cursor within keyboard) ay fingertip position.
      - Ang "click" ay pinch gesture (thumb + index) para pumindot ng key.

IMPORTANT CONCEPTS:
    1) Pointer per hand
        - Each hand has its own pointer = index fingertip (landmark 8).
        - This supports 1-hand or 2-hand typing.

    2) Hover vs Press
        - Hover = kung anong key ang nasa ilalim ng pointer.
        - Press = occurs only when we receive pinch DOWN event.

    3) Gesture events are produced by the recognizer
        - We do NOT compute pinch distances here.
        - We simply consume events like:
            * GESTURE_PINCH_INDEX_DOWN
            * GESTURE_PINCH_MIDDLE_DOWN
            * GESTURE_PINCH_PINKY_DOWN

USED BY:
    - app.py (cv_loop) calls update_keyboard_mode(...) kapag mode == "keyboard"

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple, Union

from ..core.coords import frame_to_screen_xy
from ..gestures.base import (
    GESTURE_PINCH_INDEX_DOWN,
    GESTURE_PINCH_MIDDLE_DOWN,
    GESTURE_PINCH_PINKY_DOWN,
)
from .actions import Action, Hotkey, KeyPress


@dataclass(slots=True)
class KeyboardSettings:
    """Keyboard settings.

    Fields:
        key_tap_sensitivity / key_tap_cooldown:
            legacy (from old flex-tap) – not used in pinch-to-type.

        thumb_space_only / finger_tap_thresholds:
            also legacy for flex-tap.

    Practical tip:
        If later gusto mo i-clean completely, pwede natin gawing separate
        settings class for pinch keyboard.
    """

    key_tap_sensitivity: float
    key_tap_cooldown: float
    thumb_space_only: bool
    finger_tap_thresholds: Dict[str, float]


@dataclass(slots=True)
class KeyboardState:
    """Runtime state for keyboard controller.

    K4 feature:
        shift_one_shot:
            When True, the next keypress will be sent with Shift.
            After one keypress, auto reset to False.

    Why state exists here:
        Keyboard behavior can be stateful:
          - shift toggles
          - maybe future: caps lock, auto-repeat, prediction, etc.

    _reserved:
        Placeholder container para madaling mag-add later without refactoring.
    """

    shift_one_shot: bool = False
    _reserved: Dict[str, float] = field(default_factory=dict)

    def reset_prev_rel_only(self) -> None:
        """Compatibility no-op.

        Historically used by flex-tap logic (rel_y tracking). Not used now.
        """

        return


# =========================
# Layout helpers
# =========================

def create_keyboard_layout_screen(
    screen_w: int,
    screen_h: int,
    *,
    height_ratio: float,
    side_margin: int,
) -> List[dict]:
    """Create a simple QWERTY keyboard layout in screen coordinates.

    Goal:
        Gumawa ng listahan ng keys na may rectangles on the screen.
        This layout is only for drawing + hit-testing.

    Returns:
        List of dicts, each item:
            {
              "label": "Q" / "A" / ... / "SPACE",
              "x1","y1","x2","y2": screen pixel rectangle
            }

    Why screen coords:
        Yung pointer natin (index fingertip) is also mapped to screen coords.
        So match na match yung math for hover detection.
    """

    keys: List[dict] = []

    rows = [
        "QWERTYUIOP",
        "ASDFGHJKL",
        "ZXCVBNM",
        "SPACE",
    ]

    # Keyboard area is bottom portion of screen
    kb_height = int(screen_h * height_ratio)
    kb_top = screen_h - kb_height - 20
    kb_left = side_margin
    kb_right = screen_w - side_margin
    kb_width = kb_right - kb_left

    # Compute uniform key sizes (with centering per row)
    max_cols = max(len(row) if row != "SPACE" else 5 for row in rows)
    key_w = kb_width / max_cols
    key_h = kb_height / len(rows)

    for row_index, row in enumerate(rows):
        y1 = int(kb_top + row_index * key_h)
        y2 = int(y1 + key_h - 6)  # small gap for nicer visuals

        if row == "SPACE":
            # Make space bar wider by using slots
            label = "SPACE"
            num_slots = 5
            total_row_width = num_slots * key_w
            row_left = int(kb_left + (kb_width - total_row_width) / 2)
            x1 = row_left
            x2 = int(row_left + total_row_width - 6)
            keys.append({
                "label": label,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            })
        else:
            num_keys = len(row)
            total_row_width = num_keys * key_w
            row_left = int(kb_left + (kb_width - total_row_width) / 2)

            for i, ch in enumerate(row):
                x1 = int(row_left + i * key_w)
                x2 = int(x1 + key_w - 6)
                keys.append({
                    "label": ch,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                })

    return keys


def get_key_at_point(keys: Sequence[dict], x: int, y: int) -> Optional[dict]:
    # Find which key rectangle is under the (x, y) screen point.



    for key in keys:
        if key["x1"] <= x <= key["x2"] and key["y1"] <= y <= key["y2"]:
            return key
    return None


# =========================
# Small utilities
# =========================

def _label_to_keypress(label: str) -> str:
    """Convert on-screen label to pyautogui-compatible key name."""

    if label == "SPACE":
        return "space"
    return label.lower()


def _is_alpha_key(key: str) -> bool:
    """True if key is a single letter a-z (used for Shift logic)."""

    return len(key) == 1 and key.isalpha()


def _hands_with_gesture(gesture_results, gesture_name: str) -> Set[str]:
    """Return set of hand labels that produced a specific gesture event."""

    return {
        g.hand_label
        for g in (gesture_results or [])
        if getattr(g, "name", None) == gesture_name and getattr(g, "hand_label", None)
    }


# =========================
# Main keyboard controller
# =========================

def update_keyboard_mode(
    *,
    keys: Sequence[dict],
    hands_list,
    screen_w: int,
    screen_h: int,
    settings: KeyboardSettings,
    state: KeyboardState,
    now: float,
    gesture_results=None,
) -> Tuple[List[Action], Set[str], List[Union[Tuple[int, int], dict]], Dict[str, Optional[str]]]:
    """Compute keyboard-mode Actions + overlay info.

    Inputs (important):
        keys:
            keyboard layout rectangles (screen coords)

        hands_list:
            tracker output list of hands

        gesture_results:
            list of GestureResult events from recognizer
            (ex: PINCH_INDEX_DOWN means "press" now)

    Returns:
        actions:
            list of Actions to execute (KeyPress / Hotkey)

        highlight_labels:
            set of key labels currently hovered (for overlay highlight)

        finger_points:
            list of pointer points for overlay. In K3 we use dicts:
                {"x":..., "y":..., "hand_label": "Left"/"Right"}

        hovered_key_by_hand:
            mapping for UI hint:
                {"Left": "A" or None, "Right": "K" or None}

    CORE IDEA:
        For each hand:
          1) Pointer = index fingertip (landmark 8)
          2) Determine hovered key under pointer
          3) If that hand has PINCH_INDEX_DOWN event this frame => press hovered key

        PLUS speed boosts:
          - thumb+middle pinch DOWN => Backspace
          - thumb+pinky pinch DOWN => arm one-shot Shift

    NOTE ABOUT settings/now:
        They are reserved for later (like repeat rate / prediction).
        We keep them in signature so controllers stay stable.
    """

    # Not used now, but kept for future upgrades.
    _ = (settings, now)

    actions: List[Action] = []
    highlight_labels: Set[str] = set()

    # finger_points items are dicts (x,y,hand_label) so overlay can draw L/R markers.
    finger_points: List[Union[Tuple[int, int], dict]] = []

    # Track hovered keys per hand for overlay status text.
    hovered_key_by_hand: Dict[str, Optional[str]] = {"Left": None, "Right": None}

    # Step 1: Read gesture events for this frame
    # We convert gesture_results -> set of hands that fired each event.
    pinch_down_hands = _hands_with_gesture(gesture_results, GESTURE_PINCH_INDEX_DOWN)
    middle_down_hands = _hands_with_gesture(gesture_results, GESTURE_PINCH_MIDDLE_DOWN)
    pinky_down_hands = _hands_with_gesture(gesture_results, GESTURE_PINCH_PINKY_DOWN)

    # Step 2: Apply "global" keyboard gestures (not tied to hovered key)
    # K4 Shift: thumb+pinky arms one-shot shift.
    if pinky_down_hands:
        state.shift_one_shot = True

    # K4 Backspace: thumb+middle does immediate backspace (no hover needed).
    # If both hands do it, we'll allow multiple backspaces (one per edge event).
    for _hand in middle_down_hands:
        actions.append(KeyPress("backspace"))

    # Step 3: For each hand, compute pointer + hovered key
    for h in hands_list or []:
        hand_label = h.get("label")
        lm = h.get("landmarks")
        if lm is None or not hand_label:
            continue

        # Pointer = index fingertip
        # We convert normalized landmark coords -> screen pixels.
        tip_lm = lm.landmark[8]
        tip_x, tip_y = frame_to_screen_xy(tip_lm.x, tip_lm.y, screen_w, screen_h)

        # Save pointer for overlay drawing
        finger_points.append({"x": tip_x, "y": tip_y, "hand_label": hand_label})

        # Hover detection: what key is under pointer?
        key = get_key_at_point(keys, tip_x, tip_y)
        if key is None:
            continue

        label = key["label"]
        highlight_labels.add(label)
        hovered_key_by_hand[hand_label] = label

        # Step 4: Press logic (pinch-to-type)
        # Only press when we receive pinch DOWN edge event.
        # Thanks to K6 hysteresis, you don't need to open fingers wide to re-arm.
        if hand_label in pinch_down_hands:
            key_name = _label_to_keypress(label)

            # Apply one-shot Shift if armed
            if state.shift_one_shot:
                if _is_alpha_key(key_name):
                    # For letters: send Shift+letter
                    actions.append(Hotkey(("shift", key_name)))
                else:
                    # For non-letters: just press it as is
                    actions.append(KeyPress(key_name))
                state.shift_one_shot = False
            else:
                actions.append(KeyPress(key_name))

    return actions, highlight_labels, finger_points, hovered_key_by_hand
