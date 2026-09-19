"""Computer Control Permissions — fine-grained action authorization."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set, Optional


class ComputerAction(Enum):
    """All possible computer control actions."""
    # Mouse actions
    MOUSE_MOVE = "mouse_move"
    MOUSE_CLICK = "mouse_click"
    MOUSE_RIGHT_CLICK = "mouse_right_click"
    MOUSE_DOUBLE_CLICK = "mouse_double_click"
    MOUSE_DRAG = "mouse_drag"
    MOUSE_SCROLL = "mouse_scroll"
    MOUSE_POSITION = "mouse_position"

    # Keyboard actions
    KEY_PRESS = "key_press"
    KEY_RELEASE = "key_release"
    KEY_TAP = "key_tap"
    TYPE_TEXT = "type_text"
    HOTKEY = "hotkey"

    # Screen actions
    SCREENSHOT = "screenshot"
    SCREEN_REGION = "screen_region"
    SCREEN_SIZE = "screen_size"
    WINDOW_LIST = "window_list"
    WINDOW_FOCUS = "window_focus"
    WINDOW_GEOMETRY = "window_geometry"

    # Vision actions
    VISION_ANALYZE = "vision_analyze"
    OCR = "ocr"

    # Clipboard
    CLIPBOARD_READ = "clipboard_read"
    CLIPBOARD_WRITE = "clipboard_write"

    # File/Application actions
    APP_LAUNCH = "app_launch"
    FILE_OPEN = "file_open"
    FILE_WRITE = "file_write"


class PermissionLevel(Enum):
    """Permission levels for computer actions."""
    DENIED = "denied"
    PROMPT = "prompt"  # Ask user each time
    ALLOWED = "allowed"  # Allow without prompt
    ALWAYS = "always"  # Always allow, no logging


@dataclass
class ActionPermission:
    """Permission configuration for a specific action."""
    action: 'ComputerAction'
    level: PermissionLevel = PermissionLevel.PROMPT
    conditions: Dict[str, Any] = field(default_factory=dict)  # e.g., {"max_chars": 1000}


class ComputerPermissions:
    """Manages permissions for computer control actions."""

    def __init__(self):
        self._permissions: Dict[ComputerAction, ActionPermission] = {}
        self._default_level = PermissionLevel.PROMPT

        # Initialize default permissions
        self._init_defaults()

    def _init_defaults(self):
        """Set up default permissions."""
        # Observational actions - allowed by default
        for action in [
            ComputerAction.MOUSE_POSITION,
            ComputerAction.MOUSE_MOVE,
            ComputerAction.SCREEN_SIZE,
            ComputerAction.WINDOW_LIST,
            ComputerAction.SCREENSHOT,
            ComputerAction.SCREEN_REGION,
        ]:
            self._permissions[action] = ActionPermission(action, PermissionLevel.ALLOWED)

        # Click actions - prompt by default
        for action in [
            ComputerAction.MOUSE_CLICK,
            ComputerAction.MOUSE_RIGHT_CLICK,
            ComputerAction.MOUSE_DOUBLE_CLICK,
            ComputerAction.MOUSE_DRAG,
            ComputerAction.MOUSE_SCROLL,
        ]:
            self._permissions[action] = ActionPermission(action, PermissionLevel.PROMPT)

        # Keyboard - prompt by default
        for action in [
            ComputerAction.KEY_PRESS,
            ComputerAction.KEY_RELEASE,
            ComputerAction.KEY_TAP,
            ComputerAction.TYPE_TEXT,
            ComputerAction.HOTKEY,
        ]:
            self._permissions[action] = ActionPermission(action, PermissionLevel.PROMPT)

        # Window control - prompt
        for action in [
            ComputerAction.WINDOW_FOCUS,
            ComputerAction.WINDOW_GEOMETRY,
            ComputerAction.WINDOW_LIST,
        ]:
            self._permissions[action] = ActionPermission(action, PermissionLevel.PROMPT)

        # Vision - allowed
        for action in [ComputerAction.VISION_ANALYZE, ComputerAction.OCR]:
            self._permissions[action] = ActionPermission(action, PermissionLevel.ALLOWED)

        # Clipboard - prompt
        for action in [ComputerAction.CLIPBOARD_READ, ComputerAction.CLIPBOARD_WRITE]:
            self._permissions[action] = ActionPermission(action, PermissionLevel.PROMPT)

        # App/File - denied by default
        for action in [ComputerAction.APP_LAUNCH, ComputerAction.FILE_OPEN, ComputerAction.FILE_WRITE]:
            self._permissions[action] = ActionPermission(action, PermissionLevel.DENIED)

    def can_execute(self, action: ComputerAction) -> bool:
        """Check if an action can be executed (not denied)."""
        perm = self._permissions.get(action)
        if not perm:
            return self._default_level != PermissionLevel.DENIED
        return perm.level != PermissionLevel.DENIED

    def get_level(self, action: ComputerAction) -> PermissionLevel:
        """Get the permission level for an action."""
        perm = self._permissions.get(action)
        return perm.level if perm else self._default_level

    def set_permission(self, action: ComputerAction, level: PermissionLevel,
                       conditions: Dict[str, Any] = None):
        """Set permission level for an action."""
        if action not in self._permissions:
            self._permissions[action] = ActionPermission(action, level)
        else:
            self._permissions[action].level = level
        if conditions:
            self._permissions[action].conditions = conditions

    def grant(self, action: ComputerAction, conditions: Dict = None):
        """Grant permission (set to ALLOWED)."""
        self.set_permission(action, PermissionLevel.ALLOWED, conditions)

    def deny(self, action: ComputerAction):
        """Deny permission."""
        self.set_permission(action, PermissionLevel.DENIED)

    def require_prompt(self, action: ComputerAction):
        """Require prompt for action."""
        self.set_permission(action, PermissionLevel.PROMPT)

    def get_all(self) -> Dict[ComputerAction, PermissionLevel]:
        return {action: perm.level for action, perm in self._permissions.items()}

    def get_summary(self) -> Dict[str, str]:
        return {action.value: perm.level.value for action, perm in self._permissions.items()}


from typing import Any