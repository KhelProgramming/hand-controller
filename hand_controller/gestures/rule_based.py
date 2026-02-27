"""Rule-based gesture recognizer (Core file).

Goal:
    Convert raw MediaPipe hand landmarks into "gesture results" that are easy
    to consume by controllers.

    Controllers should NOT do low-level math like:
        - compute thumb-index distance
        - compare landmark x/y ordering
        - handle hysteresis thresholds

    Instead, controllers receive high-level meaning like:
        - PALM_FACING
        - HAND_OPEN
        - PINCH_THUMB_INDEX (level)
        - PINCH_THUMB_INDEX_DOWN (one-shot event)

Why this file is "core":
    Dito usually nanggagaling ang confusion kasi maraming geometry + thresholds.
    Kaya we document heavily para madaling i-maintain ng group.

Important context:
    1) Mirrored frame
        Sa app.py, we do cv2.flip(frame, 1) para selfie-like.
        Side effect: Left/Right comparisons sa x-axis become "mirrored".
        Kaya may special rule sa palm-facing detection.

    2) Coordinate space
        MediaPipe landmarks are normalized (0..1).
        For pinch distances, we convert to frame pixels (FRAME_WIDTH x FRAME_HEIGHT).
        Reason: stable & intuitive threshold (pinch_threshold is in pixels).

    3) Keyboard click feel (Phase K6): Hysteresis
        Problem sa strict OPEN->PINCHED edge:
            Kapag close na fingers mo, stuck ka sa pinched state and
            hirap mag-trigger ulit.

        Solution:
            Use two thresholds:
                PRESS   (tighter)  -> triggers DOWN event
                RELEASE (looser)   -> re-arms when fingers separate

        In code:
            - "level" pinch uses pinch_threshold (legacy behavior)
            - "DOWN" events use press_th/release_th derived from multipliers
"""

from __future__ import annotations

import math
from typing import List

from ..core.coords import distance, get_landmark_pixel
from ..config.tuning import KEY_PINCH_PRESS_MULTIPLIER, KEY_PINCH_RELEASE_MULTIPLIER
from .base import (
    GestureResult,
    GestureRecognizer,
    GESTURE_HAND_OPEN,
    GESTURE_PALM_FACING,
    GESTURE_PINCH_INDEX,
    GESTURE_PINCH_INDEX_DOWN,
    GESTURE_PINCH_MIDDLE,
    GESTURE_PINCH_MIDDLE_DOWN,
    GESTURE_PINCH_RING,
    GESTURE_PINCH_PINKY_DOWN,
)


def is_palm_facing_thumb_pinky(hand_landmarks, handedness_label: str) -> bool:
    """Detect kung palm (harap) ang nakaharap sa camera.

    How (simple rule):
        Compare thumb.x and pinky.x positions.

    IMPORTANT NOTE (mirrored frame):
        Dahil naka cv2.flip(frame, 1) tayo, parang naka-salamin yung x-axis.
        So yung usual rule sa non-mirrored frame is baligtad dito.

    Rule used here (same as your original project):
        Right hand:
            thumb.x < pinky.x  => palm facing camera
            thumb.x > pinky.x  => back of hand

        Left hand:
            thumb.x > pinky.x  => palm facing camera
            thumb.x < pinky.x  => back of hand

    Why we care:
        - In mouse mode, palm-facing is a safety gate.
        - In mode toggle (K5), palm-facing reduces accidental toggles.
    """
    thumb = hand_landmarks.landmark[4]
    pinky = hand_landmarks.landmark[20]

    thumb_x = thumb.x
    pinky_x = pinky.x

    if handedness_label == "Right":
        return thumb_x < pinky_x
    return thumb_x > pinky_x


def is_hand_open(hand_landmarks) -> bool:
    """Detect kung "open hand" (bukas ang kamay).

    We check 4 fingers only (index, middle, ring, pinky):
        - compare tip.y vs pip.y
        - If tip is above pip (smaller y in image coords), finger is extended.

    Decision rule:
        If >= 3 fingers are extended -> considered open hand.

    Why not include thumb?
        Thumb orientation is tricky (sideways movement) and less stable.
        Your original logic also ignored thumb for open-hand detection.
    """
    finger_tips = [8, 12, 16, 20]
    finger_pips = [6, 10, 14, 18]

    extended_count = 0
    margin = 0.02

    for tip_id, pip_id in zip(finger_tips, finger_pips):
        tip = hand_landmarks.landmark[tip_id]
        pip = hand_landmarks.landmark[pip_id]
        if tip.y < pip.y - margin:
            extended_count += 1

    return extended_count >= 3


