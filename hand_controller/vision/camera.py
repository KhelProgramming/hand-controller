"""

Small wrapper around cv2.VideoCapture.

Goal: centralize camera creation/config (index, resolution) and
provide a tiny API that keeps behavior identical to the original code.
"""

from __future__ import annotations

import cv2


class Camera:
    """OpenCV camera wrapper.

    Notes:
    - Uses cv2.VideoCapture under the hood.
    - Sets width/height using OpenCV property IDs 3 and 4 (same as original).
    """

    def __init__(self, index: int = 0, width: int = 640, height: int = 480):
        self.index = index
        self.width = width
        self.height = height

        self.cap = cv2.VideoCapture(self.index)
        # Keep the same property IDs used in the original file.
        self.cap.set(3, self.width)
        self.cap.set(4, self.height)

    def read(self):
        """Read a frame. Returns (ret, frame) exactly like cv2.VideoCapture.read."""
        return self.cap.read()

    def release(self) -> None:
        """Release the camera."""
        if self.cap is not None:
            self.cap.release()

    def is_opened(self) -> bool:
        return bool(self.cap is not None and self.cap.isOpened())

    def __enter__(self) -> "Camera":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
