"""Keyboard Controller — virtual keyboard operations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Set, Optional
import threading
import time


@dataclass
class KeyEvent:
    key: str
    pressed: bool
    timestamp: float


class KeyboardController:
    """Virtual keyboard controller."""

    def __init__(self):
        self._pressed_keys: Set[str] = set()
        self._lock = threading.Lock()
        self._key_history: List[tuple[str, bool, float]] = []

        # Key name mappings
        self._key_map = {
            # Letters
            **{chr(i): chr(i) for i in range(ord('a'), ord('z') + 1)},
            **{chr(i): chr(i) for i in range(ord('A'), ord('Z') + 1)},
            # Numbers
            **{str(i): str(i) for i in range(10)},
            # Special keys
            "enter": "enter",
            "escape": "escape",
            "tab": "tab",
            "backspace": "backspace",
            "delete": "delete",
            "space": "space",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
            "home": "home",
            "end": "end",
            "page_up": "page_up",
            "page_down": "page_down",
            "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4",
            "f5": "f5", "f6": "f6", "f7": "f7", "f8": "f8",
            "f9": "f9", "f10": "f10", "f11": "f11", "f12": "f12",
            # Modifiers
            "ctrl": "ctrl",
            "alt": "alt",
            "shift": "shift",
            "super": "super",
            "meta": "super",
            "cmd": "super",
            "win": "super",
        }

    def _normalize_key(self, key: str) -> str:
        """Normalize key name."""
        return self._key_map.get(key.lower(), key.lower())

    def press(self, key: str) -> bool:
        """Press and hold a key."""
        key = self._normalize_key(key)
        with self._lock:
            if key not in self._pressed_keys:
                self._pressed_keys.add(key)
                self._key_history.append((key, True, time.time()))
        return True

    def release(self, key: str) -> bool:
        """Release a key."""
        key = self._normalize_key(key)
        with self._lock:
            self._pressed_keys.discard(key)
            self._key_history.append((key, False, time.time()))
        return True

    def tap(self, key: str, duration: float = 0.05) -> bool:
        """Tap a key (press and release)."""
        self.press(key)
        time.sleep(duration)
        self.release(key)
        return True

    def type_text(self, text: str, delay: float = 0.01) -> bool:
        """Type a string of text."""
        for char in text:
            self.tap(char)
            time.sleep(delay)
        return True

    def hotkey(self, *keys: str) -> bool:
        """Press a combination of keys (e.g., ctrl+c)."""
        normalized = [self._normalize_key(k) for k in keys]
        for key in normalized:
            self.press(key)
        time.sleep(0.05)
        for key in reversed(normalized):
            self.release(key)
        return True

    def is_pressed(self, key: str) -> bool:
        """Check if a key is currently pressed."""
        with self._lock:
            return self._normalize_key(key) in self._pressed_keys

    def release_all(self):
        """Release all pressed keys."""
        with self._lock:
            for key in list(self._pressed_keys):
                self.release(key)

    def get_pressed_keys(self) -> Set[str]:
        """Get currently pressed keys."""
        with self._lock:
            return set(self._pressed_keys)

    def get_history(self, limit: int = 100) -> List[tuple]:
        """Get key press history."""
        with self._lock:
            return self._key_history[-limit:]


import threading
from typing import List, Set
import time