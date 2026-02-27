"""hand_controller.controllers.mouse_controller

PURPOSE (Very Detailed Taglish):
    Mouse-mode controller = ito yung utak ng "hand as mouse".

    Sa mouse mode, goals natin:
      1) Cursor movement (parang trackpad / relative movement)
      2) Mouse clicks (pinch gestures)
      3) Human-friendly feel (smoothing + deadzone + sensitivity)

IMPORTANT SEPARATION:
    - DITO: logic only (nagde-decide kung anong gagawin)
    - HINDI DITO: actual OS actions

    Meaning: ang output ng functions dito ay list of Action objects.
    Si action_executor.py ang tumatawag ng pyautogui.

WHY DELTA-BASED MOVEMENT (trackpad style) and NOT absolute mapping:
    Absolute mapping = "kung nasaan kamay mo sa camera, doon cursor".
    Kadalasan jittery + nakakapagod.

    Delta-based = "gaano kalayo gumalaw ang wrist mula last frame".
    Parang trackpad:
      - small movements = small cursor movements
      - you can "clutch" (stop movement) kapag sarado ang hand

CLUTCH BEHAVIOR (existing design):
    - palm facing + open hand => movement active
    - palm facing + closed hand => movement disabled (clutch) BUT clicks still allowed
    - back of hand => disable for safety

GESTURE SOURCE:
    Palm / open / pinch detection comes from gestures layer
    (gestures/rule_based.py for now, ML later).

USED BY:
    - app.py (cv_loop) calls update_mouse_mode(...) kapag mode == "mouse"

"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import List, Optional, Tuple

from ..core.coords import get_landmark_pixel
from ..gestures.base import (
    GestureRecognizer,
    GESTURE_HAND_OPEN,
    GESTURE_PALM_FACING,
    GESTURE_PINCH_INDEX,
    GESTURE_PINCH_MIDDLE,
)
from .actions import Action, MoveTo, Click, DoubleClick


@dataclass(slots=True)
class MouseSettings:
    """User-tunable settings for mouse feel.

    sensitivity:
        Mas mataas = mas mabilis cursor movement per wrist delta.

    smoothing:
        0..1. Higher = smoother but more "delay".

    deadzone:
        Small movement threshold (pixels in screen space) na i-ignore.
        Helps reduce micro jitter.

    click_cooldown:
        Minimum seconds between clicks (anti-spam).

    double_click_interval:
        If two left clicks happen within this time window => double click.

    pinch_threshold:
        Distance threshold (in camera/frame pixels) used by gesture recognizer
        to decide if a pinch is happening.
    """

    sensitivity: float
    smoothing: float
    deadzone: int
    click_cooldown: float
    double_click_interval: float
    pinch_threshold: float


@dataclass(slots=True)
class MouseState:
    """Runtime memory for mouse controller.

    WHY we need state:
        Mouse control is not "stateless" per frame.
        We need to remember:
          - previous cursor position (screen coords)
          - previous wrist position (frame coords) to compute dx/dy
          - last click times (cooldown + double click)

    Fields:
        prev_x, prev_y:
            Last cursor position on the screen.

        hand_tracked + prev_hand_x/y:
            Used for delta-based motion.
            First time we see movement_active, we "initialize" the tracker
            without moving cursor abruptly.

        last_*:
            Used for click cooldown and double click detection.
    """

    # cursor position (screen)
    prev_x: int
    prev_y: int

    # tracking wrist delta (frame/camera)
    hand_tracked: bool = False
    prev_hand_x: Optional[int] = None
    prev_hand_y: Optional[int] = None

    # click cooldown timers
    last_left_click: float = 0.0
    last_right_click: float = 0.0
    last_click_time: float = 0.0


def smooth_movement(
    new_x: int,
    new_y: int,
    prev_x: int,
    prev_y: int,
    *,
    smoothing: float,
    deadzone: int,
) -> Tuple[int, int]:
    """Apply smoothing + deadzone (same math as original one-file app).

    Very simple explanation:
      - Compute dx, dy from previous point.
      - If distance is too small (< deadzone), ignore it to reduce jitter.
      - Otherwise, move partially toward target depending on smoothing.

    Note:
      smoothing is like "how much we keep the old value".
        - smoothing = 0.0 => immediate movement (no smoothing)
        - smoothing = 0.8 => very smooth but delayed
    """

    dx = new_x - prev_x
    dy = new_y - prev_y
    dist = math.hypot(dx, dy)

    # Step 1: deadzone to reduce micro-movement jitter
    if dist < deadzone:
        return prev_x, prev_y

    # Step 2: smoothing
    factor = smoothing
    smooth_x = int(prev_x + dx * (1 - factor))
    smooth_y = int(prev_y + dy * (1 - factor))
    return smooth_x, smooth_y


def get_mouse_hand(hands_list):
    """Pick which hand controls the mouse.

    Strategy:
      - Prefer Right hand (common dominant hand)
      - Otherwise pick the first detected hand

    Note:
      hands_list item format comes from tracker.extract_hands():
        {"label": "Left"/"Right", "landmarks": ...}
    """

    if not hands_list:
        return None
    for h in hands_list:
        if h.get("label") == "Right":
            return h
    return hands_list[0]


def _gesture_names_for_hand(gesture_results, hand_label: str) -> set:
    """Helper: filter gesture results for one hand and return a set of names."""

    return {g.name for g in (gesture_results or []) if g.hand_label == hand_label}


def _click_actions_from_pinch_flags(
    *,
    pinch_index: bool,
    pinch_middle: bool,
    settings: MouseSettings,
    state: MouseState,
    now: float,
) -> List[Action]:
    """Convert pinch booleans into click actions (with cooldown logic).

    Pinch mapping (mouse mode):
      - thumb+index pinch => left click / double click
      - thumb+middle pinch => right click

    WHY cooldown:
      Without cooldown, every frame while pinched would spam clicks.

    WHY double click logic:
      If two left pinches happen close enough (double_click_interval),
      we emit DoubleClick instead of two separate Clicks.
    """

    actions: List[Action] = []

    # --- left / double click ---
    if pinch_index and (now - state.last_left_click) > settings.click_cooldown:
        if (now - state.last_click_time) < settings.double_click_interval:
            actions.append(DoubleClick())
        else:
            actions.append(Click(button="left"))
        state.last_left_click = now
        state.last_click_time = now

    # --- right click ---
    if pinch_middle and (now - state.last_right_click) > settings.click_cooldown:
        actions.append(Click(button="right"))
        state.last_right_click = now

    return actions


def update_mouse_mode(
    *,
    hands_list,
    frame_w: int,
    frame_h: int,
    screen_w: int,
    screen_h: int,
    settings: MouseSettings,
    state: MouseState,
    now: float,
    recognizer: GestureRecognizer,
) -> Tuple[List[Action], str]:
    """Compute mouse-mode Actions and status text (for overlay).

    Inputs:
      hands_list:
        list of hands from tracker (each has label + landmarks)

      frame_w/frame_h:
        camera frame resolution (used when converting landmarks to pixels)

      screen_w/screen_h:
        actual screen size (used for clamping cursor)

      settings/state:
        user config + runtime memory

      recognizer:
        gesture recognizer (rule-based for now)

    Returns:
      (actions, mouse_status)

    High-level flow:
      1) If no hands -> disable + reset tracking
      2) Pick mouse hand (prefer Right)
      3) Use recognizer to compute gestures (palm/open/pinch)
      4) Decide movement_active + click_active
      5) If movement_active -> delta-based movement via wrist landmark
      6) If click_active -> pinch click actions
    """

    actions: List[Action] = []

    # --- Step 1: No hands -> no control ---
    if not hands_list:
        state.hand_tracked = False
        return actions, "mouse disabled: walang kamay sa camera"

    # --- Step 2: Pick which hand controls the cursor ---
    mouse_hand = get_mouse_hand(hands_list)
    if mouse_hand is None:
        state.hand_tracked = False
        return actions, "mouse disabled: walang ma-detect na tamang kamay"

    h_label = mouse_hand["label"]
    h_lm = mouse_hand["landmarks"]

    # --- Step 3: Ask recognizer for gestures ---
    # IMPORTANT:
    #   We call recognizer with the whole hands_list because some recognizers
    #   may need multi-hand context later.
    gesture_results = recognizer.recognize(
        hands_list=hands_list,
        frame_w=frame_w,
        frame_h=frame_h,
        pinch_threshold=settings.pinch_threshold,
    )

    # Filter gestures for the controlling hand
    gset = _gesture_names_for_hand(gesture_results, h_label)

    palm_ok = GESTURE_PALM_FACING in gset
    open_ok = GESTURE_HAND_OPEN in gset
    pinch_index = GESTURE_PINCH_INDEX in gset
    pinch_middle = GESTURE_PINCH_MIDDLE in gset

    # --- Step 4: Decide movement/click permissions ---
    # movement_active:
    #   - need palm facing (safety)
    #   - need open hand (so fist can act as "clutch")
    movement_active = palm_ok and open_ok

    # click_active:
    #   - allow clicking as long as palm facing
    #   - even if hand closed (so you can clutch movement but still click)
    click_active = palm_ok

    mouse_status = ""

    # --- Step 5: Movement logic (delta-based) ---
    if movement_active:
        # Wrist landmark index = 0
        # We read wrist position in *frame pixels* (camera space), not screen.
        wrist_x, wrist_y = get_landmark_pixel(h_lm, frame_w, frame_h, 0)

        if not state.hand_tracked:
            # First frame of tracking:
            # We store baseline wrist position but do not move cursor yet.
            state.prev_hand_x = wrist_x
            state.prev_hand_y = wrist_y
            state.hand_tracked = True
            mouse_status = "mouse ready: igalaw ang kamay para gumalaw ang cursor"
        else:
            # Compute delta from previous wrist position
            dx = wrist_x - (state.prev_hand_x or wrist_x)
            dy = wrist_y - (state.prev_hand_y or wrist_y)
            state.prev_hand_x = wrist_x
            state.prev_hand_y = wrist_y

            # Convert wrist delta -> cursor delta using sensitivity
            raw_x = int(state.prev_x + dx * settings.sensitivity)
            raw_y = int(state.prev_y + dy * settings.sensitivity)

            # Clamp to screen boundaries
            raw_x = max(0, min(screen_w - 1, raw_x))
            raw_y = max(0, min(screen_h - 1, raw_y))

            # Smooth movement to reduce jitter
            smooth_x, smooth_y = smooth_movement(
                raw_x,
                raw_y,
                state.prev_x,
                state.prev_y,
                smoothing=settings.smoothing,
                deadzone=settings.deadzone,
            )

            actions.append(MoveTo(smooth_x, smooth_y))
            state.prev_x, state.prev_y = smooth_x, smooth_y
            mouse_status = "mouse active"
    else:
        # Not movement active => treat as clutch or disabled.
        # Reset wrist tracking so next time it becomes active, no sudden jump.
        state.hand_tracked = False

        if not palm_ok:
            mouse_status = "mouse disabled: nakatalikod ang kamay (iharap ang palad sa camera)"
        elif not open_ok:
            mouse_status = "mouse movement disabled: sarado ang kamay (pwede pa ring mag-click gamit pinch)"
        else:
            mouse_status = "mouse disabled: hindi pasado ang kondisyon ng kamay"

    # --- Step 6: Click logic (pinch) ---
    if click_active:
        actions.extend(
            _click_actions_from_pinch_flags(
                pinch_index=pinch_index,
                pinch_middle=pinch_middle,
                settings=settings,
                state=state,
                now=now,
            )
        )

    return actions, mouse_status
