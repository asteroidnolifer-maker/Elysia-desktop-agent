"""Canonical runtime tool layer: one registry, real tools, explicit permissions.

``elysia.core.tools`` defines the *mechanism* (ToolSpec/ToolRegistry: risk gates,
permission gates, dry-run previews, audit events). This module defines the
*runtime surface*: which concrete tools exist, what each one needs, and which
logical agent role may use it.

Design rules (see docs/ARCHITECTURE.md):

  - deny-by-default: a tool whose permission token was not granted to the calling
    role is refused, and an unknown role is granted nothing;
  - read-only roles can never write. Reviewers (code_reviewer, security_reviewer)
    are read-only by construction, so a review can never silently "fix" the file
    it is reviewing;
  - every tool is backed by a real subsystem (Workspace path validation, the QA
    harness, git, the computer-control backend) — nothing here is a stub;
  - a machine-level capability that does not exist on this host reports
    ``unavailable`` instead of pretending to work;
  - all invocations emit audit events (``tool.invoke`` / ``tool.result``).

Permission levels (escalating bundles, used in config and role maps):

    read_only        workspace:read, git:read, system:info
    workspace_write  + workspace:write
    git_write        + git:write
    network          + net:http
    browser          + browser:control
    desktop          + desktop:control
    system           + system:shell, system:process
"""
from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request

from .events import EventBus
from .paths import PathEscapeError
from .tools import HIGH, LOW, MODERATE, SAFE, ToolRegistry, ToolSpec
from .workspace import Workspace

# -- permission tokens -------------------------------------------------------
P_WS_READ = "workspace:read"
P_WS_WRITE = "workspace:write"
P_GIT_READ = "git:read"
P_GIT_WRITE = "git:write"
P_NET = "net:http"
P_BROWSER = "browser:control"
P_DESKTOP = "desktop:control"
P_SHELL = "system:shell"
P_PROC = "system:process"
P_INFO = "system:info"

ALL_PERMISSIONS = [P_WS_READ, P_WS_WRITE, P_GIT_READ, P_GIT_WRITE, P_NET,
                   P_BROWSER, P_DESKTOP, P_SHELL, P_PROC, P_INFO]

# Escalating levels. A role's grant is the union of its levels.
LEVELS: dict[str, list[str]] = {
    "read_only": [P_WS_READ, P_GIT_READ, P_INFO],
    "workspace_write": [P_WS_READ, P_GIT_READ, P_INFO, P_WS_WRITE],
    "git_write": [P_WS_READ, P_GIT_READ, P_INFO, P_WS_WRITE, P_GIT_WRITE],
    "network": [P_WS_READ, P_GIT_READ, P_INFO, P_NET],
    "browser": [P_WS_READ, P_GIT_READ, P_INFO, P_NET, P_BROWSER],
    "desktop": [P_WS_READ, P_INFO, P_DESKTOP],
    "system": [P_WS_READ, P_WS_WRITE, P_GIT_READ, P_INFO, P_SHELL, P_PROC],
    "destructive": [P_WS_READ, P_WS_WRITE, P_GIT_WRITE, P_SHELL, P_PROC],
}

# Which levels each logical agent role gets. Deliberately explicit: reviewers
# and planners have no write permission at all.
ROLE_LEVELS: dict[str, list[str]] = {
    "planner": ["read_only"],
    "architect": ["read_only"],
    "researcher": ["network"],
    "research_agent": ["network"],
    "fact_checker": ["network"],
    "analyst": ["read_only"],
    "implementer": ["workspace_write"],
    "debugger": ["system"],
    "tester": ["system"],
    "qa_engineer": ["system"],
    "integration_agent": ["git_write"],
    "documentation_agent": ["workspace_write"],
    "release_agent": ["git_write"],
    "git_engineer": ["git_write"],
    "code_reviewer": ["read_only"],
    "security_reviewer": ["read_only"],
    "performance_reviewer": ["read_only"],
    "dependency_reviewer": ["read_only"],
    "final_verifier": ["read_only"],
}

