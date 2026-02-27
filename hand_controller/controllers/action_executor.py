"""hand_controller/controllers/action_executor.py (CORE FILE)

PURPOSE:
  Ito lang dapat ang file na may direct calls sa `pyautogui.*`.
  Think of this as "bridge" between:
    - PURE LOGIC (controllers)  -> outputs Action objects
    - REAL SIDE EFFECTS (OS)    -> mouse move/click/type

WHY WE NEED THIS LAYER:
  1) Clean architecture:
       controller decides WHAT to do
       executor decides HOW to do it

  2) Debugging becomes easier:
       If controller returns correct actions but nothing happens,
       executor is the place to check.

  3) Testing becomes possible:
       You can unit-test controllers without moving your real mouse.

TEST NOTE:
  - We import pyautogui lazily inside execute_actions().
  - Reason: sa test, pyautogui may fail to init display.
"""

from __future__ import annotations

from typing import Iterable

from .actions import Action, MoveTo, Click, DoubleClick, KeyPress, Hotkey


def execute_actions(actions: Iterable[Action]) -> None:
    """Execute actions in order.

    Inputs:
      actions: iterable of Action objects.
        Examples:
          - MoveTo(x, y)
          - Click(button="left")
          - DoubleClick()
          - KeyPress("a")
          - Hotkey(["shift", "a"])  -> sends Shift+A

    Side effects:
      - Actual OS mouse movement
      - Actual OS clicks
      - Actual OS keypresses

    Important rule in this project:
      - Controllers should NOT call pyautogui directly.
      - Always return Actions, then pass here.
    """
    # Lazy import so importing controller modules doesn't require an active display.
    import pyautogui

    # Keep consistent behavior with original code
    pyautogui.FAILSAFE = False

    for act in actions:
        if isinstance(act, MoveTo):
            pyautogui.moveTo(act.x, act.y)
        elif isinstance(act, DoubleClick):
            pyautogui.doubleClick()
        elif isinstance(act, Click):
            pyautogui.click(button=act.button)
        elif isinstance(act, KeyPress):
            pyautogui.press(act.key)
        elif isinstance(act, Hotkey):
            # pyautogui.hotkey presses keys in order, then releases in reverse.
            pyautogui.hotkey(*act.keys)
        else:
            # defensive: ignore unknown actions
            continue
