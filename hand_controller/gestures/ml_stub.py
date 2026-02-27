"""ML gesture recognizer stub (Phase 5).

This is a placeholder for your groupmates' ML model.

Expected behavior:
- Load or initialize an ML model (e.g., MediaPipe gesture classifier, custom
  trained model, etc.)
- In `recognize(...)`, output GestureResult entries such as:
    - PALM_FACING
    - HAND_OPEN
    - PINCH_THUMB_INDEX
    - PINCH_THUMB_MIDDLE
  with a confidence score (0..1).

For now, it returns an empty list so the app keeps working.
"""

from __future__ import annotations

from typing import List

from .base import GestureResult


class MLGestureRecognizerStub:
    def __init__(self, *args, **kwargs) -> None:
        # Later: load model weights, init preprocessors, etc.
        pass

    def recognize(self, *, hands_list, frame_w: int, frame_h: int, pinch_threshold: float) -> List[GestureResult]:
        # Later: run inference; map model outputs to GestureResult
        return []
