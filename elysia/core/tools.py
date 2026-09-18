"""Permissioned, risk-aware tool registry.

Tools have metadata (name, description, input/output schema, permissions,
timeout, risk). Invocation always goes through a permission check — the model
never turns arbitrary output directly into arbitrary shell execution.

Risk levels: safe < low < moderate < high. The default policy denies high-risk
(and quarantinable) operations unless explicitly enabled; destructive actions
can be dry-run/previewed before execution. Every invocation is recorded on the
event bus with a structured result.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .events import EventBus

SAFE = "safe"
LOW = "low"
MODERATE = "moderate"
HIGH = "high"
RISK_ORDER = {SAFE: 0, LOW: 1, MODERATE: 2, HIGH: 3}


@dataclass
class ToolSpec:
    name: str
    description: str = ""
    permissions: list = field(default_factory=list)   # e.g. ["workspace:write", "system:shell"]
    timeout_s: int = 30
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    risk: str = SAFE
    destructive: bool = False
    preview_fn: Callable | None = None  # (args)->str preview for dry-run
    dry_run_safe: bool = False          # True if a dry_run arg is accepted


class ToolError(Exception):
    pass


class PermissionDenied(Exception):
    pass


class PolicyDenied(Exception):
    pass


class ToolResult:
    """Structured result from a tool invocation (never a raw exception)."""

    def __init__(self, ok: bool = True, data=None, error: str = "",
                 preview: str = "", dry_run: bool = False):
        self.ok = ok
        self.data = data or {}
        self.error = error
        self.preview = preview
        self.dry_run = dry_run

    def to_dict(self) -> dict:
        return {"ok": self.ok, "data": self.data, "error": self.error,
                "preview": self.preview[:8000], "dry_run": self.dry_run}

    @classmethod
    def ok_result(cls, data=None, preview="") -> "ToolResult":
        return cls(ok=True, data=data, preview=preview)

    @classmethod
    def preview_result(cls, preview: str, data=None) -> "ToolResult":
        """A successful dry run: `dry_run` MUST be True here, otherwise callers
        that branch on the flag would believe the action really happened."""
        payload = {"dry_run": True, "preview": preview}
        if data:
            payload.update(data)
        return cls(ok=True, data=payload, preview=preview, dry_run=True)

    @classmethod
    def error_result(cls, message, data=None) -> "ToolResult":
        return cls(ok=False, data=data, error=message)


class ToolRegistry:
    def __init__(self, events: EventBus | None = None,
                 allowed_high_risk: set[str] | None = None,
                 dry_run_default: bool = False):
        self._tools: dict[str, tuple[ToolSpec, Callable]] = {}
        self.events = events
        self.allowed_high_risk = allowed_high_risk or set()
        self._policies: list[Callable] = []
        self.dry_run_default = dry_run_default

    def register(self, spec: ToolSpec, fn: Callable) -> None:
        self._tools[spec.name] = (spec, fn)

    def add_policy(self, fn: Callable) -> None:
        """fn(spec, args) -> str reason to deny, or None to allow."""
        self._policies.append(fn)

    def list(self, risk_max: str | None = None) -> list[ToolSpec]:
        """Registered specs, optionally filtered to ``risk <= risk_max``."""
        specs = [spec for spec, _ in self._tools.values()]
        if risk_max:
            ceiling = RISK_ORDER.get(risk_max, max(RISK_ORDER.values()))
            specs = [s for s in specs if RISK_ORDER.get(s.risk, 0) <= ceiling]
        return specs

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def get(self, name: str) -> ToolSpec | None:
        spec, _ = self._tools.get(name, (None, None))
        return spec

    def invoke(self, name: str, args: dict, granted_permissions=None) -> dict:
        entry = self._tools.get(name)
        if not entry:
            return ToolResult.error_result(f"unknown tool: {name}").to_dict()
        spec, fn = entry
        # -- risk gate ---------------------------------------------------------
        if spec.risk == HIGH and name not in self.allowed_high_risk:
            return ToolResult.error_result(
                f"tool {name} is high-risk and not allowed by policy").to_dict()
        # -- permission gate ----------------------------------------------------
        need = set(spec.permissions)
        granted = set(granted_permissions or [])
        missing = need - granted
        if missing:
            return ToolResult.error_result(
                f"tool {name} needs permissions {sorted(missing)}").to_dict()
        # -- dry-run / preview ---------------------------------------------------
        dry_run = bool(args.pop("_dry_run", self.dry_run_default))
        if dry_run or (spec.destructive and not spec.dry_run_safe):
            preview = (spec.preview_fn(args) if spec.preview_fn
                       else f"{spec.name} would run with args: {str(args)[:500]}")
            return ToolResult.preview_result(preview).to_dict()
        # -- policy callbacks ----------------------------------------------------
        for pol in self._policies:
            reason = pol(spec, args)
            if reason:
                return ToolResult.error_result(f"tool {name}: {reason}").to_dict()
        # -- invoke --------------------------------------------------------------
        t0 = time.time()
        if self.events:
            self.events.emit("tool.invoke", status="started",
                             provider=None, risk=spec.risk, **{"tool": name})
        try:
            result = fn(args)
            dur = time.time() - t0
            if self.events:
                self.events.emit("tool.result", status="ok",
                                 duration_s=dur, **{"tool": name})
            if isinstance(result, ToolResult):
                return result.to_dict()
            return {"ok": True, "tool": name, "result": result,
                    "duration_s": dur}
        except PermissionDenied as e:
            if self.events:
                self.events.emit("tool.result", status="denied",
                                 error=str(e)[:300], **{"tool": name})
            return ToolResult.error_result(str(e)).to_dict()
        except Exception as e:
            if self.events:
                self.events.emit("tool.result", status="error",
                                 error=str(e)[:300], **{"tool": name})
            return ToolResult.error_result(f"{type(e).__name__}: {str(e)[:300]}").to_dict()