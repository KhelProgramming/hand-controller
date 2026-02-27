"""hand_controller.controllers.actions

PURPOSE:
    Dito naka-define ang mga "Action" objects.

    Action = "desisyon" lang (ano ang gagawin), pero *hindi* dito ginagawa ang actual
    side effects (mouse move / click / typing). Ang actual execution ay nasa
    controllers/action_executor.py.

WHY NEEDED:
    Sa original one-file app, halo-halo ang logic at pyautogui calls.
    Problem nun:
      - mahirap i-test (kasi gagalaw talaga mouse mo kapag nag-run ka)
      - mahirap i-maintain (kasi scattered ang side effects)
      - mahirap isingit ang ML (kasi gusto natin output lang ng ML = decision)

    Sa architecture natin ngayon:
      - controllers/*  => "decide" (produce Action list)
      - action_executor => "do" (perform pyautogui)

HOW TO READ:
    Think of Actions as "commands".
      - MoveTo(x,y)            => galawin cursor
      - Click(button)          => left/right click
      - DoubleClick()          => double-click
      - KeyPress(key)          => press a key (like 'a', 'space', 'backspace')
      - Hotkey(keys=(...))     => press a key combo (like Shift+A)

USED BY:
    - controllers/mouse_controller.py (MoveTo, Click, DoubleClick)
    - controllers/keyboard_controller.py (KeyPress, Hotkey)
    - controllers/action_executor.py (reads Action objects and calls pyautogui)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple, Union


@dataclass(frozen=True, slots=True)
class MoveTo:
    """Move mouse cursor to a screen coordinate.

    Taglish meaning:
        "I-move mo ang cursor sa (x, y) sa screen".

    Notes:
        - x/y are screen pixels (0..screen_w-1, 0..screen_h-1)
        - Actual pyautogui.moveTo happens in action_executor.
    """

    x: int
    y: int


@dataclass(frozen=True, slots=True)
class Click:
    """Single click action.

    Taglish meaning:
        "Mag-click once" (left by default).

    button:
        - "left" or "right"

    Notes:
        - Actual click happens in action_executor.
        - Controllers decide *when* to click; executor decides *how* to call pyautogui.
    """

    button: Literal["left", "right"] = "left"


@dataclass(frozen=True, slots=True)
class DoubleClick:
    """Double click action (left only).

    Taglish meaning:
        "Mag-double click".

    Notes:
        - In our app, double click is used sa mouse mode kapag mabilis na
          dalawang left pinch in a short interval.
    """

    button: Literal["left"] = "left"


@dataclass(frozen=True, slots=True)
class KeyPress:
    """Press a single key.

    Taglish meaning:
        "Pindutin ang key".

    key:
        - should be in pyautogui.press compatible form
          examples: 'a', 'space', 'enter', 'backspace'

    Notes:
        - For letters, we usually pass lower-case.
        - For shifted letters, we use Hotkey(('shift', 'a')).
    """

    key: str


@dataclass(frozen=True, slots=True)
class Hotkey:
    """Press a hotkey chord.

    Example:
        Hotkey(keys=('shift', 'a'))  -> uppercase 'A'

    Taglish meaning:
        "Pindutin sabay" (combo keys).

    Notes:
        - This maps to pyautogui.hotkey(*keys)
        - We use this for one-shot Shift behavior in keyboard mode.
    """

    keys: Tuple[str, ...]


# Union type used across the app.
# Controllers return: List[Action]
Action = Union[MoveTo, Click, DoubleClick, KeyPress, Hotkey]
