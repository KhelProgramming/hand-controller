"""hand_controller/app.py

GOAL NG FILE:
  Ito ang "main glue" ng buong project. Dito nagtatagpo ang:
    - Camera (OpenCV)
    - Hand tracking (MediaPipe via HandTracker)
    - Gesture recognition (RuleBasedGestureRecognizer ngayon; ML later)
    - Mode switching (ModeManager: mouse <-> keyboard)
    - Controllers (mouse_controller / keyboard_controller)
    - Action execution (pyautogui) + Overlay updates (Qt signals)

MENTAL MODEL (end-to-end flow per frame):
  1) Read frame from camera
  2) Mirror frame (selfie feel)
  3) Track hands -> get landmarks + handedness
  4) Recognize gestures (pinch/palm/open, etc.)
  5) Update mode (mouse or keyboard) using ModeManager
  6) Run the correct controller (mouse_controller OR keyboard_controller)
  7) Controller returns "actions" (MoveTo/Click/KeyPress...)
  8) action_executor executes those actions via pyautogui
  9) Build overlay payload (selfie, skeleton, highlights)
 10) Emit overlay payload using Qt signal bus (thread-safe)

IMPORTANT NOTE ABOUT THREADS:
  - 'cv_loop()' runs in a background thread (worker thread).
  - PyQt UI (OverlayWindow paint) should run in the UI thread.
  - So we DO NOT call overlay.update_state() directly from cv thread.
    Instead, we emit a signal (overlay_bus.update_overlay.emit(payload)).

COORDINATE SPACES:
  - MediaPipe landmarks are NORMALIZED coords (x,y in [0..1])
  - For drawing overlay, we convert normalized -> SCREEN pixels
    using frame_to_screen_xy(..., screen_w, screen_h)
  - For pinch distances, we usually use FRAME pixels (640x480)

"""

import sys
import time

import cv2
from .vision import Camera, HandTracker
from .core.coords import frame_to_screen_xy
from .gestures import RuleBasedGestureRecognizer


from .controllers import (
    execute_actions,
    MouseSettings,
    MouseState,
    update_mouse_mode,
    KeyboardSettings,
    KeyboardState,
    create_keyboard_layout_screen,
    update_keyboard_mode,
    ModeManager,
    ModeSettings,
)


# =========================
# config ng app
# =========================

FRAME_WIDTH, FRAME_HEIGHT = 640, 480

# preset profiles para sa mouse feel
PROFILES = {
    "precision": {"sens": 4.0, "smooth": 0.65, "deadzone": 4},
    "balanced": {"sens": 8.0, "smooth": 0.5, "deadzone": 3},
    "fast": {"sens": 12.0, "smooth": 0.4, "deadzone": 2},
    "crazy": {"sens": 16.0, "smooth": 0.32, "deadzone": 1},
}

CURRENT_PROFILE = "fast"

# active mouse parameters (nagbabago kapag nagpalit ng profile o sliders)
SENSITIVITY = PROFILES[CURRENT_PROFILE]["sens"]
SMOOTHING = PROFILES[CURRENT_PROFILE]["smooth"]
DEADZONE = PROFILES[CURRENT_PROFILE]["deadzone"]

CLICK_COOLDOWN = 0.25
DOUBLE_CLICK_INTERVAL = 0.4
PINCH_THRESHOLD = 35

# config ng keyboard overlay
KEYBOARD_HEIGHT_RATIO = 0.50   # fraction ng screen height para sa keyboard panel
KEYBOARD_SIDE_MARGIN = 100
KEY_FONT_SIZE = 18

# config ng pointer circles
FINGER_RADIUS = 8

# base size ng selfie preview (scalable)
SELFIE_WIDTH = 320
SELFIE_HEIGHT = 240

# config ng tap gesture (keyboard mode)
TAP_COOLDOWN_DEFAULT = 0.15   # default cooldown per finger bago payagan ulit ang tap (seconds)

# global keyboard feel
KEY_TAP_SENSITIVITY = 1.0     # 1.0 = normal, >1 = mas madali mag trigger, <1 = mas matigas
KEY_TAP_COOLDOWN = TAP_COOLDOWN_DEFAULT
THUMB_SPACE_ONLY = True       # kung True, thumb pang SPACE lang

# threshold ng flex per finger (pixels sa screen, rel_y)
FINGER_TAP_THRESHOLDS = {
    "thumb": 8.0,
    "index": 12.0,
    "middle": 12.0,
    "ring": 12.0,
    "pinky": 10.0,
}


# pyautogui is initialized lazily to support headless test environments.
screen_w, screen_h = 1920, 1080

def init_pyautogui():
    """Initialize pyautogui and screen size (call from UI/main thread).

    Why we do this here (instead of importing pyautogui at module import time)?
      - Some environments (tests)  walang active display.
      - If pyautogui tries to initialize too early, pwedeng mag-error.

    What this does:
      - turns off FAILSAFE (para di mag-stop kapag napunta cursor sa corner)
      - reads actual monitor size (screen_w, screen_h)
    """
    global screen_w, screen_h
    import pyautogui
    pyautogui.FAILSAFE = False
    screen_w, screen_h = pyautogui.size()

# These are still kept for compatibility 
# which resets them on Start. The runtime controllers ang humahawak ng real state
prev_x, prev_y = screen_w // 2, screen_h // 2
hand_tracked = False
prev_hand_x = None
prev_hand_y = None

# keyboard layout ay built once in main()
keyboard_keys = []


# =========================
# cv thread function
# =========================


def cv_loop(overlay_bus, stop_event):
    """Main loop (worker thread): camera -> hand tracker -> controllers -> actions -> overlay.

    GOAL:
      Tumatakbo habang hindi pa naka-set ang stop_event.
      Bawat frame, ia-apply ang hand tracking + gesture logic + controller logic.

    INPUTS:
      overlay_bus:
        Object na may Qt signal `update_overlay`. Dito tayo nag-eemit ng payload.
        UI thread ang tatanggap at magdo-draw.

      stop_event:
        threading.Event. Kapag set -> hihinto ang while loop.
    """
    global keyboard_keys

    cam = Camera(index=0, width=FRAME_WIDTH, height=FRAME_HEIGHT)
    tracker = HandTracker(max_num_hands=2, min_detection_confidence=0.7, min_tracking_confidence=0.7)
    recognizer = RuleBasedGestureRecognizer()

    # Mode state machine (uses defaults from hand_controller/config/tuning.py)
    mode_manager = ModeManager(settings=ModeSettings())

    # ------------------------------------------------------------
    # Runtime states (persist across frames)
    # ------------------------------------------------------------
    # MouseState/KeyboardState = memory ng app habang tumatakbo.
    # Bakit kailangan?
    #   - para sa mouse smoothing, kailangan natin maalala prev_x/prev_y.
    #   - para sa trackpad style movement, kailangan natin maalala prev_hand_x/prev_hand_y.
    #   - para sa keyboard, may shift-one-shot at per-hand pinch state.
    mouse_state = MouseState(prev_x=prev_x, prev_y=prev_y, hand_tracked=hand_tracked, prev_hand_x=prev_hand_x, prev_hand_y=prev_hand_y)
    keyboard_state = KeyboardState()

    while not stop_event.is_set():
        # ------------------------------------------------------------
        # Step 1) Read a frame from the camera
        # ------------------------------------------------------------
        # 'ret' = success flag, 'frame' = actual image (BGR format by OpenCV).
        ret, frame = cam.read()
        if not ret:
            break

        # ------------------------------------------------------------
        # Step 2) Mirror the frame (para maging selfie)
        # ------------------------------------------------------------
        frame = cv2.flip(frame, 1)

        # ------------------------------------------------------------
        # Step 3) Convert BGR -> RGB for MediaPipe
        # ------------------------------------------------------------
        # MediaPipe expects RGB, pero si OpenCV default BGR.
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = tracker.process(rgb_frame)
        now = time.time()

        # ------------------------------------------------------------
        # Step 4) Extract hands into a stable, simple structure
        # ------------------------------------------------------------
        # hands_list is a list of dicts:
        #   {"label": "Left"/"Right", "landmarks": <mp hand landmarks>}
        hands_list = tracker.extract_hands(result)

        # ------------------------------------------------------------
        # Step 5) Recognize gestures
        # ------------------------------------------------------------
        gesture_results = recognizer.recognize(
            hands_list=hands_list,
            frame_w=FRAME_WIDTH,
            frame_h=FRAME_HEIGHT,
            pinch_threshold=PINCH_THRESHOLD,
        )

        # ------------------------------------------------------------
        # Step 6) Update current mode (mouse <-> keyboard)
        # ------------------------------------------------------------
        mode, _toggled = mode_manager.update(gesture_results=gesture_results, now=now)
        keyboard_visible = (mode == "keyboard")

        highlight_labels = set()
        finger_points = []
        skeleton_lines = []
        mouse_status = ""
        keyboard_status = ""

        # ------------------------------------------------------------
        # Step 7) Controllers -> Actions
        # ------------------------------------------------------------
        #   Controllers do not directly call pyautogui.
        #   They return a list of Action objects.
        # Then action_executor executes those actions.
        if mode == "mouse":
            # ensure keyboard prev-rel is cleared when leaving keyboard mode
            keyboard_state.reset_prev_rel_only()

            mouse_settings = MouseSettings(
                sensitivity=SENSITIVITY,
                smoothing=SMOOTHING,
                deadzone=DEADZONE,
                click_cooldown=CLICK_COOLDOWN,
                double_click_interval=DOUBLE_CLICK_INTERVAL,
                pinch_threshold=PINCH_THRESHOLD,
            )

            actions, mouse_status = update_mouse_mode(
                hands_list=hands_list,
                frame_w=FRAME_WIDTH,
                frame_h=FRAME_HEIGHT,
                screen_w=screen_w,
                screen_h=screen_h,
                settings=mouse_settings,
                state=mouse_state,
                now=now,
                recognizer=recognizer,
            )
            execute_actions(actions)
        else:
            # match original behavior: disable mouse tracking when in keyboard mode
            mouse_state.hand_tracked = False

            keyboard_settings = KeyboardSettings(
                key_tap_sensitivity=KEY_TAP_SENSITIVITY,
                key_tap_cooldown=KEY_TAP_COOLDOWN,
                thumb_space_only=THUMB_SPACE_ONLY,
                finger_tap_thresholds=FINGER_TAP_THRESHOLDS,
            )

            actions, highlight_labels, finger_points, hovered_key_by_hand = update_keyboard_mode(
                keys=keyboard_keys,
                hands_list=hands_list,
                screen_w=screen_w,
                screen_h=screen_h,
                settings=keyboard_settings,
                state=keyboard_state,
                now=now,
                gesture_results=gesture_results,
            )
            execute_actions(actions)

            # small visual cue about which key each hand is hovering.
            left_lbl = hovered_key_by_hand.get("Left") if hovered_key_by_hand else None
            right_lbl = hovered_key_by_hand.get("Right") if hovered_key_by_hand else None
            parts = []
            if getattr(keyboard_state, "shift_one_shot", False):
                parts.append("SHIFT")
            if left_lbl:
                parts.append(f"L:{left_lbl}")
            if right_lbl:
                parts.append(f"R:{right_lbl}")
            keyboard_status = "  ".join(parts)

        # ------------------------------------------------------------
        # Step 8) Overlay visuals payload
        # ------------------------------------------------------------
        # OverlayWindow ay "renderer" lang.
        # It shows:
        #   - skeleton lines (always)
        #   - finger pointers / highlighted keys (keyboard mode)
        #   - selfie preview
        #   - mode + status text
        for h in hands_list:
            lm = h["landmarks"]
            for conn in tracker.connections:
                start_idx, end_idx = conn
                sx = lm.landmark[start_idx].x
                sy = lm.landmark[start_idx].y
                ex = lm.landmark[end_idx].x
                ey = lm.landmark[end_idx].y
                x1, y1 = frame_to_screen_xy(sx, sy, screen_w, screen_h)
                x2, y2 = frame_to_screen_xy(ex, ey, screen_w, screen_h)
                skeleton_lines.append((x1, y1, x2, y2))

        selfie = cv2.resize(frame, (SELFIE_WIDTH, SELFIE_HEIGHT))

        payload = {
            "mode": mode,
            "keyboard_visible": keyboard_visible,
            "highlight_labels": highlight_labels,
            "finger_points": finger_points,
            "skeleton_lines": skeleton_lines,
            "selfie_frame": selfie,
            "mouse_status": mouse_status,
            "keyboard_status": keyboard_status,
        }
        # Emit through a Qt signal bus to update the overlay in the UI thread.
        if overlay_bus is not None:
            try:
                overlay_bus.update_overlay.emit(payload)
            except Exception:
                pass

    # ------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------
    # para next run ay magopen properly ang camera
    cam.release()
    tracker.close()


# =========================
# main entry
# =========================


def main():
    global keyboard_keys

    # local ui imports para maiwasan ang dobleng 
    from PyQt5.QtWidgets import QApplication
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv)

    # Call init_pyautogui() in the UI/main thread.
    #   - gets real screen size for overlay + controllers
    #   - avoids early pyautogui initialization issues
    init_pyautogui()

    keyboard_keys = create_keyboard_layout_screen(
        screen_w,
        screen_h,
        height_ratio=KEYBOARD_HEIGHT_RATIO,
        side_margin=KEYBOARD_SIDE_MARGIN,
    )

    window = MainWindow(keyboard_keys, cv_loop)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
