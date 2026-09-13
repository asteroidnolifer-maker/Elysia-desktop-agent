"""Permissioned tool registry.

Tools have metadata (name, description, input/output schema, permissions,
timeout). Invocation always goes through a permission check — the model never
turns arbitrary output directly into arbitrary shell execution.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .events import EventBus


@dataclass
class ToolSpec:
    name: str
    description: str = ""
    permissions: list = field(default_factory=list)   # e.g. ["workspace:write", "system:shell"]
    timeout_s: int = 30
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)


class ToolError(Exception):
    pass


class PermissionDenied(Exception):
    pass


class ToolRegistry:
    def __init__(self, events: EventBus | None = None):
        self._tools: dict[str, tuple[ToolSpec, Callable]] = {}
        self.events = events

    def register(self, spec: ToolSpec, fn: Callable) -> None:
        self._tools[spec.name] = (spec, fn)

    def list(self) -> list[ToolSpec]:
        return [spec for spec, _ in self._tools.values()]

    def get(self, name: str) -> ToolSpec | None:
        spec, _ = self._tools.get(name, (None, None))
        return spec

    def invoke(self, name: str, args: dict, granted_permissions=None) -> dict:
        entry = self._tools.get(name)
        if not entry:
            raise ToolError(f"unknown tool: {name}")
        spec, fn = entry
        need = set(spec.permissions)
        granted = set(granted_permissions or [])
        missing = need - granted
        if missing:
            raise PermissionDenied(
                f"tool {name} needs permissions {sorted(missing)}")
        t0 = time.time()
        if self.events:
            self.events.emit("tool_invoke", status="started",
                             provider=None, **{"tool": name})
        try:
            result = fn(args)
            dur = time.time() - t0
            if self.events:
                self.events.emit("tool_invoke", status="ok",
                                 duration_s=dur, **{"tool": name})
            return {"ok": True, "tool": name, "result": result, "duration_s": dur}
        except Exception as e:
            if self.events:
                self.events.emit("tool_invoke", status="error",
                                 error=str(e)[:300], **{"tool": name})
            raise