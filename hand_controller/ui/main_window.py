"""hand_controller.ui.main_window

PURPOSE (UI / Hybrid comments):
    Ito ang "control panel" window (yung normal app window na may Start/Stop at tabs).

    Dito mo makikita:
      - Start/Stop controller
      - Mouse profile + sliders (sens/smoothing/deadzone)
      - Keyboard instructions (pinch-to-type + speed boosts)
      - Overlay settings (selfie preview)

IMPORTANT:
    - MainWindow is UI-only.
    - Ang computer vision loop (cv_loop) tumatakbo sa worker thread.
    - MainWindow ang nagse-set up ng signal bridge (OverlaySignalBus)
      para thread-safe mag-update ng OverlayWindow.

NOTE ABOUT SETTINGS:
    To keep behavior identical habang phased refactor, some runtime settings are still
    stored as module-level globals in hand_controller.app (imported as appmod).


"""

import threading

from PyQt5.QtWidgets import (
    QWidget,
    QMainWindow,
    QPushButton,
    QLabel,
    QComboBox,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QFormLayout,
    QSlider,
    QCheckBox,
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont


# Shared constants/settings/state currently live in app module.
from .. import app as appmod

# UI pieces
from .overlay_window import OverlayWindow
from .signals import OverlaySignalBus


class MainWindow(QMainWindow):
    """Main control panel UI.

    Responsibilities:
      - Create/destroy OverlayWindow
      - Start/stop the worker thread that runs cv_loop
      - Expose UI controls for settings (mouse/keyboard/selfie)

    What it does NOT do:
      - No hand tracking logic
      - No pyautogui calls

    Design note:
      cv_loop is injected (cv_loop_fn) to avoid circular imports and keep layering clean.
    """

    def __init__(self, keyboard_keys, cv_loop_fn):
        super().__init__()

        self.keyboard_keys = keyboard_keys
        self.cv_loop_fn = cv_loop_fn

        self.overlay = None
        self.overlay_bus = None
        self.controller_thread = None
        self.stop_event = None
        self.controller_running = False

        self.status_label = None
        self.start_button = None
        self.profile_combo = None

        self.sens_slider = None
        self.sens_value_label = None
        self.smooth_slider = None
        self.smooth_value_label = None
        self.deadzone_slider = None
        self.deadzone_value_label = None

        # selfie settings config (stored here so it persists across start/stop)
        self.selfie_enabled_cfg = True
        self.selfie_scale_cfg = 1.0
        self.selfie_pos_cfg = "top_left"

        # selfie controls
        self.selfie_checkbox = None
        self.selfie_pos_combo = None
        self.selfie_size_slider = None
        self.selfie_size_label = None

        # keyboard feel controls (legacy flex-tap, kept disabled)
        self.tap_sens_slider = None
        self.tap_sens_label = None
        self.tap_cd_slider = None
        self.tap_cd_label = None
        self.thumb_space_checkbox = None

        self.init_ui()

    def init_ui(self):
        """Setup ng itsura ng control panel window."""
        self.setWindowTitle("Hand Controller")
        self.resize(900, 600)

        central = QWidget()
        main_layout = QHBoxLayout()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

        # Left panel: title + status + Start/Stop + profile selector
        left_panel = QVBoxLayout()
        left_panel.setContentsMargins(20, 20, 20, 20)
        left_panel.setSpacing(15)

        title_label = QLabel("Hand Controller")
        title_label.setFont(QFont("Arial", 18, QFont.Bold))
        left_panel.addWidget(title_label)

        self.status_label = QLabel("Status: Stopped")
        self.status_label.setFont(QFont("Arial", 12))
        self.status_label.setStyleSheet("color: #ff5555;")
        left_panel.addWidget(self.status_label)

        self.start_button = QPushButton("Start controller")
        self.start_button.setFont(QFont("Arial", 14, QFont.Bold))
        self.start_button.setFixedHeight(48)
        self.start_button.setStyleSheet(
            "background-color: #55aa55; color: white; border-radius: 6px;"
        )
        self.start_button.clicked.connect(self.toggle_controller)
        left_panel.addWidget(self.start_button)

        left_panel.addSpacing(10)

        profile_group = QGroupBox("Mouse profile")
        pg_layout = QVBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["precision", "balanced", "fast", "crazy"])
        self.profile_combo.setCurrentText(appmod.CURRENT_PROFILE)
        self.profile_combo.currentTextChanged.connect(self.on_profile_changed)
        pg_layout.addWidget(self.profile_combo)

        profile_hint = QLabel(
            "Piliin ang base profile ng mouse feel.\nPwede mo pa i-tweak sa kanan."
        )
        profile_hint.setWordWrap(True)
        pg_layout.addWidget(profile_hint)

        profile_group.setLayout(pg_layout)
        left_panel.addWidget(profile_group)

        left_panel.addStretch()

        main_layout.addLayout(left_panel, 1)

        # Right panel: tabs (Mouse / Keyboard / System)
        tabs = QTabWidget()
        tabs.addTab(self.build_mouse_tab(), "Mouse")
        tabs.addTab(self.build_keyboard_tab(), "Keyboard")
        tabs.addTab(self.build_system_tab(), "Overlay / System")
        main_layout.addWidget(tabs, 2)

    def build_mouse_tab(self):
        """Mouse tab content."""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        group = QGroupBox("Mouse feel")
        form = QFormLayout()

        self.sens_slider = QSlider(Qt.Horizontal)
        self.sens_slider.setMinimum(1)
        self.sens_slider.setMaximum(20)
        self.sens_slider.setValue(int(appmod.SENSITIVITY))
        self.sens_slider.valueChanged.connect(self.on_sens_changed)
        self.sens_value_label = QLabel(f"{appmod.SENSITIVITY:.1f}")
        sens_row = QHBoxLayout()
        sens_row.addWidget(self.sens_slider)
        sens_row.addWidget(self.sens_value_label)
        form.addRow("Sensitivity", sens_row)

        self.smooth_slider = QSlider(Qt.Horizontal)
        self.smooth_slider.setMinimum(0)
        self.smooth_slider.setMaximum(90)
        self.smooth_slider.setValue(int(appmod.SMOOTHING * 100))
        self.smooth_slider.valueChanged.connect(self.on_smooth_changed)
        self.smooth_value_label = QLabel(f"{appmod.SMOOTHING:.2f}")
        smooth_row = QHBoxLayout()
        smooth_row.addWidget(self.smooth_slider)
        smooth_row.addWidget(self.smooth_value_label)
        form.addRow("Smoothing", smooth_row)

        self.deadzone_slider = QSlider(Qt.Horizontal)
        self.deadzone_slider.setMinimum(0)
        self.deadzone_slider.setMaximum(10)
        self.deadzone_slider.setValue(int(appmod.DEADZONE))
        self.deadzone_slider.valueChanged.connect(self.on_deadzone_changed)
        self.deadzone_value_label = QLabel(f"{appmod.DEADZONE}")
        dz_row = QHBoxLayout()
        dz_row.addWidget(self.deadzone_slider)
        dz_row.addWidget(self.deadzone_value_label)
        form.addRow("Deadzone", dz_row)

        group.setLayout(form)
        layout.addWidget(group)

        info = QLabel(
            "Sensitivity: mas mataas = mas mabilis ang cursor.\n"
            "Smoothing: mas mataas = mas smooth pero may delay.\n"
            "Deadzone: laki ng galaw na i-ignore para hindi nanginginig ang cursor."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def build_keyboard_tab(self):
        """Keyboard settings tab."""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        enabled_box = QCheckBox("Enable virtual keyboard control (toggle gesture)")
        enabled_box.setChecked(True)
        enabled_box.setEnabled(False)
        layout.addWidget(enabled_box)

        desc = QLabel(
            "Gamitin ang thumb + ring pinch (hold ~0.3s) para mag-toggle Mouse ↔ Keyboard mode (mas stable kung nakaharap ang palad).\n"
            "Sa keyboard mode, itutok ang index fingertip sa key at gawin ang thumb-index pinch para mag-type (one press per pinch).\n"
            "Speed boosts: thumb+middle pinch = BACKSPACE, thumb+pinky pinch = SHIFT (one-shot).\n"
            "Tip: pwede ang 1 hand o 2 hands (bawat kamay may sariling pointer; may L/R marker sa overlay)."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Legacy flex-tap controls kept for reference (disabled)
        feel_group = QGroupBox("Typing feel (legacy flex-tap settings)")
        fg_layout = QFormLayout()

        self.tap_sens_slider = QSlider(Qt.Horizontal)
        self.tap_sens_slider.setMinimum(50)   # 50%
        self.tap_sens_slider.setMaximum(200)  # 200%
        self.tap_sens_slider.setValue(int(appmod.KEY_TAP_SENSITIVITY * 100))
        self.tap_sens_slider.valueChanged.connect(self.on_tap_sensitivity_changed)
        self.tap_sens_label = QLabel(f"{int(appmod.KEY_TAP_SENSITIVITY*100)}%")
        ts_row = QHBoxLayout()
        ts_row.addWidget(self.tap_sens_slider)
        ts_row.addWidget(self.tap_sens_label)
        fg_layout.addRow("Tap sensitivity", ts_row)

        self.tap_cd_slider = QSlider(Qt.Horizontal)
        self.tap_cd_slider.setMinimum(50)    # 50 ms
        self.tap_cd_slider.setMaximum(300)   # 300 ms
        self.tap_cd_slider.setValue(int(appmod.KEY_TAP_COOLDOWN * 1000))
        self.tap_cd_slider.valueChanged.connect(self.on_tap_cooldown_changed)
        self.tap_cd_label = QLabel(f"{int(appmod.KEY_TAP_COOLDOWN*1000)} ms")
        cd_row = QHBoxLayout()
        cd_row.addWidget(self.tap_cd_slider)
        cd_row.addWidget(self.tap_cd_label)
        fg_layout.addRow("Tap cooldown", cd_row)

        self.thumb_space_checkbox = QCheckBox("Gamitin ang thumb para sa SPACE lang")
        self.thumb_space_checkbox.setChecked(appmod.THUMB_SPACE_ONLY)
        self.thumb_space_checkbox.stateChanged.connect(self.on_thumb_space_only_changed)
        fg_layout.addRow("Thumb rule", self.thumb_space_checkbox)

        feel_group.setLayout(fg_layout)
        feel_group.setEnabled(False)
        layout.addWidget(feel_group)

        info2 = QLabel(
            "Tap sensitivity: mas mataas = mas konting flex ang kailangan bago mag type.\n"
            "Tap cooldown: oras sa pagitan ng taps per finger, mas mababa = mas mabilis mag type.\n"
            "Thumb rule: kapag naka-on, ang thumb ay pumipindot lang ng SPACE."
        )
        info2.setWordWrap(True)
        layout.addWidget(info2)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def build_system_tab(self):
        """Overlay/system settings tab."""
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        selfie_group = QGroupBox("Selfie preview")
        sg_layout = QFormLayout()

        self.selfie_checkbox = QCheckBox("Show selfie preview")
        self.selfie_checkbox.setChecked(True)
        self.selfie_checkbox.stateChanged.connect(self.on_selfie_enabled_changed)
        sg_layout.addRow("Visible", self.selfie_checkbox)

        self.selfie_pos_combo = QComboBox()
        self.selfie_pos_combo.addItem("Top left", "top_left")
        self.selfie_pos_combo.addItem("Top right", "top_right")
        self.selfie_pos_combo.addItem("Bottom left", "bottom_left")
        self.selfie_pos_combo.addItem("Bottom right", "bottom_right")
        self.selfie_pos_combo.setCurrentIndex(0)
        self.selfie_pos_combo.currentIndexChanged.connect(self.on_selfie_position_changed)
        sg_layout.addRow("Position", self.selfie_pos_combo)

        self.selfie_size_slider = QSlider(Qt.Horizontal)
        self.selfie_size_slider.setMinimum(50)   # 50%
        self.selfie_size_slider.setMaximum(150)  # 150%
        self.selfie_size_slider.setValue(100)
        self.selfie_size_slider.valueChanged.connect(self.on_selfie_size_changed)
        self.selfie_size_label = QLabel("100%")
        size_row = QHBoxLayout()
        size_row.addWidget(self.selfie_size_slider)
        size_row.addWidget(self.selfie_size_label)
        sg_layout.addRow("Size", size_row)

        selfie_group.setLayout(sg_layout)
        layout.addWidget(selfie_group)

        lbl = QLabel(
            "System info:\n\n"
            "- Default camera index: 0\n"
            "- Resolution: 640 x 480\n"
            "- Overlay: always on top, transparent sa mouse"
        )
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        about = QLabel(
            "\nHand Controller v0.1\nExperimental build para sa hand-based mouse at keyboard."
        )
        about.setWordWrap(True)
        layout.addWidget(about)

        layout.addStretch()
        tab.setLayout(layout)
        return tab

    # =========================
    # controller control
    # =========================

    @pyqtSlot()
    def toggle_controller(self):
        """Start/Stop controller."""
        if self.controller_running:
            self.stop_controller()
        else:
            self.start_controller()

    def start_controller(self):
        """Start camera + overlay + CV loop.

        Tricky part: threading + signals
            - OverlayWindow is a Qt widget (UI thread).
            - cv_loop runs in a worker thread.
            - Worker thread emits overlay payloads via OverlaySignalBus.
        """
        if self.controller_running:
            return

        # Reset shared mouse state (trackpad-like delta movement uses these)
        appmod.prev_x, appmod.prev_y = appmod.screen_w // 2, appmod.screen_h // 2
        appmod.hand_tracked = False

        # 1) Create overlay window (UI thread)
        self.overlay = OverlayWindow(self.keyboard_keys)
        self.overlay.set_profile(self.profile_combo.currentText())
        self.overlay.set_selfie_config(
            enabled=self.selfie_enabled_cfg,
            scale=self.selfie_scale_cfg,
            position=self.selfie_pos_cfg,
        )

        # 2) Create signal bus and connect it to overlay slot
        # WHY:
        #   Direct overlay.update_state() from worker thread can freeze/crash.
        #   Signals queue the payload and deliver it safely on the UI thread.
        self.overlay_bus = OverlaySignalBus()
        self.overlay_bus.update_overlay.connect(self.overlay.apply_state)

        # 3) Start worker thread
        self.stop_event = threading.Event()
        self.controller_thread = threading.Thread(
            target=self.cv_loop_fn,
            args=(self.overlay_bus, self.stop_event),
            daemon=True,
        )
        self.controller_thread.start()

        self.controller_running = True
        self.update_status("Running", running=True)

    def stop_controller(self):
        """Stop controller thread and close overlay.

        Important cleanup order:
            1) stop_event.set() -> tells cv_loop to exit
            2) join thread (with timeout) to reduce race conditions
            3) disconnect signal bus (avoid queued updates hitting closing overlay)
            4) close overlay window
        """
        if not self.controller_running:
            return

        if self.stop_event is not None:
            self.stop_event.set()

        if self.controller_thread is not None and self.controller_thread.is_alive():
            self.controller_thread.join(timeout=1.0)

        # Disconnect signal bus to avoid queued updates hitting a closing window
        if self.overlay_bus is not None and self.overlay is not None:
            try:
                self.overlay_bus.update_overlay.disconnect(self.overlay.apply_state)
            except Exception:
                pass

        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None
        self.overlay_bus = None

        self.controller_thread = None
        self.stop_event = None
        self.controller_running = False
        self.update_status("Stopped", running=False)

    def update_status(self, text, running):
        """Update status text + button style."""
        self.status_label.setText(f"Status: {text}")
        if running:
            self.status_label.setStyleSheet("color: #55ff55;")
            self.start_button.setText("Stop controller")
            self.start_button.setStyleSheet(
                "background-color: #cc5555; color: white; border-radius: 6px;"
            )
        else:
            self.status_label.setStyleSheet("color: #ff5555;")
            self.start_button.setText("Start controller")
            self.start_button.setStyleSheet(
                "background-color: #55aa55; color: white; border-radius: 6px;"
            )

    def closeEvent(self, event):
        """Ensure controller stopped when closing."""
        self.stop_controller()
        event.accept()

    # =========================
    # handlers para sa UI controls
    # =========================

    @pyqtSlot(str)
    def on_profile_changed(self, name):
        """Apply selected profile.

        Note:
            We update appmod globals so controllers immediately feel the changes.
            Overlay label is updated via overlay.set_profile().
        """
        if name not in appmod.PROFILES:
            return

        appmod.CURRENT_PROFILE = name
        p = appmod.PROFILES[name]
        appmod.SENSITIVITY = p["sens"]
        appmod.SMOOTHING = p["smooth"]
        appmod.DEADZONE = p["deadzone"]

        self.sens_slider.setValue(int(appmod.SENSITIVITY))
        self.sens_value_label.setText(f"{appmod.SENSITIVITY:.1f}")

        self.smooth_slider.setValue(int(appmod.SMOOTHING * 100))
        self.smooth_value_label.setText(f"{appmod.SMOOTHING:.2f}")

        self.deadzone_slider.setValue(int(appmod.DEADZONE))
        self.deadzone_value_label.setText(f"{appmod.DEADZONE}")

        if self.overlay is not None:
            self.overlay.set_profile(name)

    @pyqtSlot(int)
    def on_sens_changed(self, value):
        """Sensitivity slider."""
        appmod.SENSITIVITY = float(value)
        self.sens_value_label.setText(f"{appmod.SENSITIVITY:.1f}")

        if self.overlay is not None:
            self.overlay.set_profile_custom_label()

    @pyqtSlot(int)
    def on_smooth_changed(self, value):
        """Smoothing slider (0..90 -> 0.00..0.90)."""
        appmod.SMOOTHING = value / 100.0
        self.smooth_value_label.setText(f"{appmod.SMOOTHING:.2f}")

        if self.overlay is not None:
            self.overlay.set_profile_custom_label()

    @pyqtSlot(int)
    def on_deadzone_changed(self, value):
        """Deadzone slider."""
        appmod.DEADZONE = int(value)
        self.deadzone_value_label.setText(f"{appmod.DEADZONE}")

        if self.overlay is not None:
            self.overlay.set_profile_custom_label()

    @pyqtSlot(int)
    def on_selfie_enabled_changed(self, state):
        """Toggle selfie visibility."""
        self.selfie_enabled_cfg = (state == Qt.Checked)

        if self.overlay is not None:
            self.overlay.set_selfie_config(enabled=self.selfie_enabled_cfg)

    @pyqtSlot(int)
    def on_selfie_position_changed(self, index):
        """Change selfie corner."""
        data = self.selfie_pos_combo.itemData(index)
        if not data:
            data = "top_left"
        self.selfie_pos_cfg = data

        if self.overlay is not None:
            self.overlay.set_selfie_config(position=self.selfie_pos_cfg)

    @pyqtSlot(int)
    def on_selfie_size_changed(self, value):
        """Change selfie scale (50% - 150%)."""
        self.selfie_scale_cfg = value / 100.0
        self.selfie_size_label.setText(f"{value}%")

        if self.overlay is not None:
            self.overlay.set_selfie_config(scale=self.selfie_scale_cfg)

    @pyqtSlot(int)
    def on_tap_sensitivity_changed(self, value):
        """Tap sensitivity (50% - 200%). (Legacy, disabled)"""
        appmod.KEY_TAP_SENSITIVITY = value / 100.0
        self.tap_sens_label.setText(f"{value}%")

    @pyqtSlot(int)
    def on_tap_cooldown_changed(self, value):
        """Tap cooldown (50 - 300 ms). (Legacy, disabled)"""
        appmod.KEY_TAP_COOLDOWN = value / 1000.0
        self.tap_cd_label.setText(f"{value} ms")

    @pyqtSlot(int)
    def on_thumb_space_only_changed(self, state):
        """Thumb rule toggle. (Legacy, disabled)"""
        appmod.THUMB_SPACE_ONLY = (state == Qt.Checked)
