"""Mouse Controller — virtual mouse operations."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Tuple, Optional
import time


class MouseButton(Enum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"
    X1 = "x1"
    X2 = "x2"


@dataclass
class MousePosition:
    x: int
    y: int


class MouseController:
    """Virtual mouse controller."""

    def __init__(self):
        self._position = (0, 0)
        self._pressed_buttons = set()
        self._lock = threading.Lock()

    def position(self) -> Tuple[int, int]:
        """Get current mouse position."""
        with self._lock:
            return self._position

    def move(self, x: int, y: int, duration: float = 0.0) -> bool:
        """Move mouse to absolute position."""
        with self._lock:
            if duration > 0:
                # Smooth move
                steps = max(1, int(duration * 60))
                start_x, start_y = self._position
                dx = (x - start_x) / steps
                dy = (y - start_y) / steps
                for i in range(steps):
                    self._position = (int(start_x + dx * i), int(start_y + dy * i))
                    time.sleep(duration / steps)
            self._position = (x, y)
        return True

    def move_relative(self, dx: int, dy: int) -> bool:
        """Move mouse relative to current position."""
        x, y = self.position()
        return self.move(x + dx, y + dy)

    def click(self, x: int = None, y: int = None,
              button: str = "left", count: int = 1) -> bool:
        """Click at position (or current position if not specified)."""
        if x is not None and y is not None:
            self.move(x, y)

        with self._lock:
            for _ in range(count):
                self._pressed_buttons.add(button)
                time.sleep(0.01)
                self._pressed_buttons.discard(button)
        return True

    def double_click(self, x: int = None, y: int = None,
                     button: str = "left") -> bool:
        """Double click at position."""
        return self.click(x, y, button, count=2)

    def right_click(self, x: int = None, y: int = None) -> bool:
        """Right click at position."""
        return self.click(x, y, "right")

    def press(self, button: str = "left") -> bool:
        """Press and hold mouse button."""
        with self._lock:
            self._pressed_buttons.add(button)
        return True

    def release(self, button: str = "left") -> bool:
        """Release mouse button."""
        with self._lock:
            self._pressed_buttons.discard(button)
        return True

    def drag(self, x1: int, y1: int, x2: int, y2: int,
             button: str = "left", duration: float = 0.5) -> bool:
        """Drag from (x1,y1) to (x2,y2)."""
        self.move(x1, y1)
        self.press(button)
        self.move(x2, y2, duration)
        self.release(button)
        return True

    def scroll(self, dx: int = 0, dy: int = 0) -> bool:
        """Scroll mouse wheel."""
        return True

    def release_all(self):
        """Release all pressed buttons."""
        with self._lock:
            self._pressed_buttons.clear()


import threading