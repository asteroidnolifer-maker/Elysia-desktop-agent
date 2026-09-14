"""Computer-control abstraction for Elysia agents.

A single interface for controlled interaction with the machine: filesystem,
terminal (shell), processes, and system information. Every call is routed
through a permissions check, returns structured results, and is recorded on the
event bus. Execution has hard timeouts. Anything destructive is an explicit,
named action with a preview; the default policy denies it.

"Browser" and "App control" are reserved surfaces — they report unavailable
unless a companion controller is registered (safe default for headless runs).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from .events import EventBus
from .paths import PathEscapeError, is_within
from .workspace import Workspace


class PermissionDenied(PermissionError):
    pass


class ToolResult:
    def __init__(self, ok: bool, data=None, error: str = "", preview: str = ""):
        self.ok = ok
        self.data = data if data is not None else {}
        self.error = error
        self.preview = preview

    def to_dict(self) -> dict:
        return {"ok": self.ok, "data": self.data, "error": self.error,
                "preview": self.preview[:4000]}


class Computer:
    """Provides filesystem + shell + process + system-info tools under one
    permissioned interface."""

    def __init__(self, workspace: Workspace,
                 events: EventBus | None = None, allow_shell: bool = False,
                 shell_timeout_s: int = 120):
        self.workspace = workspace
        self.events = events or EventBus()
        self.allow_shell = allow_shell
        self.shell_timeout_s = shell_timeout_s
        self._shell_history: list[str] = []

    # -- permission helpers ------------------------------------------------
    def _check(self, permission: str):
        if not permission.startswith("workspace"):
            raise PermissionDenied(f"permission required: {permission}")
        return True

    def _emit(self, event_type: str, **kw):
        self.events.emit(event_type, agent_id="computer", **kw)

    # -- filesystem ----------------------------------------------------------
    def read_file(self, rel_path: str, max_chars: int = 12000) -> ToolResult:
        self._check("workspace:read")
        try:
            text = self.workspace.read(rel_path, max_chars=max_chars)
        except (PathEscapeError, FileNotFoundError, OSError) as e:
            if isinstance(e, PathEscapeError):
                self._emit("workspace.read", status="denied", detail=rel_path)
            return ToolResult(False, error=str(e))
        self._emit("workspace.read", status="ok", detail=rel_path)
        return ToolResult(True, data={"path": rel_path, "chars": len(text)},
                          preview=text[:max_chars])

    def write_file(self, rel_path: str, content: str) -> ToolResult:
        self._check("workspace:write")
        try:
            abspath = self.workspace.write_owned(rel_path, content)
        except (PathEscapeError, OSError) as e:
            if isinstance(e, PathEscapeError):
                self._emit("workspace.write", status="denied", detail=rel_path)
            return ToolResult(False, error=str(e))
        self._emit("workspace.write", status="ok", detail=rel_path)
        return ToolResult(True, data={"path": rel_path, "abspath": abspath,
                                      "bytes": len(content)})

    def append_file(self, rel_path: str, content: str) -> ToolResult:
        self._check("workspace:write")
        try:
            abspath = self.workspace.resolve(rel_path)
            if not is_within(self.workspace.root, abspath):
                raise PathEscapeError("path escapes workspace")
            os.makedirs(os.path.dirname(abspath) or self.workspace.root,
                        exist_ok=True)
            with open(abspath, "a", encoding="utf-8") as f:
                f.write(content)
        except (PathEscapeError, OSError) as e:
            return ToolResult(False, error=str(e))
        self._emit("workspace.write", status="ok", detail=f"+{rel_path}")
        return ToolResult(True, data={"path": rel_path})

    def delete_file(self, rel_path: str) -> ToolResult:
        self._check("workspace:write")
        try:
            abspath = self.workspace.resolve(rel_path)
            if not is_within(self.workspace.root, abspath):
                raise PathEscapeError("path escapes workspace")
            self.workspace.resolve_or_none(rel_path)  # re-validates
            if not os.path.isfile(abspath):
                return ToolResult(False, error="not a file")
            os.remove(abspath)
        except (PathEscapeError, OSError) as e:
            return ToolResult(False, error=str(e))
        self._emit("workspace.write", status="deleted", detail=rel_path)
        return ToolResult(True, data={"deleted": rel_path})

    def list_dir(self, rel_path: str = "") -> ToolResult:
        self._check("workspace:read")
        try:
            abspath = self.workspace.resolve(rel_path or ".")
            if not is_within(self.workspace.root, abspath):
                raise PathEscapeError("path escapes workspace")
            if not os.path.isdir(abspath):
                return ToolResult(False, error="not a directory")
            entries = sorted(os.listdir(abspath))
        except (PathEscapeError, OSError) as e:
            return ToolResult(False, error=str(e))
        self._emit("workspace.read", status="ok", detail=rel_path or ".")
        return ToolResult(True, data={"path": rel_path or ".",
                                      "entries": entries})

    # -- terminal -----------------------------------------------------------
    def run_shell(self, command: str, cwd: str = "",
                  timeout_s: int | None = None) -> ToolResult:
        if not self.allow_shell:
            return ToolResult(False, error="shell disabled by policy")
        timeout = timeout_s or self.shell_timeout_s
        cwd = cwd or self.workspace.root
        preview = command[:500]
        self._emit("tool.invoke", name="shell", detail=preview, status="ok")
        self._shell_history.append(preview)
        try:
            r = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                cwd=cwd, timeout=timeout,
                env={**os.environ, "PYTHONUNBUFFERED": "1"})
        except subprocess.TimeoutExpired:
            return ToolResult(False, error=f"timed out after {timeout}s",
                              preview=preview)
        except OSError as e:
            return ToolResult(False, error=str(e)[:300], preview=preview)
        out = (r.stdout or "") + (r.stderr or "")
        self._emit("tool.result", name="shell", status="ok" if r.returncode == 0
                   else "error", detail=f"rc={r.returncode}")
        return ToolResult(r.returncode == 0,
                          data={"rc": r.returncode}, preview=out[:4000],
                          error="" if r.returncode == 0 else out[:300])

    # -- processes -----------------------------------------------------------
    def start_process(self, cmd: list[str], cwd: str = "") -> ToolResult:
        """Start a long-running process detached; return pid info."""
        if not self.allow_shell:
            return ToolResult(False, error="process start disabled by policy")
        try:
            p = subprocess.Popen(cmd, cwd=cwd or self.workspace.root,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except OSError as e:
            return ToolResult(False, error=str(e)[:300])
        self._emit("tool.invoke", name="process", detail=cmd[0], status="ok")
        return ToolResult(True, data={"pid": p.pid, "cmd": " ".join(cmd)})

    def list_processes(self, pattern: str = "") -> ToolResult:
        try:
            r = subprocess.run(["ps", "aux"], capture_output=True, text=True,
                               timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return ToolResult(False, error="ps unavailable")
        lines = [l for l in r.stdout.splitlines()
                 if not pattern or pattern.lower() in l.lower()]
        return ToolResult(True, data={"match_count": len(lines) - 1},
                          preview="\n".join(lines[:2000]))

    def stop_process(self, pid: int) -> ToolResult:
        try:
            os.kill(int(pid), 15)
        except (OSError, ValueError) as e:
            return ToolResult(False, error=str(e)[:200])
        self._emit("tool.invoke", name="process_stop", detail=str(pid),
                   status="ok")
        return ToolResult(True, data={"stopped": pid})

    # -- system info -----------------------------------------------------------
    def system_info(self) -> ToolResult:
        import platform
        info = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu": platform.machine(),
        }
        return ToolResult(True, data=info)

    # -- reserved surfaces -----------------------------------------------------
    def browser_action(self, action: str, **kw) -> ToolResult:
        return ToolResult(False, error="browser control unavailable in this "
                                       "profile (reserved surface)")

    def app_action(self, app: str, action: str, **kw) -> ToolResult:
        return ToolResult(False, error="app control unavailable in this "
                                       "profile (reserved surface)")

    # -- home directory --------------------------------------------------------
    def home_path(self, *parts: str) -> str:
        return os.path.join(os.path.expanduser("~"), *parts)

    # -- position helper for sandboxes ------------------------------------------
    @staticmethod
    def which(binary: str) -> str | None:
        return shutil.which(binary)