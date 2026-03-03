from __future__ import annotations
from typing import List
import numpy as np

EPS = 1e-9

def calculate_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    ba = a - b
    bc = c - b
    denom = float(np.linalg.norm(ba) * np.linalg.norm(bc))
    if denom < EPS:
        return 0.0
    cosang = float(np.dot(ba, bc) / denom)
    cosang = float(np.clip(cosang, -1.0, 1.0))
    return float(np.degrees(np.arccos(cosang)))

def _normalized_points(hand_landmarks) -> np.ndarray:
    raw = np.array([[lm.x, lm.y, lm.z] for lm in hand_landmarks.landmark], dtype=np.float64)
    return raw - raw[0]  # wrist relative

def extract_geo18(hand_landmarks) -> List[float]:
    p = _normalized_points(hand_landmarks)

    palm_width = float(np.linalg.norm(p[5] - p[17]))
    if palm_width < 1e-6:
        palm_width = 1.0

    wrist = p[0]

    extensions = [
        float(np.linalg.norm(wrist - p[i]) / palm_width)
        for i in (4, 8, 12, 16, 20)
    ]

    thumb_tip = p[4]
    pinches = [
        float(np.linalg.norm(thumb_tip - p[i]) / palm_width)
        for i in (8, 12, 16, 20)
    ]

    spreads = [
        float(np.linalg.norm(p[i] - p[j]) / palm_width)
        for i, j in ((8, 12), (12, 16), (16, 20))
    ]

    thumb_to_pinky_base = float(np.linalg.norm(p[4] - p[17]) / palm_width)

    angles = [
        calculate_angle(p[1], p[2], p[3]) / 180.0,
        calculate_angle(p[5], p[6], p[7]) / 180.0,
        calculate_angle(p[9], p[10], p[11]) / 180.0,
        calculate_angle(p[13], p[14], p[15]) / 180.0,
        calculate_angle(p[17], p[18], p[19]) / 180.0,
    ]

    return extensions + pinches + spreads + [thumb_to_pinky_base] + angles
