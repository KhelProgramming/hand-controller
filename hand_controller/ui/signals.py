"""hand_controller.ui.signals

PURPOSE (UI / Hybrid comments):
    Thread-safe bridge between worker thread (cv_loop) and Qt UI thread.

Problem (bakit kailangan ito):
    - cv_loop runs in a background thread.
    - Qt widgets (OverlayWindow) must be updated only on the UI thread.

Solution:
    - Worker thread emits a signal with an overlay payload dict.
    - Qt queues that signal and delivers it to OverlayWindow.apply_state() safely.

Payload shape:
    The emitted object is usually a dict with keys matching
    OverlayWindow.update_state(...). Example keys:
      mode, keyboard_visible, highlight_labels, finger_points,
      skeleton_lines, selfie_frame, mouse_status, keyboard_status
"""

from PyQt5.QtCore import QObject, pyqtSignal


class OverlaySignalBus(QObject):
    """Signal container used as a safe messaging channel.

    update_overlay:
        Emits a single object (payload). We keep it as 'object' to allow
        flexible dict payloads without strict Qt type constraints.
    """

    update_overlay = pyqtSignal(object)