# Roles that must never be able to modify anything, even if a config tries to
# grant it: those declared with no write/shell/desktop capability at all. Note
# this is derived from the DECLARED levels, not from a caller's override, so a
# config cannot escalate a reviewer into a writer.
WRITE_FORBIDDEN = ("workspace_write", "git_write", "system", "destructive")
READ_ONLY_ROLES = frozenset(
    r for r, lv in ROLE_LEVELS.items() if not (set(lv) & set(WRITE_FORBIDDEN)))

DEFAULT_CEILING = ["read_only", "workspace_write", "system:info"]


def expand_levels(levels) -> list[str]:
    """Expand level names (or raw permission tokens) into permission tokens."""
    out: list[str] = []
    for item in levels or []:
        item = str(item)
        tokens = LEVELS.get(item, [item] if item in ALL_PERMISSIONS else [])
        for t in tokens:
            if t not in out:
                out.append(t)
    return out


def role_permissions(ceiling=None, overrides=None,
                     role_levels: dict | None = None) -> dict[str, list[str]]:
    """Role -> granted permission tokens, capped by the configured ceiling.

    The ceiling is what makes this deny-by-default: raising a role's levels in
    ``role_levels`` only helps if the ceiling (``tools.default_permissions`` in
    config) also allows the token. Reviewers are forced read-only.
    """
    cap = set(expand_levels(ceiling if ceiling is not None else DEFAULT_CEILING))
    levels = dict(role_levels or ROLE_LEVELS)
    out: dict[str, list[str]] = {}
    for role, lv in levels.items():
        granted = {t for t in expand_levels(lv) if t in cap}
        if role in READ_ONLY_ROLES:
            granted -= {P_WS_WRITE, P_GIT_WRITE, P_SHELL, P_PROC, P_DESKTOP}
        out[role] = sorted(granted)
    for role, extra in (overrides or {}).items():
        merged = set(out.get(role) or []) | {t for t in expand_levels(extra) if t in cap}
        if role in READ_ONLY_ROLES:
            merged -= {P_WS_WRITE, P_GIT_WRITE, P_SHELL, P_PROC, P_DESKTOP}
        out[role] = sorted(merged)
    return out


# -- SSRF guard (Phase 18: never let a model point us at the metadata service) --
_BLOCKED_IP_REASONS = (
    ("loopback", "is_loopback"),
    ("link-local", "is_link_local"),
    ("private", "is_private"),
    ("reserved", "is_reserved"),
    ("multicast", "is_multicast"),
    ("unspecified", "is_unspecified"),
)


def _ip_reason(ip: str) -> str | None:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "not an ip"
    for label, attr in _BLOCKED_IP_REASONS:
        if getattr(addr, attr, False):
            return label
    return None


def url_blocked_reason(url: str) -> str | None:
    """Reason this URL must not be fetched, or None if it is allowed.

    Blocks non-http(s) schemes and any host resolving to a loopback, private,
    link-local (cloud metadata), reserved or multicast address.
    """
    import socket
    try:
        p = urllib.parse.urlparse(url or "")
    except ValueError:
        return "unparseable url"
    if p.scheme not in ("http", "https"):
        return f"scheme not allowed: {p.scheme or '(none)'}"
    host = p.hostname or ""
    if not host:
        return "no host in url"
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as e:
            return f"dns failure: {e}"
        for info in infos:
            r = _ip_reason(info[4][0])
            if r:
                return f"{host} resolves to {info[4][0]} ({r})"
        return None
    return _ip_reason(str(addr))


class ToolLayer:
    """A registry plus the per-role permission map used to invoke it."""

    def __init__(self, registry: ToolRegistry, roles: dict[str, list[str]]):
        self.registry = registry
        self.roles = roles

    # -- permissions ---------------------------------------------------------
    def grant(self, role: str) -> list[str]:
        return list(self.roles.get(role) or [])

    def allowed(self, name: str, role: str) -> tuple[bool, str]:
        """(allowed, reason) without executing anything."""
        spec = self.registry.get(name)
        if spec is None:
            return False, f"unknown tool: {name}"
        if spec.risk == HIGH and name not in self.registry.allowed_high_risk:
            return False, f"{name} is high-risk and not enabled by policy"
        missing = sorted(set(spec.permissions) - set(self.grant(role)))
        if missing:
            return False, f"{name} needs {missing} (role {role} has none)"
        return True, ""

    def invoke(self, name: str, args: dict, role: str) -> dict:
        """Invoke a tool as ``role``. Always returns a structured result dict
        (``ok``/``data``/``error``) — never raises for a permission refusal."""
        res = self.registry.invoke(name, dict(args or {}),
                                  granted_permissions=self.grant(role))
        # Normalize the registry's two success shapes onto one key.
        if isinstance(res, dict) and "data" not in res and "result" in res:
            res = {**res, "data": res["result"]}
        return res

    # -- introspection -------------------------------------------------------
    def describe(self) -> list[dict]:
        rows = []
        for spec in sorted(self.registry.list(), key=lambda s: s.name):
            rows.append({"name": spec.name, "risk": spec.risk,
                         "permissions": sorted(spec.permissions),
                         "destructive": spec.destructive,
                         "timeout_s": spec.timeout_s,
                         "description": spec.description})
        return rows

    def roles_report(self) -> list[dict]:
        return [{"role": r, "permissions": sorted(p),
                 "can_write": P_WS_WRITE in p,
                 "tools": sorted(s.name for s in self.registry.list()
                                 if set(s.permissions) <= set(p))}
                for r, p in sorted(self.roles.items())]


# -- concrete tool implementations -------------------------------------------

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".gradle",
             "build", "dist", ".mypy_cache", ".pytest_cache"}
TEXT_EXT = {".py", ".md", ".txt", ".sh", ".go", ".js", ".ts", ".tsx", ".jsx",
            ".json", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".rs", ".java",
            ".kt", ".sql", ".html", ".css", ".c", ".h", ".cpp", ".rb", ".env",
            ".gradle", ".kts", ""}


def _iter_text_files(root: str, limit_files: int = 600):
    n = 0
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in SKIP_DIRS and not d.startswith(".git")]
        for f in fn:
            ext = os.path.splitext(f)[1].lower()
            if ext not in TEXT_EXT:
                continue
            if os.path.getsize(os.path.join(dp, f)) > 400_000:
                continue
            yield os.path.join(dp, f)
            n += 1
            if n >= limit_files:
                return


def build_tools(workspace: "Workspace | str", events: EventBus | None = None,
                cfg=None, *, desktop=None, ceiling=None, overrides=None,
                allow_high_risk=None, enable_shell=None,
                role_levels: dict | None = None) -> ToolLayer:
    """Build the canonical tool layer for a workspace.

    ``cfg`` (an elysia Config) supplies the permission ceiling
    (``tools.default_permissions``), the high-risk gate (``tools.allow_high_risk``)
    and the optional ``tools.role_permissions`` overrides. All of it is
    overridable by keyword so the layer is testable without a Config.
    """
    ws = workspace if isinstance(workspace, Workspace) else Workspace(workspace)
    events = events or EventBus()
    tools_cfg = getattr(cfg, "tools", None)
    if ceiling is None:
        ceiling = list(getattr(tools_cfg, "default_permissions", None)
                       or DEFAULT_CEILING)
    if allow_high_risk is None:
        allow_high_risk = bool(getattr(tools_cfg, "allow_high_risk", False))
    if overrides is None:
        overrides = dict(getattr(tools_cfg, "role_permissions", None) or {})
    if enable_shell is None:
        enable_shell = bool(getattr(tools_cfg, "enable_shell", False))
    if desktop is None:
        desktop = get_computer_desktop(cfg)

    roles = role_permissions(ceiling=ceiling, overrides=overrides,
                             role_levels=role_levels)

    # High-risk tools are only reachable when policy explicitly enables them.
    # The gate is derived from the registered specs themselves (single source of
    # truth) once everything is registered, below.
    reg = ToolRegistry(events=events, allowed_high_risk=set())

    # ---- filesystem ---------------------------------------------------------
    def _read(args):
        path = str(args.get("path") or "")
        text = ws.read(path, max_chars=int(args.get("max_chars") or 12000))
        return {"path": path, "chars": len(text), "content": text}

    def _list(args):
        return {"path": args.get("path") or ".", "entries": ws.list_files(
            str(args.get("path") or ""), max_depth=int(args.get("max_depth") or 2))}

    def _search(args):
        pat = re.compile(str(args.get("pattern") or ""), re.I)
        max_hits = int(args.get("max_hits") or 60)
        hits = []
        for f in _iter_text_files(ws.root):
            rel = os.path.relpath(f, ws.root).replace(os.sep, "/")
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if pat.search(line):
                            hits.append({"path": rel, "line": i,
                                         "text": line.strip()[:200]})
                            if len(hits) >= max_hits:
                                return {"pattern": pat.pattern, "hits": hits,
                                        "truncated": True}
            except OSError:
                continue
        return {"pattern": pat.pattern, "hits": hits, "truncated": False}

    def _write(args):
        path = str(args.get("path") or "")
        content = args.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        abspath = ws.write_owned(path, content)
        events.emit("file.changed", status="written", detail=path)
        return {"path": path, "abspath": abspath, "bytes": len(content)}

    def _remove(args):
        path = str(args.get("path") or "")
        abspath = ws.resolve(path)          # rejects traversal / symlink escape
        if not os.path.isfile(abspath):
            return {"path": path, "removed": False, "reason": "not a file"}
        os.remove(abspath)
        events.emit("file.changed", status="removed", detail=path)
        return {"path": path, "removed": True}

    # ---- QA ------------------------------------------------------------------
    def _validate(args):
        from .qa import validate_file
        path = str(args.get("path") or "")
        content = args.get("content")
        ok, reason = validate_file(path, content if isinstance(content, str) else None)
        return {"path": path, "valid": ok, "reason": reason}

    def _run_tests(args):
        from .qa import run as qa_run
        cmd, kind = discover_test_command(ws.root)
        if not cmd:
            return {"ran": False, "reason": "no test runner discovered",
                    "kind": None}
        rc, out = qa_run(cmd, cwd=ws.root,
                         timeout=int(args.get("timeout_s") or 180))
        events.emit("test.completed", status="ok" if rc == 0 else "fail",
                    detail=f"{kind}: rc={rc}")
        return {"ran": True, "kind": kind, "command": cmd, "rc": rc,
                "output": out[-4000:]}

    # ---- git -----------------------------------------------------------------
    def _git_status(args):
        from .git import current_branch, dirty_files, is_repo
        if not is_repo(ws.root):
            return {"repo": False, "branch": "", "dirty": []}
        return {"repo": True, "branch": current_branch(ws.root),
                "dirty": dirty_files(ws.root)}

    def _git_diff(args):
        from .git import git as git_cmd, is_repo
        if not is_repo(ws.root):
            return {"repo": False, "diff": ""}
        rc, out = git_cmd(ws.root, "diff", "--", ".")
        return {"repo": True, "rc": rc, "diff": out[:8000]}

    def _git_checkpoint(args):
        from .git import safe_checkpoint
        ok, out = safe_checkpoint(ws.root, str(args.get("message") or
                                              "elysia checkpoint"))
        return {"ok": ok, "result": out[:500]}

    # ---- system --------------------------------------------------------------
    def _system_info(args):
        from .resources import ResourceManager
        info = {"python": None, "cpu_count": os.cpu_count()}
        try:
            import platform
            info["platform"] = platform.platform()
            info["python"] = platform.python_version()
        except Exception:  # noqa: BLE001
            pass
        try:
            rm = ResourceManager.from_config(cfg)
            info["memory"] = rm.report()
        except Exception as e:  # noqa: BLE001 — diagnostics must not raise
            info["memory"] = {"error": str(e)[:120]}
        return info

    # ---- browser (guarded, offline-honest) ------------------------------------
    def _browser_open(args):
        url = str(args.get("url") or "")
        reason = url_blocked_reason(url)
        if reason:
            events.emit("tool.quarantined", status="denied", detail=f"{url}: {reason}")
            raise PermissionError(f"url refused by policy: {reason}")
        limit = int(args.get("max_chars") or 8000)
        req = urllib.request.Request(url, headers={"User-Agent": "Elysia/1.0"})
        with urllib.request.urlopen(req, timeout=int(args.get("timeout_s") or 20)) as r:
            raw = r.read(2_000_000).decode("utf-8", errors="replace")
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return {"url": url, "chars": len(text), "text": text[:limit]}

    # ---- knowledge -----------------------------------------------------------
    def _knowledge(args):
        from .knowledge import load_all
        q = str(args.get("query") or "").lower()
        out = []
        for e in load_all():
            if q and q not in (e.name + " " + " ".join(getattr(e, "aliases", []))).lower():
                continue
            out.append({"name": e.name, "summary": e.summary()[:1500]})
            if len(out) >= int(args.get("limit") or 5):
                break
        return {"query": q, "results": out}

    specs = [
        ("fs.read", "read a workspace file",
         [P_WS_READ], LOW, _read, {"path": "str", "max_chars": "int?"}),
        ("fs.list", "list workspace files",
         [P_WS_READ], LOW, _list, {"path": "str?", "max_depth": "int?"}),
        ("fs.search", "regex search workspace text files",
         [P_WS_READ], LOW, _search, {"pattern": "str", "max_hits": "int?"}),
        ("fs.write", "write a file the task owns (path-validated)",
         [P_WS_WRITE], MODERATE, _write, {"path": "str", "content": "str"}),
        ("fs.remove", "delete a workspace file",
         [P_WS_WRITE], MODERATE, _remove, {"path": "str"}),
        ("qa.validate", "validate a file with the language-aware QA harness",
         [P_WS_READ], LOW, _validate, {"path": "str", "content": "str?"}),
        ("qa.run_tests", "run the project's discovered test command",
         [P_SHELL], MODERATE, _run_tests, {"timeout_s": "int?"}),
        ("git.status", "current branch + dirty files",
         [P_GIT_READ], LOW, _git_status, {}),
        ("git.diff", "working-tree diff (capped)",
         [P_GIT_READ], LOW, _git_diff, {}),
        ("git.checkpoint", "commit a checkpoint without touching unrelated files",
         [P_GIT_WRITE], MODERATE, _git_checkpoint, {"message": "str"}),
        ("system.info", "host diagnostics: platform, cpu, memory",
         [P_INFO], LOW, _system_info, {}),
        ("browser.open_url", "fetch a URL over http(s) with an SSRF guard",
         [P_NET, P_BROWSER], MODERATE, _browser_open,
         {"url": "str", "max_chars": "int?"}),
        ("knowledge.search", "search vendored knowledge docs",
         [P_WS_READ], LOW, _knowledge, {"query": "str", "limit": "int?"}),
    ]
    for name, desc, perms, risk, fn, schema in specs:
        reg.register(ToolSpec(name=name, description=desc, permissions=list(perms),
                              risk=risk, input_schema=schema), fn)

    # ---- desktop / clipboard (Phase 15): high-risk, two-key gated -------------
    if desktop is not None:
        for spec, fn in _desktop_specs(desktop, events):
            reg.register(spec, fn)
    if allow_high_risk:
        reg.allowed_high_risk = {s.name for s in reg.list() if s.risk == HIGH}

    # -- previews for destructive/irreversible operations ------------------------
    for nm in ("fs.write", "fs.remove", "git.checkpoint"):
        spec = reg.get(nm)
        if spec:
            spec.destructive = nm != "fs.write"
            spec.dry_run_safe = True
    reg.dry_run_default = False
    layer = ToolLayer(reg, roles)
    layer.desktop = desktop
    return layer


def _desktop_specs(desktop, events):
    """ToolSpecs for the computer-control backend (real ops, permission-gated)."""
    def guard(fn):
        def wrapper(args):
            if not desktop.available():
                raise RuntimeError(f"desktop backend unavailable: "
                                   f"{desktop.unavailable_reason()}")
            return fn(args)
        return wrapper

    def spec(name, desc, schema=None, destructive=False):
        # Every desktop/clipboard action changes the user's machine, so it is
        # HIGH risk (policy gate) *and* needs desktop:control (permission gate).
        return ToolSpec(name=name, description=desc, permissions=[P_DESKTOP],
                        risk=HIGH, destructive=destructive,
                        dry_run_safe=True, input_schema=schema or {})

    return [
        (spec("desktop.screenshot", "capture the screen to a workspace file",
              {"path": "str?"}),
         guard(lambda a: {"path": a.get("path") or "screenshot.png",
                          "result": desktop.screenshot(a.get("path") or "")})),
        (spec("desktop.windows", "list top-level windows"),
         guard(lambda a: desktop.windows())),
        (spec("desktop.focus", "focus a window by id/title",
              {"window_id": "str"}),
         guard(lambda a: desktop.focus(str(a.get("window_id") or "")))),
        (spec("desktop.mouse", "move the pointer", {"x": "int", "y": "int"}),
         guard(lambda a: desktop.move_mouse(int(a["x"]), int(a["y"])))),
        (spec("desktop.click", "click the pointer (explicit coordinates)",
              {"x": "int?", "y": "int?", "button": "str?"}),
         guard(lambda a: desktop.click(a.get("x"), a.get("y"),
                                       a.get("button") or "left"))),
        (spec("desktop.type", "type text on the current focus", {"text": "str"}),
         guard(lambda a: desktop.type_text(str(a.get("text") or "")))),
        (spec("desktop.key", "press one key or chord", {"key": "str"}),
         guard(lambda a: desktop.press(str(a.get("key") or "")))),
        (spec("desktop.launch", "launch an application by name",
              {"app": "str", "args": "list?"}),
         guard(lambda a: desktop.launch(str(a.get("app") or ""),
                                        list(a.get("args") or [])))),
        (spec("clipboard.read", "read the clipboard"),
         guard(lambda a: {"text": desktop.clipboard_read()[:4000]})),
        (spec("clipboard.write", "write the clipboard", {"text": "str"},
              destructive=True),
         guard(lambda a: {"written": desktop.clipboard_write(
             str(a.get("text") or ""))})),
    ]


def get_computer_desktop(cfg=None):
    """The desktop backend for this host (real when a driver exists)."""
    from .computer import CommandLineDesktop, NullDesktop
    backend = CommandLineDesktop()
    return backend if backend.available() else NullDesktop()


def discover_test_command(root: str) -> tuple[list | None, str | None]:
    """Discover how to run this project's tests (no shell interpretation)."""
    if not os.path.isdir(root):
        return None, None
    has = lambda *names: any(os.path.exists(os.path.join(root, n)) for n in names)
    if has("go.mod") and shutil.which("go"):
        return ["go", "test", "./..."], "go"
    if (has("pytest.ini", "pyproject.toml", "setup.py", "tests") and
            shutil.which("python3")):
        return ["python3", "-m", "pytest", "-q"], "pytest"
    if has("Cargo.toml") and shutil.which("cargo"):
        return ["cargo", "test", "--quiet"], "cargo"
    if has("package.json") and shutil.which("npm"):
        return ["npm", "test", "--silent"], "npm"
    return None, None


def tool_audit(layer: ToolLayer, role: str) -> dict:
    """What a role may and may not do right now (for `elysia tools --audit`)."""
    rows = []
    for spec in sorted(layer.registry.list(), key=lambda s: s.name):
        ok, reason = layer.allowed(spec.name, role)
        rows.append({"tool": spec.name, "allowed": ok, "reason": reason,
                     "risk": spec.risk})
    return {"role": role, "granted": layer.grant(role),
            "allowed": [r["tool"] for r in rows if r["allowed"]],
            "denied": [r for r in rows if not r["allowed"]], "rows": rows}
