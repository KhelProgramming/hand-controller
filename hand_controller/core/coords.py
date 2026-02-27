"""Coordinate and geometry helper functions.

These are intentionally kept *pure* (no global state) so they are easy to test.
"""

from __future__ import annotations

import math
from typing import Tuple


def frame_to_screen_xy(norm_x: float, norm_y: float, screen_w: int, screen_h: int) -> Tuple[int, int]:
    """Convert MediaPipe normalized landmark coordinates (0..1) to screen pixels."""
    sx = int(norm_x * screen_w)
    sy = int(norm_y * screen_h)
    return sx, sy


def get_landmark_pixel(hand_landmarks, frame_w: int, frame_h: int, idx: int) -> Tuple[int, int]:
    """Convert a landmark to *camera frame* pixel coordinates (e.g., 640x480)."""
    x = int(hand_landmarks.landmark[idx].x * frame_w)
    y = int(hand_landmarks.landmark[idx].y * frame_h)
    return x, y


def distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """Euclidean distance between two (x, y) points."""
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])
