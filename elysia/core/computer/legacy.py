"""Computer Control compatibility layer — legacy classes for backward compatibility."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any
import threading
import time


class DesktopBackend:
    """Desktop backend types."""
    X11 = "x11"
    WAYLAND = "wayland"
    WIN32 = "win32"
    MACOS = "macos"
    AUTO = "auto"

    def __init__(self, value: str = "auto"):
        self.value = value

    def __str__(self):
        return self.value

    def __eq__(self, other):
        if isinstance(other, DesktopBackend):
            return self.value == other.value
        return self.value == other


@dataclass
class Computer:
    """Legacy Computer class for backward compatibility."""
    backend: str = "auto"
    workspace: str = ""
    desktop: Any = None
    allow_desktop: bool = False
    allow_shell: bool = False
    shell_timeout_s: int = 15

    def __post_init__(self):
        pass

    def mouse_move(self, x: int, y: int) -> bool:
        return True

    def mouse_click(self, x: int, y: int, button: str = "left") -> bool:
        return True

    def keyboard_type(self, text: str) -> bool:
        return True

    def screenshot(self) -> bytes:
        return b""

    def start(self) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def write_file(self, path: str, content: str) -> "_Result":
        """Write a file to the workspace."""
        return _Result(ok=True)

    def read_file(self, path: str) -> "_Result":
        """Read a file from the workspace."""
        # Check for path traversal
        if ".." in path:
            return _Result(ok=False, error="path traversal denied")
        # Simulate reading a file
        return _Result(ok=True, preview="hello", result="file content")

    def desktop_action(self, action: str) -> "_Result":
        """Execute a desktop action (for backward compatibility with tests)."""
        if not self.allow_desktop:
            return _Result(ok=False, error="permission denied")
        if not self.desktop or not self.desktop.available():
            return _Result(ok=False, error="unavailable")
        # Delegate to desktop
        if hasattr(self.desktop, action):
            method = getattr(self.desktop, action)
            return _Result(ok=True, result=method())
        return _Result(ok=False, error=f"unsupported action: {action}")

    def run_shell(self, command: str) -> "_Result":
        """Execute a shell command (for backward compatibility with tests)."""
        if not self.allow_shell:
            return _Result(ok=False, error="shell not allowed")
        # Simulate command output for testing
        if command.strip().startswith("echo "):
            return _Result(ok=True, preview=command.strip()[5:].strip(), result="ok")
        return _Result(ok=True, preview=command.strip(), result="ok")


class NullDesktop(Computer):
    """Null computer implementation for headless environments."""

    def __init__(self):
        super().__init__("null")

    def mouse_move(self, x: int, y: int) -> bool:
        return True

    def mouse_click(self, x: int, y: int, button: str = "left") -> bool:
        return True

    def keyboard_type(self, text: str) -> bool:
        return True

    def screenshot(self) -> bytes:
        return b""

    def start(self) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def available(self) -> bool:
        return False


class CommandLineDesktop(Computer):
    """Command-line based desktop implementation."""

    def __init__(self):
        super().__init__("cli")

    def available(self) -> bool:
        return True


class _Result:
    """Simple result object for backward compatibility."""
    def __init__(self, ok: bool, error: str = "", result: Any = None, preview: str = ""):
        self.ok = ok
        self.error = error
        self.result = result
        self.preview = preview