#!/usr/bin/env python3
"""
Elysia JARVIS HUD server — thin HTTP layer over the canonical core.

All execution goes through the canonical pipeline:
    MasterController → Scheduler → TaskExecutor → AgentPipeline → ProviderManager → ToolLayer → Workspace → QA

This server only handles HTTP routing and HUD rendering. No legacy task division,
worker management, or provider logic — those live in elysia.core.
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

ORCH_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(ORCH_DIR)
WS_DIR = os.path.realpath(os.path.join(REPO_ROOT, "workspace"))
LOGS_DIR = os.path.join(ORCH_DIR, "logs")
HUD_PATH = os.path.join(ORCH_DIR, "hud.html")
JARVIS_JPG = os.path.expanduser("~/Downloads/jarvis.jpg")
# Database path (tests can override by setting server.DB_PATH = "/new/path")
DB_PATH = os.path.join(ORCH_DIR, "taskboard.sqlite")


def _get_db_path() -> str:
    """Get the current database path (allows test patching)."""
    return DB_PATH

sys.path.insert(0, REPO_ROOT)

from elysia.core.config import load_config
from elysia.core.events import EventBus
from elysia.core.master import MasterController
from elysia.core.server_api import run_agent, run_chat, deep_research
from elysia.core.tasks import TaskStore
from elysia.core.toolkit import role_permissions

EVENTS = EventBus(run_id="hud")

# Canonical controller (lazy-initialized)
_CONTROLLER = None
_CONTROLLER_LOCK = __import__("threading").Lock()


def _controller() -> MasterController:
    global _CONTROLLER
    if _CONTROLLER is None:
        with _CONTROLLER_LOCK:
            if _CONTROLLER is None:
                cfg = load_config()
                store = TaskStore(_get_db_path())
                from elysia.core.providers import ProviderManager
                from elysia.core.resources import ResourceManager
                from elysia.core.toolkit import build_tools
                from elysia.core.workspace import Workspace

                providers = ProviderManager()
                for pc in cfg.providers:
                    providers.register(pc)
                tools = build_tools(Workspace(WS_DIR), EVENTS, cfg)
                _CONTROLLER = MasterController(
                    store=store,
                    providers=providers,
                    workspace_root=WS_DIR,
                    cfg=cfg,
                    events=EVENTS,
                    resources=ResourceManager(),
                    tools=tools,
                )
                _CONTROLLER.start()
    return _CONTROLLER


# Compat aliases for tests
class _TaskboardStub:
    def store(self):
        return _controller().store

taskboard = _TaskboardStub()


def start_scheduler_thread():
    """Compat: scheduler runs inside MasterController."""
    return _controller().scheduler


def stop_scheduler():
    """Compat: scheduler stops with MasterController."""
    _controller().scheduler.stop()


def log(msg: str):
    print(f"{__import__('time').strftime('%H:%M:%S')} [server] {msg}", flush=True)


def _permission_audit(role: str) -> dict:
    """What a role may invoke right now (for HUD/tools audit)."""
    cfg = load_config()
    tools_cfg = getattr(cfg, "tools", None)
    ceiling = list(getattr(tools_cfg, "default_permissions", None) or ["read_only", "workspace_write", "system:info"])
    overrides = dict(getattr(tools_cfg, "role_permissions", None) or {})
    allow_high_risk = bool(getattr(tools_cfg, "allow_high_risk", False))
    from elysia.core.tools import role_permissions as _rp
    return _rp(ceiling=ceiling, overrides=overrides, role_levels=None).get(role, {})


class Handler(BaseHTTPRequestHandler):
    server_version = "ElysiaHUD/1.0"

    def _send(self, code: int, body, ctype: str = "application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 1_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode())
        except Exception:
            return {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        q = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}

        if path == "/":
            return self._page()
        if path == "/jarvis.jpg":
            return self._jarvis()
        if path == "/api/state":
            return self._send(200, self._api_state())
        if path == "/api/tasks":
            return self._send(200, self._api_tasks(q))
        if path == "/api/agents":
            return self._send(200, self._api_agents())
        if path == "/api/providers":
            return self._send(200, self._api_providers())
        if path == "/api/events":
            return self._send(200, self._api_events(q))
        if path == "/api/scheduler":
            return self._send(200, self._api_scheduler())
        if path == "/api/tools":
            return self._send(200, self._api_tools(q))
        if path == "/api/health":
            return self._send(200, self._api_health())
        if path == "/api/agent-log":
            return self._send(200, self._api_agent_log(q))
        return self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        body = self._body()

        if path == "/api/ask":
            return self._api_ask(body)
        if path == "/api/task":
            return self._api_task(body)
        if path == "/api/task/cancel":
            return self._api_task_cancel(body)
        if path == "/api/chat":
            return self._api_chat(body)
        if path == "/api/agent":
            return self._api_agent(body)
        if path == "/api/executor":
            return self._api_executor(body)
        return self._send(404, {"ok": False, "error": "not found"})

    # ------- handlers -------

    def _page(self):
        try:
            with open(HUD_PATH) as f:
                html = f.read()
        except OSError:
            return self._send(500, "hud.html missing", "text/plain")
        return self._send(200, html, "text/html; charset=utf-8")

    def _jarvis(self):
        try:
            with open(JARVIS_JPG, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._send(404, {"ok": False, "error": "jarvis.jpg not found"})

    def _api_state(self):
        ctrl = _controller()
        store = ctrl.store
        counts = store.counts()
        health = ctrl.health()
        agents = ctrl.agents()
        recent = store.list(limit=25)
        return {
            "ok": True,
            "time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
            "health": health,
            "counts": counts,
            "tasks": recent,
            "agents": agents,
            "running": ctrl.running,
        }

    def _api_tasks(self, q):
        ctrl = _controller()
        store = ctrl.store
        if q.get("id"):
            tid = int(q["id"][0])
            t = store.get(tid)
            return {"ok": True, "task": t} if t else {"ok": False, "error": "not found"}
        status = (q.get("status") or [""])[0] or None
        n = min(int((q.get("n") or ["50"])[0]), 200)
        tasks = store.list(status=status, limit=n)
        return {"ok": True, "status": status, "tasks": tasks, "counts": store.counts()}

    def _api_agents(self):
        ctrl = _controller()
        return {"ok": True, "agents": ctrl.agents()}

    def _api_providers(self):
        ctrl = _controller()
        return {"ok": True, "providers": ctrl.providers.health_report(probe=True)}

    def _api_events(self, q):
        n = min(int((q.get("n") or ["100"])[0]), 500)
        et = ((q.get("type") or [""])[0]) or None
        return {"ok": True, "events": EVENTS.recent(n=n, event_type=et)}

    def _api_scheduler(self):
        ctrl = _controller()
        s = ctrl.scheduler
        ex = ctrl.executor
        return {
            "ok": True,
            "running": s is not None,
            "workers": s.workers.list() if s else [],
            "max_concurrency": s.max_concurrency if s else None,
            "budget": s.current_budget() if s else None,
            "counts": ctrl.store.counts(),
            "blocked": len(ctrl.store.blocked_tasks()),
            "executor": {
                "running": bool(ex and ex.running),
                "inflight": ex.inflight() if ex else [],
                "stats": ex.stats if ex else None,
            },
        }

    def _api_tools(self, q):
        role = (q.get("role") or ["implementer"])[0]
        ctrl = _controller()
        layer = ctrl.tools
        if not layer:
            return {"ok": True, "tools": [], "roles": {}}
        if q.get("audit"):
            return {"ok": True, "audit": _permission_audit(role)}
        return {"ok": True, "tools": layer.describe(), "roles": layer.roles_report()}

    def _api_health(self):
        ctrl = _controller()
        return {"ok": True, "health": ctrl.health()}

    def _api_agent_log(self, q):
        wid = (q.get("worker") or [""])[0]
        n = int((q.get("n") or ["30"])[0])
        logf = os.path.join(LOGS_DIR, f"worker-{wid}.log") if wid else os.path.join(LOGS_DIR, "server.log")
        try:
            with open(logf, "rb") as f:
                data = f.read()
            lines = data.decode("utf-8", "replace").splitlines()
            return {"ok": True, "worker": wid, "lines": lines[-n:]}
        except OSError:
            return {"ok": True, "worker": wid, "lines": []}

    def _api_ask(self, body):
        goal = str(body.get("goal") or "").strip()
        if len(goal) < 8:
            return self._send(400, {"ok": False, "error": "goal too short (>=8 chars)"})
        files_hint = body.get("files") or []
        if isinstance(files_hint, str):
            files_hint = [f.strip() for f in files_hint.split(",") if f.strip()]

        log(f"/api/ask goal: {goal[:120]}")
        res = run_agent(goal, workspace=WS_DIR, timeout_s=180)
        return self._send(200 if res.get("ok") else 502, res)

    def _api_task(self, body):
        title = str(body.get("title") or "").strip()
        desc = str(body.get("description") or title).strip()
        files = body.get("files") or []
        if isinstance(files, str):
            files = [f.strip() for f in files.split(",") if f.strip()]
        if not title or not files:
            return self._send(400, {"ok": False, "error": "title and >=1 owned file required"})
        ctrl = _controller()
        from elysia.core.paths import validate_file_list
        try:
            files = validate_file_list(WS_DIR, files)
        except Exception as e:
            return self._send(400, {"ok": False, "error": f"invalid file path: {e}"})
        tid = ctrl.store.add_task(title=title, description=desc, owned_files=files, priority=5, status="ready")
        EVENTS.emit("task_added", task_id=tid, status="open")
        log(f"/api/task -> added #{tid} {title[:60]}")
        return self._send(200, {"ok": True, "added": [ctrl.store.get(tid)]})

    def _api_task_cancel(self, body):
        tid = int(body.get("id") or 0)
        if tid <= 0:
            return self._send(400, {"ok": False, "error": "id required"})
        ctrl = _controller()
        affected = ctrl.cancel(tid, by="user")
        return self._send(200, {"ok": True, "cancelled": affected})

    def _api_chat(self, body):
        message = str(body.get("message") or "").strip()
        history = body.get("history") or []
        if len(message) < 2:
            return self._send(400, {"ok": False, "error": "message too short"})
        if len(message) > 4000:
            return self._send(400, {"ok": False, "error": "message too long (max 4000)"})

        low = message.lower()
        if any(k in low for k in ("status", "how many", "count", "health", "running", "agents", "workers", "board", "progress", "#")):
            return self._send(200, run_chat(message, workspace=WS_DIR))
        if any(k in low for k in ("research", "deep research", "investigate", "find out")):
            return self._send(200, deep_research(message, workspace=WS_DIR))
        if any(k in low for k in ("pool", "worker", "agent")) and any(v in low for v in ("start", "stop", "launch", "kill")):
            return self._send(200, run_chat(message, workspace=WS_DIR))

        return self._send(200, run_chat(message, workspace=WS_DIR))

    def _api_agent(self, body):
        task = str(body.get("task") or body.get("message") or "").strip()
        if len(task) < 3:
            return self._send(400, {"ok": False, "error": "task too short"})
        log(f"/api/agent task: {task[:120]}")
        res = run_agent(task, workspace=WS_DIR, timeout_s=20)
        return self._send(200 if res.get("ok") else 502, res)

    def _api_executor(self, body):
        action = (body.get("action") or "status").strip()
        ctrl = _controller()
        if action == "start":
            if not ctrl.executor.running:
                ctrl.executor.start()
            return self._send(200, {"ok": True, "running": ctrl.executor.running})
        if action == "stop":
            if ctrl.executor.running:
                ctrl.executor.stop()
            return self._send(200, {"ok": True, "running": False})
        ex = ctrl.executor
        return self._send(200, {
            "ok": True,
            "running": ex.running,
            "inflight": ex.inflight(),
            "stats": ex.stats,
            "max_tasks": ex.max_tasks,
        })


def main():
    ap = argparse.ArgumentParser(description="Elysia JARVIS HUD server (canonical core)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8087)
    args = ap.parse_args()

    os.makedirs(LOGS_DIR, exist_ok=True)
    log(f"HUD listening on http://{args.host}:{args.port}  (workspace={WS_DIR})")
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # Graceful shutdown
        try:
            ctrl = _controller()
            ctrl.stop(release=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()