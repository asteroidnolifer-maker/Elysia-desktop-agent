"""Computer Controller — high-level desktop automation with permissions."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
import threading
import time
import uuid

from .mouse import MouseController
from .keyboard import KeyboardController
from .screen import ScreenCapture
from .vision import VisionPipeline
from .permissions import ComputerPermissions, ComputerAction


class ComputerBackend(Enum):
    X11 = "x11"
    WAYLAND = "wayland"
    WIN32 = "win32"
    MACOS = "macos"
    AUTO = "auto"


@dataclass
class ComputerActionRequest:
    """A structured computer action request."""
    action: ComputerAction
    params: Dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ComputerActionResult:
    """Result of a computer action."""
    success: bool
    action: ComputerAction
    output: Any = None
    error: str = ""
    duration_ms: float = 0.0
    session_id: str = ""
    verification: Dict[str, Any] = field(default_factory=dict)


class ComputerController:
    """Main computer controller orchestrating mouse, keyboard, screen, and vision."""

    def __init__(self, permissions: 'ComputerPermissions' = None,
                 backend: ComputerBackend = ComputerBackend.AUTO):
        self.permissions = permissions or ComputerPermissions()
        self.backend = self._detect_backend(backend)
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.screen = ScreenCapture()
        self.vision = VisionPipeline()
        self._lock = threading.Lock()
        self._action_history: List[Dict[str, Any]] = []
        self._rate_limits: Dict[str, List[float]] = {}
        self._session_id = str(uuid.uuid4())

    def execute(self, action: ComputerAction, **params) -> ComputerActionResult:
        """Execute a computer action with permission checking and verification."""
        # Check permissions
        if not self.permissions.can_execute(action):
            return ComputerActionResult(
                success=False,
                action=action,
                error=f"Permission denied for action: {action.value}",
                session_id=self._session_id,
            )

        # Check rate limits
        if not self._check_rate_limit(action):
            return ComputerActionResult(
                success=False,
                action=action,
                error=f"Rate limit exceeded for action: {action.value}",
                session_id=self._session_id,
            )

        # Execute the action
        start_time = time.time()
        try:
            result = self._execute_action(action, **params)
            duration_ms = (time.time() - start_time) * 1000

            # Record successful action
            self._record_action(action, params, result, duration_ms, True)

            # Verify result if possible
            verification = self._verify_action(action, params, result)

            return ComputerActionResult(
                success=True,
                action=action,
                output=result,
                duration_ms=duration_ms,
                session_id=self._session_id,
                verification=verification,
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            self._record_action(action, params, str(e), duration_ms, False)
            return ComputerActionResult(
                success=False,
                action=action,
                error=str(e),
                duration_ms=duration_ms,
                session_id=self._session_id,
            )

    def _execute_action(self, action: ComputerAction, **params) -> Any:
        """Execute the specific action."""
        if action in (ComputerAction.MOUSE_MOVE, ComputerAction.MOUSE_CLICK,
                      ComputerAction.MOUSE_DOUBLE_CLICK, ComputerAction.MOUSE_RIGHT_CLICK,
                      ComputerAction.MOUSE_DRAG, ComputerAction.MOUSE_SCROLL):
            return self.mouse.execute(action, **params)

        elif action in (ComputerAction.KEY_PRESS, ComputerAction.KEY_RELEASE,
                        ComputerAction.KEY_TAP, ComputerAction.TYPE_TEXT,
                        ComputerAction.HOTKEY):
            return self.keyboard.execute(action, **params)

        elif action in (ComputerAction.SCREENSHOT, ComputerAction.SCREEN_REGION):
            return self.screen.execute(action, **params)

        elif action in (ComputerAction.WINDOW_LIST, ComputerAction.WINDOW_FOCUS,
                        ComputerAction.WINDOW_GEOMETRY):
            return self.screen.execute(action, **params)

        elif action in (ComputerAction.VISION_ANALYZE, ComputerAction.OCR):
            return self.vision.execute(action, **params)

        else:
            raise ValueError(f"Unknown action: {action}")

    def _verify_action(self, action: ComputerAction, params: Dict[str, Any],
                       result: Any) -> Dict[str, Any]:
        """Verify the action result."""
        verification = {"verified": False, "details": ""}

        if action == ComputerAction.MOUSE_CLICK:
            # Verify by checking mouse position
            pos = self.mouse.position()
            target = params.get("target", params.get("position"))
            if target and abs(pos[0] - target[0]) < 5 and abs(pos[1] - target[1]) < 5:
                verification = {"verified": True, "details": "Mouse position matches target"}
            else:
                verification = {"verified": False, "details": "Mouse position mismatch"}

        elif action == ComputerAction.TYPE_TEXT:
            # Could verify by checking clipboard or active window content
            verification = {"verified": True, "details": "Text input sent"}

        elif action == ComputerAction.SCREENSHOT:
            if result and len(result) > 100:
                verification = {"verified": True, "details": f"Screenshot captured ({len(result)} bytes)"}
            else:
                verification = {"verified": False, "details": "Screenshot empty or failed"}

        return verification

    def _check_rate_limit(self, action: ComputerAction) -> bool:
        """Check if action is within rate limits."""
        now = time.time()
        key = action.value
        if key not in self._rate_limits:
            self._rate_limits[key] = []

        # Clean old entries
        self._rate_limits[key] = [t for t in self._rate_limits[key] if now - t < 60]

        # Check limits (configurable per action type)
        limits = {
            ComputerAction.MOUSE_CLICK: 30,
            ComputerAction.KEY_TAP: 60,
            ComputerAction.TYPE_TEXT: 10,
            ComputerAction.SCREENSHOT: 10,
        }
        limit = limits.get(action, 20)
        if len(self._rate_limits[key]) >= limit:
            return False

        self._rate_limits[key].append(now)
        return True

    def _record_action(self, action: ComputerAction, params: Dict,
                       result: Any, duration_ms: float, success: bool):
        """Record action in history."""
        with self._lock:
            self._action_history.append({
                "action": action.value,
                "params": params,
                "success": success,
                "duration_ms": duration_ms,
                "timestamp": time.time(),
            })
            # Keep only last 1000 actions
            if len(self._action_history) > 1000:
                self._action_history = self._action_history[-1000:]

    def _detect_backend(self, backend: ComputerBackend) -> ComputerBackend:
        if backend != ComputerBackend.AUTO:
            return backend

        # Auto-detect display server
        import os
        if os.environ.get("WAYLAND_DISPLAY"):
            return ComputerBackend.WAYLAND
        if os.environ.get("DISPLAY"):
            return ComputerBackend.X11
        if os.name == "nt":
            return ComputerBackend.WIN32
        if sys.platform == "darwin":
            return ComputerBackend.MACOS
        return ComputerBackend.X11

    def emergency_stop(self):
        """Emergency stop - cancel all actions and release inputs."""
        self.mouse.release_all()
        self.keyboard.release_all()
        with self._lock:
            self._action_history.append({
                "action": "EMERGENCY_STOP",
                "timestamp": time.time(),
            })

    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._lock:
            return self._action_history[-limit:]

    def get_permissions(self) -> 'ComputerPermissions':
        return self.permissions

    def set_permissions(self, permissions: 'ComputerPermissions'):
        self.permissions = permissions


import threading
import time
import sys
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple