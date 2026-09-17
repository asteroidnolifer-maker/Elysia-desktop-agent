"""Master control plane — one controller for a goal's whole workflow.

``MasterController`` is the top of the runtime graph. Everything below it is the
canonical core (there is no second execution path):

    goal
      -> planner            AgentPipeline.plan_task (provider routed by capability)
      -> durable task graph TaskStore rows: goal milestone + subtasks + deps
      -> scheduler          leases, resource/provider budget, atomic reservation
      -> executor           in-process, N parallel slots, lease heartbeats
      -> per task           implementer -> Workspace.write_owned -> QA
                            tester (real runner) -> code_reviewer (real git diff)
      -> completion         persisted in SQLite: survives a process restart

The controller also *reports* the run honestly — which logical agents actually
ran, which providers answered or were failed over, which files changed on disk,
QA/test/review output, and the final task states. Nothing here is simulated: the
files are really written, the diff is really read, the states are really stored.
"""
from __future__ import annotations

import re
import time

from .agents import AgentPipeline
from .events import EventBus
from .executor import TaskExecutor
from .providers import ProviderManager
from .scheduler import Scheduler
from .tasks import TERMINAL, TaskStore

# Role that owns the file-writing stage of a planned sub-task. The other
# logical agents (planner/tester/code_reviewer) run inside the pipeline.
DEFAULT_SUBTASK_ROLE = "implementer"

_FILE_RE = re.compile(
    r"[\w./-]+\.(?:py|md|rs|go|js|ts|tsx|jsx|sh|yaml|yml|json|toml|sql|css|html)",
    re.I)


def extract_owned_files(text: str | None, limit: int = 8) -> list[str]:
    """Owned-file hints from a plan item (never traversal, never absolute)."""
    out = [p for p in _FILE_RE.findall(text or "")
           if ".." not in p and not p.startswith("/")]
    return list(dict.fromkeys(out))[:limit]


# Capabilities each logical role needs. Mirrors the configured
# ``model_routing.role_capabilities``; kept here so a briefing can describe the
# control plane without constructing a scheduler.
ROLE_CAPABILITIES: dict[str, list[str]] = {
    "planner": ["chat", "reasoning"],
    "architect": ["chat", "reasoning"],
    "implementer": ["chat", "coding"],
    "tester": ["chat", "coding"],
    "debugger": ["chat", "coding", "reasoning"],
    "code_reviewer": ["chat", "reasoning"],
    "security_reviewer": ["chat", "reasoning"],
    "documentation_agent": ["chat"],
    "research_agent": ["chat", "reasoning"],
    "integration_agent": ["chat", "coding"],
    "release_agent": ["chat"],
}


def role_capabilities(cfg=None) -> dict[str, list[str]]:
    """Role -> required capabilities (configured routing wins over defaults)."""
    routing = getattr(cfg, "model_routing", None) if cfg is not None else None
    if routing is None:
        return dict(ROLE_CAPABILITIES)
    default = list(getattr(routing, "default_capabilities", None) or ["chat"])
    configured = dict(getattr(routing, "role_capabilities", None) or {})
    return {role: list(configured.get(role) or default)
            for role in ROLE_CAPABILITIES}


def role_assignments(providers: ProviderManager, cfg=None) -> list[dict]:
    """Which provider/model would serve each logical role right now."""
    caps_by_role = role_capabilities(cfg)
    out = []
    for role, caps in caps_by_role.items():
        p = providers.select(capabilities=caps)
        out.append({"role": role, "capabilities": sorted(caps),
                    "provider": p.name if p else None,
                    "model": p.cfg.model if p else None})
    return out


def persist_goal(goal: str, subs: list[dict], store: TaskStore,
                 priority: int = 5) -> list[dict]:
    """Persist a goal durably on the board: goal milestone + ready subtasks.

    Because everything lives in SQLite, a crash before the scheduler runs is
    survivable — after a restart the ready subtasks are picked up exactly like
    any other board work. Priority is uniform so claim order is plan order;
    sequencing is expressed through dependencies, never by priority tricks.
    """
    gid = store.add_task(title=goal[:120] or "goal", description=goal,
                         kind="goal", priority=0, status="done")
    out: list[dict] = []
    for s in subs:
        detail = s.get("detail") or s.get("title") or ""
        files = [f for f in (s.get("owned_files") or extract_owned_files(detail)) if f]
        role = s.get("agent_role") or DEFAULT_SUBTASK_ROLE
        title = (s.get("title") or goal)[:120]
        tid = store.add_task(title=title, description=detail, kind="subtask",
                             owned_files=files, dependencies=[gid],
                             priority=priority, agent_role=role)
        store.mark_ready(tid)
        out.append({"id": tid, "goal_id": gid, "title": title, "files": files,
                    "agent_role": role, "status": "ready"})
    # Optional sequencing: a plan item may name earlier items it must wait for
    # ("after": [0] or "dependencies": [0]) — indices into this same plan.
    import json as _json
    for i, s in enumerate(subs):
        after = s.get("after") or s.get("dependencies") or []
        deps = [out[j]["id"] for j in after
                if isinstance(j, int) and 0 <= j < len(out) and j != i]
        if deps:
            store._update(out[i]["id"],
                          dependencies=_json.dumps([gid] + deps))
    return out


