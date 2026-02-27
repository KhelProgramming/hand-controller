"""hand_controller/vision/hand_tracker.py 

PURPOSE:
  Wrapper ito sa MediaPipe Hands.
  Instead na scattered sa app.py ang MediaPipe config + result parsing,
  nandito lahat para malinis ang codebase.

WHY THIS EXISTS:
  1) Single place to configure MediaPipe Hands
     (max hands, detection confidence, tracking confidence).
  2) Single place to convert MediaPipe result -> mas madaling structure.
  3) Easier i-swap later (if you change tracking library).

IMPORTANT NOTES:
  - MediaPipe expects RGB frames.
    OpenCV default is BGR, so sa app.py we do cv2.cvtColor(BGR->RGB).
  - MediaPipe gives:
      result.multi_hand_landmarks  -> list of landmarks (21 points per hand)
      result.multi_handedness      -> list that says "Left" or "Right"

OUTPUT SHAPE (keeping backward compatibility):
  extract_hands(...) returns list of dicts like:
    {"label": "Left"/"Right", "landmarks": <mp hand_landmarks>}

  Why dict, not custom class?
    - Minimal behavior changes from your original code.
    - Controllers already expect that structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

import mediapipe as mp


@dataclass(frozen=True)
class HandData:
    """A small structured container for a detected hand."""

    label: str  # "Left" or "Right"
    landmarks: Any  # MediaPipe hand landmarks object


class HandTracker:
    """Wrapper around mp.solutions.hands.Hands.

    Think of this class as "hand detector + tracker".

    Responsibilities:
      - Create the MediaPipe Hands object with the right config.
      - Provide a `.process(rgb_frame)` method (just passes through).
      - Provide `.extract_hands(result)` to produce a stable structure.
      - Provide `.connections` for drawing skeleton lines.
    """

    def __init__(
        self,
        max_num_hands: int = 2,
        min_detection_confidence: float = 0.7,
        min_tracking_confidence: float = 0.7,
    ):
        # MediaPipe modules (kept as attributes for easier access later)
        self.mp_hands = mp.solutions.hands

        # NOTE:
        # mp_drawing existed in the original code but wasn't used.
        # Keeping it here is harmless and useful if you want to draw landmarks
        # in the future (debugging / demos).
        self.mp_drawing = mp.solutions.drawing_utils

        self.hands = self.mp_hands.Hands(
            max_num_hands=max_num_hands,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    @property
    def connections(self):
        """Hand skeleton connections.

        What is this?
          - A list of landmark index pairs, like (0, 1), (1, 2), ...
          - Used by overlay to draw lines between landmarks (skeleton).
        """
        return self.mp_hands.HAND_CONNECTIONS

    def process(self, rgb_frame):
        """Run MediaPipe on an RGB frame.

        Input:
          rgb_frame: frame in RGB color order.

        Output:
          MediaPipe result object.

        Note:
          Wala tayong heavy logic dito.
          All heavy parsing happens in extract_hands().
        """
        return self.hands.process(rgb_frame)

    def extract_hands(self, result) -> List[Dict[str, Any]]:
        """Convert MediaPipe result -> simple list of hands.

        Goal:
          Gawing madaling kainin ng controllers ang output.

        Input:
          result: MediaPipe output from `.process()`.

        Returns:
          List[Dict[str, Any]] where each item is:
            {"label": "Left"/"Right", "landmarks": <hand_landmarks>}

        Why zip(...)?
          - MediaPipe provides landmarks and handedness in two lists.
          - We pair them up by order (they align).

        Edge case:
          - If no hands detected, both lists can be empty/None.
            We return [].
        """
        hands_list: List[Dict[str, Any]] = []
        if result.multi_hand_landmarks and result.multi_handedness:
            for lm, hd in zip(result.multi_hand_landmarks, result.multi_handedness):
                label = hd.classification[0].label
                hands_list.append({"label": label, "landmarks": lm})
        return hands_list

    def close(self) -> None:
        """Close underlying MediaPipe resources."""
        if self.hands is not None:
            self.hands.close()

    def __enter__(self) -> "HandTracker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