def _pinch_distance(hand_landmarks, frame_w: int, frame_h: int, idx_a: int, idx_b: int) -> float:
    """Return distance between two landmarks in *frame pixels*.

    Inputs:
        idx_a, idx_b = MediaPipe landmark indices.

    Why frame pixels?
        MediaPipe landmark coords are normalized (0..1).
        We convert to pixel space so pinch_threshold is intuitive and stable.
    """
    a = get_landmark_pixel(hand_landmarks, frame_w, frame_h, idx_a)
    b = get_landmark_pixel(hand_landmarks, frame_w, frame_h, idx_b)
    return float(distance(a, b))


def _is_pinch(hand_landmarks, frame_w: int, frame_h: int, idx_a: int, idx_b: int, pinch_threshold: float) -> bool:
    """Simple level pinch check (legacy behavior).

    NOTE:
        This is "level" pinch only (continuous state).
        For keyboard click feel, we use hysteresis in _update_press_state.
    """
    return _pinch_distance(hand_landmarks, frame_w, frame_h, idx_a, idx_b) < pinch_threshold


def _update_press_state(*, prev_pressed: bool, dist_px: float, press_th: float, release_th: float) -> bool:
    """Hysteresis press state (button-like feel).

    Problem (single threshold):
        Kapag close na close na fingers mo, lagi siyang "pinched".
        Hirap mag-trigger ng bagong click event dahil walang OPEN->PINCHED transition.

    Solution (PRESS + RELEASE):
        - PRESS threshold (tighter): kailangan lumapit bago mag-press
        - RELEASE threshold (looser): kailangan lumayo muna bago ma-rearm

    Example mental model:
        Parang physical mouse button:
            press down -> click once
            release    -> ready ulit

    Returns:
        new_pressed (bool): updated pressed state
    """
    if prev_pressed:
        return False if dist_px > release_th else True
    return True if dist_px < press_th else False


class RuleBasedGestureRecognizer:
    """Gesture recognizer using hard-coded rules (baseline).

    IMPORTANT: Stateful ito.
        Meaning: may memory siya across frames.

    Bakit kailangan ng state?
        - For "DOWN" events (keypress), we need to know previous pressed state
          to detect the moment of pressing.
        - Also for hysteresis, we need to remember if currently pressed.

    Internal states (per hand_label):
        _prev_pinch_*   -> level pinch state (mostly legacy / debug)
        _pressed_*      -> hysteresis press state used for DOWN events
    """

    def __init__(self) -> None:
        # per-hand *level* pinch state (legacy threshold)
        self._prev_pinch_index = {}
        self._prev_pinch_middle = {}
        self._prev_pinch_pinky = {}

        # per-hand "press" state for edge events (hysteresis thresholds)
        self._pressed_index = {}
        self._pressed_middle = {}
        self._pressed_pinky = {}

    def recognize(
        self,
        *,
        hands_list,
        frame_w: int,
        frame_h: int,
        pinch_threshold: float,
    ) -> List[GestureResult]:
        results: List[GestureResult] = []

        # ------------------------------------------------------------
        # Step 0: Build hysteresis thresholds (for DOWN events)
        # ------------------------------------------------------------
        # We keep pinch_threshold as the "legacy" level pinch threshold.
        # But for click-like behavior (keyboard presses), we derive:
        #   press_th   = pinch_threshold * KEY_PINCH_PRESS_MULTIPLIER
        #   release_th = pinch_threshold * KEY_PINCH_RELEASE_MULTIPLIER
        #
        # Typical numbers (from tuning.py):
        #   press < release (release is looser), so it re-arms more easily.
        press_th = float(pinch_threshold) * float(KEY_PINCH_PRESS_MULTIPLIER)
        release_th = float(pinch_threshold) * float(KEY_PINCH_RELEASE_MULTIPLIER)
        if release_th < press_th:
            # Safeguard: should not happen, pero para iwas weird configs.
            release_th = press_th

        # Track which hands exist this frame so we can clean up missing hands later.
        present_hands = set()

        # ------------------------------------------------------------
        # Step 1: Loop through each detected hand
        # ------------------------------------------------------------
        for h in hands_list or []:
            hand_label = h.get("label")
            lm = h.get("landmarks")
            if lm is None or not hand_label:
                continue

            present_hands.add(hand_label)

            # --------------------------------------------------------
            # Step 2: Palm facing detection
            # --------------------------------------------------------
            if is_palm_facing_thumb_pinky(lm, hand_label):
                results.append(GestureResult(name=GESTURE_PALM_FACING, confidence=1.0, hand_label=hand_label))

            # --------------------------------------------------------
            # Step 3: Open hand detection
            # --------------------------------------------------------
            if is_hand_open(lm):
                results.append(GestureResult(name=GESTURE_HAND_OPEN, confidence=1.0, hand_label=hand_label))

            # --------------------------------------------------------
            # Step 4: Pinch calculations (distances in frame pixels)
            # --------------------------------------------------------
            # We'll compute distances once then reuse.
            d_index = _pinch_distance(lm, frame_w, frame_h, 4, 8)
            pinch_index = d_index < pinch_threshold
            if pinch_index:
                results.append(GestureResult(name=GESTURE_PINCH_INDEX, confidence=1.0, hand_label=hand_label))

            # --------------------------------------------------------
            # Step 5: Keyboard-style "DOWN" event (hysteresis)
            # --------------------------------------------------------
            # If new_pressed becomes True from False -> emit DOWN once.
            prev_pressed = bool(self._pressed_index.get(hand_label, False))
            new_pressed = _update_press_state(
                prev_pressed=prev_pressed,
                dist_px=d_index,
                press_th=press_th,
                release_th=release_th,
            )
            if new_pressed and not prev_pressed:
                results.append(GestureResult(name=GESTURE_PINCH_INDEX_DOWN, confidence=1.0, hand_label=hand_label))
            self._pressed_index[hand_label] = new_pressed
            self._prev_pinch_index[hand_label] = pinch_index

            d_middle = _pinch_distance(lm, frame_w, frame_h, 4, 12)
            pinch_middle = d_middle < pinch_threshold

            if pinch_middle:
                results.append(GestureResult(name=GESTURE_PINCH_MIDDLE, confidence=1.0, hand_label=hand_label))

            prev_pressed_mid = bool(self._pressed_middle.get(hand_label, False))
            new_pressed_mid = _update_press_state(
                prev_pressed=prev_pressed_mid,
                dist_px=d_middle,
                press_th=press_th,
                release_th=release_th,
            )
            if new_pressed_mid and not prev_pressed_mid:
                results.append(GestureResult(name=GESTURE_PINCH_MIDDLE_DOWN, confidence=1.0, hand_label=hand_label))
            self._pressed_middle[hand_label] = new_pressed_mid
            self._prev_pinch_middle[hand_label] = pinch_middle

            # --------------------------------------------------------
            # Step 6: Thumb + Pinky DOWN (one-shot shift in keyboard mode)
            # --------------------------------------------------------
            d_pinky = _pinch_distance(lm, frame_w, frame_h, 4, 20)
            pinch_pinky = d_pinky < pinch_threshold
            prev_pressed_pinky = bool(self._pressed_pinky.get(hand_label, False))
            new_pressed_pinky = _update_press_state(
                prev_pressed=prev_pressed_pinky,
                dist_px=d_pinky,
                press_th=press_th,
                release_th=release_th,
            )
            if new_pressed_pinky and not prev_pressed_pinky:
                results.append(GestureResult(name=GESTURE_PINCH_PINKY_DOWN, confidence=1.0, hand_label=hand_label))
            self._pressed_pinky[hand_label] = new_pressed_pinky
            self._prev_pinch_pinky[hand_label] = pinch_pinky

            # --------------------------------------------------------
            # Step 7: Thumb + Ring level pinch (mode toggle hold)
            # --------------------------------------------------------
            if _is_pinch(lm, frame_w, frame_h, 4, 16, pinch_threshold):
                results.append(GestureResult(name=GESTURE_PINCH_RING, confidence=1.0, hand_label=hand_label))

        # ------------------------------------------------------------
        # Step 8: Cleanup per-hand states
        # ------------------------------------------------------------
        # If a hand disappears, remove its state to avoid memory growth
        # and stale "pressed" states.
        for hand in list(self._prev_pinch_index.keys()):
            if hand not in present_hands:
                self._prev_pinch_index.pop(hand, None)
                self._prev_pinch_middle.pop(hand, None)
                self._prev_pinch_pinky.pop(hand, None)
                self._pressed_index.pop(hand, None)
                self._pressed_middle.pop(hand, None)
                self._pressed_pinky.pop(hand, None)

        return results


