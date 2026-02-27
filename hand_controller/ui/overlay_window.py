"""hand_controller.ui.overlay_window

PURPOSE (UI / Hybrid comments):
    Ito ang fullscreen transparent overlay na nakapatong sa buong screen.

    Important: renderer lang siya.
      - Hindi siya gumagawa ng hand tracking.
      - Hindi siya nagde-decide kung ano ang gagawin (mouse move / click / type).

USED BY:
    - ui.main_window.MainWindow: siya ang nagc-create ng OverlayWindow.
    - app.cv_loop (worker thread): gumagawa ng overlay payload bawat frame.
    - ui.signals.OverlaySignalBus: thread-safe bridge para i-update ang overlay.

KEY IDEA:
    - OverlayWindow draws whatever "state" it is given.
    - Worker thread MUST NOT directly manipulate Qt widgets.
      Kaya ginagamit natin ang apply_state() slot + Qt signals.
"""

import cv2

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import Qt, QRect, pyqtSlot
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QImage


# NOTE:
#   We keep behavior identical by using the same shared module-level settings/state
#   stored in hand_controller.app (screen_w/screen_h, profiles, constants, etc.)
from .. import app as appmod


class OverlayWindow(QWidget):
    """Transparent always-on-top overlay window.

    Responsibilities (UI-only):
      - Draw keyboard rectangles + highlighted keys
      - Draw hand skeleton (lines)
      - Draw fingertip indicators (circles + optional L/R labels)
      - Draw selfie preview (small camera view)
      - Draw status labels (mode/profile/mouse status/keyboard status)

    What it does NOT do:
      - No MediaPipe / camera processing
      - No mode decision
      - No pyautogui side effects

    Threading note:
      - All painting happens on the UI thread.
      - Worker thread sends "payload" via Qt signal.
      - apply_state() receives payload safely and updates internal fields.
    """

    def __init__(self, keyboard_keys):
        super().__init__()
        self.keyboard_keys = keyboard_keys

        # State that controls what the overlay will draw.
        # These values are updated every frame via apply_state().
        self.mode = "mouse"  # "mouse" or "keyboard"
        self.keyboard_visible = False
        self.highlight_labels = set()
        self.finger_points = []   # list[(x,y)] or list[dict] for labeled points
        self.skeleton_lines = []  # list[(x1,y1,x2,y2)]
        self.selfie_frame = None
        self.mouse_status = ""
        self.keyboard_status = ""
        self.profile_name = appmod.CURRENT_PROFILE

        # Selfie preview settings (UI only)
        self.selfie_enabled = True
        self.selfie_scale = 1.0
        self.selfie_position = "top_left"  # top_left/top_right/bottom_left/bottom_right

        self.init_ui()

    def init_ui(self):
        """Setup ng itsura at behavior ng overlay window."""
        self.setWindowTitle("Hand Controller Overlay")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )

        # Transparent overlay:
        # - WA_TranslucentBackground: allows alpha transparency
        # - WA_TransparentForMouseEvents: passes mouse clicks through to apps below
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.setGeometry(0, 0, appmod.screen_w, appmod.screen_h)
        self.showFullScreen()

    def set_profile(self, name):
        """Palit mouse profile (UI-triggered).

        Note:
            To keep behavior identical (and avoid rewriting settings plumbing),
            we update the shared globals in appmod.
        """
        if name not in appmod.PROFILES:
            return

        p = appmod.PROFILES[name]
        appmod.SENSITIVITY = p["sens"]
        appmod.SMOOTHING = p["smooth"]
        appmod.DEADZONE = p["deadzone"]
        appmod.CURRENT_PROFILE = name
        self.profile_name = name
        self.update()

    def set_profile_custom_label(self):
        """Kapag binago ang sliders, lagyan ng * ang profile label."""
        self.profile_name = f"{appmod.CURRENT_PROFILE}*"
        self.update()

    def set_selfie_config(self, enabled=None, scale=None, position=None):
        """Apply selfie settings (enabled / scale / position)."""
        if enabled is not None:
            self.selfie_enabled = bool(enabled)
        if scale is not None:
            s = float(scale)
            # Clamp scale for safety
            if s < 0.2:
                s = 0.2
            if s > 3.0:
                s = 3.0
            self.selfie_scale = s
        if position is not None:
            self.selfie_position = position

        self.update()

    def update_state(
        self,
        mode,
        keyboard_visible,
        highlight_labels,
        finger_points,
        skeleton_lines,
        selfie_frame,
        mouse_status,
        keyboard_status="",
    ):
        """Update overlay render state.

        IMPORTANT:
            Huwag ito tawagin directly from worker thread.
            Use apply_state() (Qt slot) via OverlaySignalBus.

        Why:
            Qt widgets are not thread-safe. Direct calls from worker thread can
            lead to random freezes/crashes.
        """
        self.mode = mode
        self.keyboard_visible = keyboard_visible
        self.highlight_labels = highlight_labels or set()
        self.finger_points = finger_points or []
        self.skeleton_lines = skeleton_lines or []
        self.selfie_frame = selfie_frame
        self.mouse_status = mouse_status or ""
        self.keyboard_status = keyboard_status or ""
        self.update()

    @pyqtSlot(object)
    def apply_state(self, payload):
        """Thread-safe entry point for updating the overlay.

        Expected payload:
            dict with keys matching update_state() parameters.

        Why try/except:
            Kapag nag-stop ang app, possible na may queued signal pa rin.
            If overlay is closing, ignore safely.
        """
        if not isinstance(payload, dict):
            return
        try:
            self.update_state(**payload)
        except Exception:
            pass

    def paintEvent(self, event):
        """Actual drawing routine.

        Paint order matters (para hindi natatakpan ang important visuals):
          1) selfie preview (background corner)
          2) keyboard (if visible)
          3) skeleton lines
          4) fingertip circles
          5) texts (mode/profile/status)
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        self.draw_selfie(painter)
        if self.keyboard_visible:
            self.draw_keyboard(painter)
        self.draw_skeleton(painter)
        self.draw_fingers(painter)
        self.draw_mode_and_profile_text(painter)
        self.draw_mouse_status(painter)
        self.draw_keyboard_status(painter)
        self.draw_profile_hint(painter)

    def draw_keyboard(self, painter):
        """Draw keyboard rectangles + labels.

        Highlighting:
            highlight_labels contains key labels currently hovered by pointer(s)
            (left/right hand).
        """
        font = QFont("Arial", appmod.KEY_FONT_SIZE)
        painter.setFont(font)

        for key in self.keyboard_keys:
            x1, y1, x2, y2 = key["x1"], key["y1"], key["x2"], key["y2"]
            label = key["label"]

            if label in self.highlight_labels:
                pen = QPen(QColor(0, 255, 255, 255), 3)
                brush = QBrush(QColor(0, 0, 0, 150))
            else:
                pen = QPen(QColor(200, 200, 200, 180), 2)
                brush = QBrush(QColor(0, 0, 0, 120))

            painter.setPen(pen)
            painter.setBrush(brush)
            rect = QRect(x1, y1, x2 - x1, y2 - y1)
            painter.drawRect(rect)

            text = "SPACE" if label == "SPACE" else label
            painter.setPen(QColor(255, 255, 255, 230))
            painter.drawText(rect, Qt.AlignCenter, text)

    def draw_fingers(self, painter):
        """Draw fingertip indicators.

        finger_points format:
            - old format: list of (x, y)
            - new format (K3): list of dicts with {x,y,hand_label}
              so we can render "L" / "R" tag near pointer circles.
        """
        if not self.finger_points:
            return

        pen = QPen(QColor(0, 255, 255, 230), 2)
        brush = QBrush(QColor(0, 255, 255, 100))
        painter.setPen(pen)
        painter.setBrush(brush)

        painter.setFont(QFont("Arial", 10, QFont.Bold))

        for pt in self.finger_points:
            if isinstance(pt, dict):
                x = int(pt.get("x", 0))
                y = int(pt.get("y", 0))
                hand_label = str(pt.get("hand_label", ""))
            else:
                x, y = pt
                hand_label = ""

            painter.drawEllipse(
                x - appmod.FINGER_RADIUS,
                y - appmod.FINGER_RADIUS,
                appmod.FINGER_RADIUS * 2,
                appmod.FINGER_RADIUS * 2,
            )

            # Small label for 2-hand typing clarity
            if hand_label in ("Left", "Right"):
                tag = "L" if hand_label == "Left" else "R"
                painter.setPen(QColor(255, 255, 255, 230))
                painter.drawText(
                    x + appmod.FINGER_RADIUS + 2,
                    y - appmod.FINGER_RADIUS - 2,
                    tag,
                )
                painter.setPen(pen)

    def draw_skeleton(self, painter):
        """Draw skeleton lines."""
        pen = QPen(QColor(0, 200, 255, 180), 2)
        painter.setPen(pen)
        for (x1, y1, x2, y2) in self.skeleton_lines:
            painter.drawLine(x1, y1, x2, y2)

    def draw_selfie(self, painter):
        """Draw selfie preview (camera frame) at chosen corner.

        Note:
            Yung resizing to SELFIE_WIDTH/HEIGHT ginagawa na sa cv loop
            para mas light ang work sa UI thread.
        """
        if self.selfie_frame is None:
            return
        if not self.selfie_enabled:
            return

        frame = self.selfie_frame
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)

        scale = self.selfie_scale
        disp_w = int(appmod.SELFIE_WIDTH * scale)
        disp_h = int(appmod.SELFIE_HEIGHT * scale)

        margin = 20
        pos = self.selfie_position

        if pos == "top_left":
            x = margin
            y = margin
        elif pos == "top_right":
            x = appmod.screen_w - disp_w - margin
            y = margin
        elif pos == "bottom_left":
            x = margin
            y = appmod.screen_h - disp_h - margin
        elif pos == "bottom_right":
            x = appmod.screen_w - disp_w - margin
            y = appmod.screen_h - disp_h - margin
        else:
            x = margin
            y = margin

        target_rect = QRect(x, y, disp_w, disp_h)
        painter.drawImage(target_rect, qimg)

    def draw_mode_and_profile_text(self, painter):
        """Draw mode + profile label."""
        mode_text = f"mode: {self.mode}"
        profile_text = f"profile: {self.profile_name}"

        painter.setFont(QFont("Arial", 14))
        painter.setPen(
            QColor(0, 255, 0, 220)
            if self.mode == "mouse"
            else QColor(0, 200, 255, 220)
        )

        base_x = 20
        base_y = appmod.SELFIE_HEIGHT + 40
        painter.drawText(base_x, base_y, mode_text)

        painter.setPen(QColor(255, 255, 255, 200))
        painter.drawText(base_x, base_y + 20, profile_text)

    def draw_mouse_status(self, painter):
        """Draw mouse-mode status notice."""
        if self.mode != "mouse":
            return
        if not self.mouse_status:
            return

        x = 20
        y = appmod.SELFIE_HEIGHT + 80

        bg_rect = QRect(x, y - 22, 620, 32)
        painter.setBrush(QBrush(QColor(0, 0, 0, 160)))
        painter.setPen(QPen(QColor(0, 0, 0, 0), 0))
        painter.drawRect(bg_rect)

        painter.setPen(QColor(255, 230, 180, 240))
        painter.setFont(QFont("Arial", 13))
        painter.drawText(
            bg_rect,
            Qt.AlignVCenter | Qt.AlignLeft,
            "  " + self.mouse_status,
        )

    def draw_keyboard_status(self, painter):
        """Draw keyboard-mode status (e.g., SHIFT + hovered keys per hand)."""
        if self.mode != "keyboard":
            return
        if not self.keyboard_status:
            return

        x = 20
        y = appmod.SELFIE_HEIGHT + 80

        bg_rect = QRect(x, y - 22, 620, 32)
        painter.setBrush(QBrush(QColor(0, 0, 0, 160)))
        painter.setPen(QPen(QColor(0, 0, 0, 0), 0))
        painter.drawRect(bg_rect)

        painter.setPen(QColor(180, 220, 255, 240))
        painter.setFont(QFont("Arial", 13))
        painter.drawText(
            bg_rect,
            Qt.AlignVCenter | Qt.AlignLeft,
            "  " + self.keyboard_status,
        )

    def draw_profile_hint(self, painter):
        """Small hint about profiles."""
        painter.setFont(QFont("Arial", 11))
        painter.setPen(QColor(180, 180, 180, 200))
        text = "mouse profiles: precision / balanced / fast / crazy (editable sa control panel)"
        x = 20
        y = appmod.SELFIE_HEIGHT + 110
        painter.drawText(x, y, text)
