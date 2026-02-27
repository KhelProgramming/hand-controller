"""Mode management (Core file).

Goal:
    Dito naka-store ang "current mode" ng app:
        - "mouse"    -> mouse movement + mouse clicks
        - "keyboard" -> virtual keyboard + pinch-to-type typing


        input: GestureResults
        output: current mode (+ toggled_this_frame)

How toggling works (summary):
    - Gesture used: thumb + ring pinch (level gesture)
    - Condition: "hold" for a short duration (ex: ~0.3s)
    - Safety:
        - optional require PALM_FACING
        - ignore toggle tracking if the same hand is doing thumb-index pinch
          (so hindi ka nagto-toggle habang nagta-type / nagpi-pinch)
    - Cooldown:
        after toggle, may cooldown para iwas accidental double toggle.

Important idea: HOLD + CONSUME
    - "hold" means: kailangan tuloy-tuloy yung pinch for N seconds.
    - "consumed" means: once nag-toggle na during a hold, hindi siya magto-toggle
      ulit until i-release mo yung pinch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple

from ..config.tuning import (
    MODE_TOGGLE_COOLDOWN_SECONDS,
    MODE_TOGGLE_HOLD_SECONDS,
    MODE_TOGGLE_MIN_CONFIDENCE,
    MODE_TOGGLE_REQUIRE_PALM_FACING,
)
from ..gestures.base import (
    GESTURE_PALM_FACING,
    GESTURE_PINCH_INDEX,
    GESTURE_PINCH_RING,
)


@dataclass(slots=True)
class ModeSettings:
    """Tuning parameters for mode switching.

    Tip:
        Most of these defaults are loaded from config/tuning.py
        para isang place lang ang adjustment.
    """

    toggle_hold_seconds: float = MODE_TOGGLE_HOLD_SECONDS
    toggle_cooldown_seconds: float = MODE_TOGGLE_COOLDOWN_SECONDS

    # Safety improvements
    require_palm_facing: bool = MODE_TOGGLE_REQUIRE_PALM_FACING
    min_toggle_confidence: float = MODE_TOGGLE_MIN_CONFIDENCE


@dataclass(slots=True)
class ModeState:
    """Runtime state (memory) for mode switching.

    This is the "brain memory" ng ModeManager.

    Fields:
        mode:
            Current mode string.

        last_toggle_time:
            Timestamp ng last successful toggle.
            Used for cooldown.

        ring_hold_start:
            Dict per hand_label -> when the hold started.

        ring_hold_consumed:
            Dict per hand_label -> True if we already toggled during the current hold.
            Why: prevents repeated toggles while still pinching.
    """

    mode: str = "mouse"  # "mouse" or "keyboard"

    # last time we toggled modes
    # Start far in the past so the first toggle isn't blocked by cooldown.
    last_toggle_time: float = -1e9

    # per-hand ring-pinch hold tracking
    ring_hold_start: Dict[str, float] = field(default_factory=dict)
    ring_hold_consumed: Dict[str, bool] = field(default_factory=dict)


class ModeManager:
    """Gesture-driven mode state machine.

    Design goal:
        Keep this pure-ish:
            - No pyautogui
            - No UI calls
        Just read gestures and update internal state.
    """

    def __init__(self, *, settings: Optional[ModeSettings] = None, state: Optional[ModeState] = None):
        self.settings = settings or ModeSettings()
        self.state = state or ModeState()

    @property
    def mode(self) -> str:
        return self.state.mode

    def update(self, *, gesture_results, now: float) -> Tuple[str, bool]:
        """Update the current mode based on latest gesture results.

        Inputs:
            gesture_results:
                List[GestureResult] for current frame.
                Important ones here:
                    - PINCH_THUMB_RING (level)
                    - PALM_FACING (safety)
                    - PINCH_THUMB_INDEX (safety / do-not-toggle while typing)

            now:
                Current timestamp (float). Passed in para testable.

        Returns:
            (mode, toggled_this_frame)
        """
        # ------------------------------------------------------------
        # Step 1: Collect ring-pinch candidates (per hand)
        # ------------------------------------------------------------
        # We gather ring-pinch gestures and keep the best confidence per hand.
        ring_conf: Dict[str, float] = {}
        for g in (gesture_results or []):
            if getattr(g, "name", None) != GESTURE_PINCH_RING:
                continue
            hand = getattr(g, "hand_label", None)
            if not hand:
                continue
            conf = float(getattr(g, "confidence", 0.0) or 0.0)
            if conf < self.settings.min_toggle_confidence:
                continue
            ring_conf[hand] = max(ring_conf.get(hand, 0.0), conf)

        ring_hands: Set[str] = set(ring_conf.keys())

        # ------------------------------------------------------------
        # Step 2: Which hands are PALM_FACING right now?
        # ------------------------------------------------------------
        palm_hands: Set[str] = {
            g.hand_label
            for g in (gesture_results or [])
            if getattr(g, "name", None) == GESTURE_PALM_FACING and getattr(g, "hand_label", None)
        }

        # ------------------------------------------------------------
        # Step 3: Safety rule (K1): don't toggle while thumb-index pinch is active
        # ------------------------------------------------------------
        # Reason: thumb-index pinch is used for typing/clicking.
        # If we allow toggle while typing, sobrang annoying.
        index_hands: Set[str] = {
            g.hand_label
            for g in (gesture_results or [])
            if getattr(g, "name", None) == GESTURE_PINCH_INDEX and g.hand_label
        }

        # ------------------------------------------------------------
        # Step 4: Reset tracking for hands that no longer qualify
        # ------------------------------------------------------------
        # If a hand stops ring-pinching OR fails palm-facing requirement,
        # we clear hold state so next time it starts fresh.
        for hand in list(self.state.ring_hold_start.keys()):
            if hand not in ring_hands:
                self.state.ring_hold_start.pop(hand, None)
                self.state.ring_hold_consumed.pop(hand, None)
                continue

            # If palm-facing is required but no longer true, reset tracking.
            if self.settings.require_palm_facing and hand not in palm_hands:
                self.state.ring_hold_start.pop(hand, None)
                self.state.ring_hold_consumed.pop(hand, None)

        toggled = False

        # ------------------------------------------------------------
        # Step 5: Track holds for active ring pinches
        # ------------------------------------------------------------
        for hand in ring_hands:
            # If the same hand is index-pinching, ignore and reset tracking.
            if hand in index_hands:
                self.state.ring_hold_start.pop(hand, None)
                self.state.ring_hold_consumed.pop(hand, None)
                continue

            # Safety: require palm facing during the hold (Phase K5).
            if self.settings.require_palm_facing and hand not in palm_hands:
                self.state.ring_hold_start.pop(hand, None)
                self.state.ring_hold_consumed.pop(hand, None)
                continue

            if hand not in self.state.ring_hold_start:
                # First frame of the hold: mark start time.
                self.state.ring_hold_start[hand] = now
                self.state.ring_hold_consumed[hand] = False
                continue

            # Already consumed for this hold; require release to re-arm.
            if self.state.ring_hold_consumed.get(hand, False):
                continue

            held_for = now - self.state.ring_hold_start[hand]
            if held_for < self.settings.toggle_hold_seconds:
                continue

            if (now - self.state.last_toggle_time) < self.settings.toggle_cooldown_seconds:
                continue

            # --------------------------------------------------------
            # Step 6: Toggle mode
            # --------------------------------------------------------
            self.state.mode = "keyboard" if self.state.mode == "mouse" else "mouse"
            self.state.last_toggle_time = now
            toggled = True

            # Mark all currently active ring holds as consumed to prevent a second toggle
            # without releasing the pinch.
            for h in ring_hands:
                self.state.ring_hold_consumed[h] = True
            break

        return self.state.mode, toggled
