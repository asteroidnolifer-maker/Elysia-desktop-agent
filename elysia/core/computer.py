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
                 shell_timeout_s: int = 120, desktop=None,
                 allow_desktop: bool = False):
        self.workspace = workspace
        self.events = events or EventBus()
        self.allow_shell = allow_shell
        self.shell_timeout_s = shell_timeout_s
        self.desktop = desktop if desktop is not None else NullDesktop()
        self.allow_desktop = allow_desktop
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

    # -- desktop control (Phase 15) --------------------------------------------
    def desktop_action(self, action: str, **kw) -> ToolResult:
        """One permissioned entry point for screen/pointer/keyboard/clipboard.

        Requires ``allow_desktop`` (an explicit, configurable grant) AND a
        backend that is actually available on this host. Unlike shell access,
        desktop actions are never silently emulated: if there is no driver the
        call reports unavailable instead of pretending to have worked.
        """
        if not self.allow_desktop:
            self._emit("tool.quarantined", name=f"desktop.{action}",
                       status="denied", detail="desktop permission not granted")
            return ToolResult(False, error="desktop control requires the "
                                            "desktop:control permission")
        fn = getattr(self.desktop, action, None)
        if fn is None:
            return ToolResult(False, error=f"unknown desktop action: {action}")
        if not self.desktop.available():
            return ToolResult(False, error="desktop backend unavailable: "
                                            f"{self.desktop.unavailable_reason()}")
        self._emit("tool.invoke", name=f"desktop.{action}", status="ok")
        try:
            result = fn(**kw)
        except TypeError as e:
            return ToolResult(False, error=f"bad arguments for {action}: {e}")
        except Exception as e:  # noqa: BLE001 — a driver failure is data, not a crash
            self._emit("tool.result", name=f"desktop.{action}", status="error",
                       error=str(e)[:200])
            return ToolResult(False, error=f"{type(e).__name__}: {str(e)[:200]}")
        self._emit("tool.result", name=f"desktop.{action}", status="ok")
        return ToolResult(True, data=result if isinstance(result, dict)
                          else {"result": result})

    def screenshot(self, path: str = "") -> ToolResult:
        """Capture the screen into the workspace (path-validated)."""
        target = path or "screenshot.png"
        try:
            self.workspace.resolve(target)
        except PathEscapeError as e:
            return ToolResult(False, error=str(e))
        return self.desktop_action("screenshot", path=target)

    # -- reserved surfaces -----------------------------------------------------
    def browser_action(self, action: str, **kw) -> ToolResult:
        return ToolResult(False, error="browser control is not wired in this "
                                       "profile; use the browser.* tools "
                                       "(guarded fetch) instead")

    def app_action(self, app: str, action: str, **kw) -> ToolResult:
        """Launch/close an application through the desktop backend."""
        if action == "launch":
            return self.desktop_action("launch", app=app, args=kw.get("args", []))
        if action == "close":
            return self.desktop_action("close", app=app)
        return ToolResult(False, error=f"unknown app action: {action}")

    # -- home directory --------------------------------------------------------
    def home_path(self, *parts: str) -> str:
        return os.path.join(os.path.expanduser("~"), *parts)

    # -- position helper for sandboxes ------------------------------------------
    @staticmethod
    def which(binary: str) -> str | None:
        return shutil.which(binary)


# ---------------------------------------------------------------------------
# Desktop backends. Elysia detects a driver instead of assuming one, and no
# backend here ever interprets model text as a shell command: every driver call
# is an argv list (or a library call), never a shell string.
# ---------------------------------------------------------------------------
class DesktopBackend:
    """Interface for host-level screen/input control."""

    name = "none"

    def available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return "no desktop backend on this host"

    def screenshot(self, path: str = "") -> dict:
        raise RuntimeError(self.unavailable_reason())

    def windows(self) -> dict:
        raise RuntimeError(self.unavailable_reason())

    def focus(self, window_id: str = "") -> dict:
        raise RuntimeError(self.unavailable_reason())

    def move_mouse(self, x: int, y: int) -> dict:
        raise RuntimeError(self.unavailable_reason())

    def click(self, x=None, y=None, button: str = "left") -> dict:
        raise RuntimeError(self.unavailable_reason())

    def type_text(self, text: str) -> dict:
        raise RuntimeError(self.unavailable_reason())

    def press(self, key: str) -> dict:
        raise RuntimeError(self.unavailable_reason())

    def clipboard_read(self) -> str:
        raise RuntimeError(self.unavailable_reason())

    def clipboard_write(self, text: str) -> bool:
        raise RuntimeError(self.unavailable_reason())

    def launch(self, app: str, args: list | None = None) -> dict:
        raise RuntimeError(self.unavailable_reason())


class NullDesktop(DesktopBackend):
    """Honest no-op backend: reports that this host has no desktop driver."""

    name = "null"

    def unavailable_reason(self) -> str:
        return ("no supported desktop driver found (install xdotool + scrot/import "
                 "on X11, or use macOS screencapture/osascript)")


class CommandLineDesktop(DesktopBackend):
    """X11/macOS desktop control via detected CLI drivers (argv only)."""

    name = "cli"

    def __init__(self, timeout_s: int = 20):
        self.timeout_s = timeout_s
        self._xdotool = shutil.which("xdotool")
        self._wmctrl = shutil.which("wmctrl")
        self._xclip = shutil.which("xclip") or shutil.which("xsel")
        self._shot = (shutil.which("scrot") or shutil.which("import") or
                      shutil.which("gnome-screenshot") or
                      shutil.which("screencapture"))
        self._osascript = shutil.which("osascript")
        import sys
        self._linux_x11 = sys.platform.startswith("linux") and bool(
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        self._mac = sys.platform == "darwin"

    def available(self) -> bool:
        if self._mac:
            return bool(self._shot or self._osascript)
        return bool(self._linux_x11 and (self._xdotool or self._shot))

    def unavailable_reason(self) -> str:
        if self._mac:
            return "macOS drivers not found (screencapture/osascript)"
        if not self._linux_x11:
            return "no X11/Wayland display session (headless host)"
        return "xdotool/scrot not installed"

    # -- helpers -------------------------------------------------------------
    def _run(self, argv: list) -> tuple[int, str]:
        try:
            r = subprocess.run(argv, capture_output=True, text=True,
                               timeout=self.timeout_s)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, str(e)[:200]

    def _xdo(self, *args) -> dict:
        if not self._xdotool:
            raise RuntimeError("xdotool not installed")
        rc, out = self._run([self._xdotool, *[str(a) for a in args]])
        if rc != 0:
            raise RuntimeError(out.strip()[:200] or f"xdotool rc={rc}")
        return {"rc": rc, "output": out.strip()[:500]}

    # -- actions -------------------------------------------------------------
    def screenshot(self, path: str = "") -> dict:
        target = path or "screenshot.png"
        if not self._shot:
            raise RuntimeError("no screenshot tool installed")
        base = os.path.basename(self._shot)
        if base == "screencapture":
            rc, out = self._run([self._shot, "-x", target])
        elif base == "gnome-screenshot":
            rc, out = self._run([self._shot, "-f", target])
        elif base == "import":
            rc, out = self._run([self._shot, "-window", "root", target])
        else:
            rc, out = self._run([self._shot, target])
        if rc != 0:
            raise RuntimeError(out.strip()[:200] or "screenshot failed")
        return {"path": target}

    def windows(self) -> dict:
        if self._wmctrl:
            rc, out = self._run([self._wmctrl, "-l"])
            rows = [l.split(None, 3) for l in out.splitlines() if l.strip()]
            return {"count": len(rows),
                    "windows": [{"id": r[0], "title": r[3] if len(r) > 3 else ""}
                                for r in rows if len(r) >= 3]}
        rc, out = self._run([self._xdotool, "search", "--name", "."]) if self._xdotool \
            else (1, "")
        ids = [l.strip() for l in out.splitlines() if l.strip()]
        return {"count": len(ids), "windows": [{"id": i, "title": ""} for i in ids]}

    def focus(self, window_id: str = "") -> dict:
        if not window_id:
            raise RuntimeError("window_id is required")
        if self._wmctrl:
            rc, out = self._run([self._wmctrl, "-i", "-a", window_id])
            if rc != 0:
                raise RuntimeError(out.strip()[:200] or f"wmctrl rc={rc}")
            return {"focused": window_id}
        return self._xdo("windowactivate", window_id)

    def move_mouse(self, x: int, y: int) -> dict:
        return self._xdo("mousemove", int(x), int(y))

    def click(self, x=None, y=None, button: str = "left") -> dict:
        if x is not None and y is not None:
            self.move_mouse(x, y)
        return self._xdo("click", button)

    def type_text(self, text: str) -> dict:
        return self._xdo("type", "--delay", "12", "--", text)

    def press(self, key: str) -> dict:
        return self._xdo("key", "--clearmodifiers", key)

    def clipboard_read(self) -> str:
        if not self._xclip:
            raise RuntimeError("no clipboard tool installed (xclip/xsel)")
        base = os.path.basename(self._xclip)
        argv = [self._xclip, "-selection", "clipboard", "-o"] if base == "xclip" \
            else [self._xclip, "-b", "-o"]
        rc, out = self._run(argv)
        if rc != 0:
            raise RuntimeError(out.strip()[:200] or "clipboard read failed")
        return out

    def clipboard_write(self, text: str) -> bool:
        if not self._xclip:
            raise RuntimeError("no clipboard tool installed (xclip/xsel)")
        base = os.path.basename(self._xclip)
        argv = [self._xclip, "-selection", "clipboard"] if base == "xclip" \
            else [self._xclip, "-b", "-i"]
        try:
            r = subprocess.run(argv, input=text, text=True, timeout=self.timeout_s)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RuntimeError(str(e)[:200]) from e
        if r.returncode != 0:
            raise RuntimeError("clipboard write failed")
        return True

    def launch(self, app: str, args: list | None = None) -> dict:
        if not app or "/" in app or "\\" in app:
            raise RuntimeError("app must be a bare command name")
        binary = shutil.which(app)
        if not binary:
            raise RuntimeError(f"application not found on PATH: {app}")
        argv = [binary, *[str(a) for a in (args or [])]]
        try:
            p = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        except OSError as e:
            raise RuntimeError(str(e)[:200]) from e
        return {"pid": p.pid, "app": app}