class MasterController:
    """Owns the scheduler + in-process executor for one board and workspace."""

    def __init__(self, store: TaskStore, providers: ProviderManager,
                 workspace_root: str, cfg=None, events: EventBus | None = None,
                 resources=None, max_tasks: int = 2, run_tests: bool = True,
                 poll_interval_s: float = 0.25,
                 heartbeat_interval_s: float = 10.0,
                 retry_backoff_s: float | None = None,
                 worker_id: str = "master"):
        self.store = store
        self.providers = providers
        self.workspace_root = workspace_root
        self.worker_id = worker_id
        self.cfg = cfg
        self.events = events or EventBus()
        self.scheduler = Scheduler(store, providers, self.events, cfg=cfg,
                                   worker_id=worker_id, resources=resources)
        self.executor = TaskExecutor(
            self.scheduler, workspace_root, max_tasks=max_tasks,
            run_tests=run_tests, poll_interval_s=poll_interval_s,
            heartbeat_interval_s=heartbeat_interval_s,
            retry_backoff_s=retry_backoff_s)

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> "MasterController":
        """Start claiming/executing and the scheduler's recovery loop."""
        if not self.executor.running:
            self.executor.start()
        self.scheduler.start()
        self.events.emit("master", status="started", agent_id=self.worker_id,
                         detail=f"max_tasks={self.executor.max_tasks}")
        return self

    def stop(self, release: bool = True) -> None:
        """Stop claiming work. With ``release`` the worker's claims are handed
        back to the board so an interrupted run is resumable, never stuck."""
        self.executor.stop()
        self.scheduler.stop()
        if release:
            self.store.release_all_for_worker(self.scheduler.worker_id,
                                              self.scheduler.max_attempts)
        self.events.emit("master", status="stopped", agent_id=self.worker_id)

    @property
    def running(self) -> bool:
        return self.executor.running

    # -- planning / submission ----------------------------------------------
    def pipeline(self) -> AgentPipeline:
        from .config import Config
        return AgentPipeline(self.providers, self.store, events=self.events,
                             cfg=self.cfg if isinstance(self.cfg, Config) else None)

    def plan(self, goal: str, workspace_summary: str = "") -> dict:
        """Turn a goal into an ordered sub-task list (planner logical agent)."""
        return self.pipeline().plan_task(goal, workspace_summary)

    def submit(self, goal: str, subs: list[dict] | None = None,
               start: bool = True) -> dict:
        """Plan (unless given) and persist the durable task graph."""
        goal = (goal or "").strip()
        if not goal:
            return {"ok": False, "status": "error", "error": "empty goal"}
        if subs is None:
            res = self.plan(goal)
            if not res.get("ok"):
                return {"ok": False, "status": "error",
                        "error": res.get("error") or "planning failed"}
            subs = res.get("tasks") or []
        if not subs:
            return {"ok": False, "status": "error",
                    "error": "planner produced no sub-tasks"}
        nodes = persist_goal(goal, subs, self.store)
        run_id = f"run-{int(time.time() * 1000)}"
        run = {"ok": True, "status": "queued", "run_id": run_id, "goal": goal,
               "goal_task": nodes[0]["goal_id"] if nodes else None,
               "subtasks": nodes,
               "subtask_ids": [n["id"] for n in nodes]}
        self.events.emit("master", status="submitted", agent_id=self.worker_id,
                         detail=f"{len(nodes)} sub-task(s) queued")
        if start:
            run["status"] = "running"
            self.start()
        return run

    def run(self, goal: str, timeout_s: float = 180.0,
            subs: list[dict] | None = None, start: bool = True) -> dict:
        """Submit and drive the workflow to completion (bounded by timeout)."""
        run = self.submit(goal, subs=subs, start=start)
        if not run.get("ok") or not start:
            return run
        run["wait"] = self.wait(run["subtask_ids"], timeout_s=timeout_s)
        run["report"] = self.report(run["subtask_ids"])
        run["status"] = "done" if run["report"]["ok"] else (
            "running" if run["wait"]["timeout"] else "failed")
        return run

    def wait(self, task_ids: list[int], timeout_s: float = 180.0,
             poll_s: float = 0.2) -> dict:
        """Block until every task is terminal (or the deadline passes)."""
        deadline = time.time() + max(0.0, timeout_s)
        while True:
            states = {tid: (self.store.get(tid) or {}).get("status")
                      for tid in task_ids}
            pending = [s for s in states.values() if s not in TERMINAL]
            if not pending:
                return {"ok": True, "timeout": False, "states": states}
            if time.time() >= deadline:
                return {"ok": False, "timeout": True, "states": states}
            time.sleep(poll_s)

    # -- control -------------------------------------------------------------
    def cancel(self, task_id: int, by: str = "master") -> list[int]:
        affected = self.scheduler.cancel(task_id, by=by)
        self.events.emit("master", status="cancelled", agent_id=self.worker_id,
                         task_id=task_id, detail=f"cancelled {affected}")
        return affected

    # -- introspection -------------------------------------------------------
    def _task_ids_for_goal(self, goal_id: int) -> list[int]:
        return sorted(t["id"] for t in self.store.list(kind="subtask", limit=2000)
                      if goal_id in (t.get("dependencies") or []))

    def tasks_for_goal(self, goal_id: int) -> list[dict]:
        """Every durable sub-task row belonging to a goal milestone."""
        return [self.store.get(t) for t in self._task_ids_for_goal(goal_id)]

    def subtask_ids(self, run: dict) -> list[int]:
        if run.get("subtask_ids"):
            return list(run["subtask_ids"])
        return self._task_ids_for_goal(run.get("goal_task"))

    def stages(self, task_ids: list[int] | None = None) -> list[str]:
        """Logical agents that actually ran for this run (ordered, unique)."""
        out: list[str] = []
        for ev in self.events.recent(5000, event_type="agent.run"):
            if ev.get("status") != "started":
                continue
            if task_ids and ev.get("task_id") not in task_ids:
                continue
            role = ev.get("agent_id")
            if role and role not in out:
                out.append(role)
        return out

    def report(self, task_ids: list[int]) -> dict:
        """What actually happened: states, agents, providers, files, checks."""
        from .workspace import Workspace
        ws = Workspace(self.workspace_root)
        tasks = [self.store.get(t) for t in task_ids]
        tasks = [t for t in tasks if t]
        nodes = []
        for t in tasks:
            written = [f for f in (t.get("owned_files") or []) if ws.exists(f)]
            nodes.append({
                "id": t["id"], "title": t["title"], "status": t["status"],
                "agent_role": t.get("agent_role"),
                "provider": t.get("provider"), "model": t.get("model"),
                "attempts": t.get("attempts"),
                "owned_files": t.get("owned_files") or [],
                "files_written": written,
                "tests": t.get("test_status"),
                "result": (t.get("result") or "")[:600],
                "error": (t.get("last_error") or "")[:300] or None,
            })
        done = [n for n in nodes if n["status"] in ("completed", "done")]
        bad = [n for n in nodes if n["status"] in ("failed", "dependency_failed",
                                                  "cancelled")]
        return {
            "ok": bool(nodes) and len(done) == len(nodes),
            "run_worker": self.scheduler.worker_id,
            "tasks": nodes,
            "completed": len(done),
            "failed": len(bad),
            "files_changed": sorted({f for n in nodes for f in n["files_written"]}),
            "stages": self.stages(task_ids),
            "providers": self.providers.health_report(),
            "provider_failures": sum(p.get("failures", 0)
                                     for p in self.providers.health_report()),
            "executor_stats": dict(self.executor.stats),
        }

    def agents(self) -> list[dict]:
        """Logical roles, their capability needs, and the provider serving each."""
        return role_assignments(self.providers, self.cfg)

    def status(self, probe: bool = False) -> dict:
        """Control-plane snapshot. ``probe`` contacts each provider first so
        the report never claims a backend is healthy without asking it."""
        return {
            "running": self.running,
            "worker": self.scheduler.worker_id,
            "max_tasks": self.executor.max_tasks,
            "inflight": self.executor.inflight(),
            "budget": self.scheduler.current_budget(),
            "counts": self.store.counts(),
            "executor_stats": dict(self.executor.stats),
            "agents": self.agents(),
            "providers": self.providers.health_report(probe=probe),
            "stages_seen": self.stages(),
        }
