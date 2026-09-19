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

import os
import re
import time

from .agents import AgentPipeline
from .config import Config
from .events import EventBus
from .inference import LocalModelPool, ModelRouter
from .resources import ResourceLedger, ResourceMonitor, ResourcePolicy
from .executor import TaskExecutor
from .graph import analyze as analyze_graph
from .graph import find_cycles, replan as replan_graph
from .graph import summary as graph_summary
from .health import dimensions as health_dimensions
from .memory import Memory
from .providers import ProviderManager
from .scheduler import Scheduler
from .tasks import TERMINAL, TaskStore
from .toolkit import build_tools, tool_audit
from .workspace import Workspace

# Role that owns the file-writing stage of a planned sub-task. The other
# logical agents (planner/tester/code_reviewer) run inside the pipeline.
DEFAULT_SUBTASK_ROLE = "implementer"

_FILE_RE = re.compile(
    r"[\w./-]+\.(?:py|md|rs|go|js|ts|tsx|jsx|sh|yaml|yml|json|toml|sql|css|html)",
    re.I)


def extract_owned_files(text: str | None, limit: int = 8) -> list[str]:
    """Owned-file hints from a plan item (never traversal, never absolute).

    One canonical implementation lives in ``elysia.core.graph`` so the planner
    path, the graph analyser and the master all agree on what a file reference
    is.
    """
    from .graph import files_in
    return files_in(text, limit=limit)


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


def dependency_cycles(subs: list[dict]) -> list[list[int]]:
    """Plan items that depend on each other in a cycle (Phase 3, item 91).

    ``subs[i]['after']``/``['dependencies']`` are indices into the same plan.
    Delegates to the canonical analyser (``elysia.core.graph.find_cycles``).
    """
    nodes = [{"index": i,
              "after": [j for j in (s.get("after") or s.get("dependencies")
                                    or []) if isinstance(j, int)]}
             for i, s in enumerate(subs)]
    return find_cycles(nodes)


def _resolve_memory_dir(configured: str | None, workspace_root: str) -> str:
    """Where this controller's memory lives.

    A RELATIVE configured dir is resolved against the project root (the parent
    of the workspace), never against the current working directory — otherwise
    a controller run from elsewhere would silently write into (or read) an
    unrelated project's memory.
    """
    project_root = os.path.dirname(os.path.abspath(workspace_root))
    if not configured:
        return os.path.join(project_root, "state", "memory")
    if os.path.isabs(configured):
        return configured
    return os.path.join(project_root, configured)


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
    # A goal milestone is not worker output, but it must still carry a result:
    # the HUD renders "(no result yet)" for a done row with an empty result,
    # which made a completed milestone look like a broken task.
    store._update(gid, result=(
        f"goal milestone — {len(subs)} sub-task(s) queued; "
        "see them on the board for live progress"))
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
                 worker_id: str = "master", tools=None):
        self.store = store
        self.providers = providers
        self.workspace_root = workspace_root
        self.worker_id = worker_id
        self.cfg = cfg
        self.resources = resources
        self.events = events or EventBus()
        # Provider circuit transitions (provider.quarantined / half_open /
        # recovered) belong on the same timeline as everything else.
        try:
            self.providers.set_events(self.events)
        except AttributeError:  # a duck-typed manager without the hook
            pass
        # One layered memory per controller (shared with the executor's
        # pipelines) so failures/solutions/decisions accumulate across tasks.
        _mem_cfg = getattr(cfg, "memory", None)
        self.memory = Memory(
            _resolve_memory_dir(getattr(_mem_cfg, "dir", None), workspace_root),
            max_entries=int(getattr(_mem_cfg, "max_entries", 20000) or 20000))
        # The canonical permissioned tool layer the agents write files through.
        # ``tools.enabled=false`` is the documented escape hatch back to direct
        # (still path-validated) workspace writes.
        if tools is not None:
            self.tools = tools
        elif getattr(getattr(cfg, "tools", None), "enabled", True):
            self.tools = build_tools(Workspace(workspace_root), self.events, cfg)
        else:
            self.tools = None
        # -- resource-aware execution layer (see RESOURCE_ARCHITECTURE.md) ---
        # ONE monitor, ONE policy, ONE ledger and ONE local-model pool for the
        # whole controller. Dozens of logical agents share them; the number of
        # expensive operations stays tiny (heavy_slots=1 by default).
        rc = getattr(cfg, "resources", None)
        self.monitor = ResourceMonitor(
            sample_interval_s=float(getattr(rc, "monitor_sample_interval_s",
                                            1.0) or 1.0))
        self.policy = ResourcePolicy.from_config(cfg)
        self.ledger = ResourceLedger.from_config(cfg, monitor=self.monitor,
                                                 policy=self.policy)
        self.pool = LocalModelPool.from_config(providers, ledger=self.ledger,
                                               monitor=self.monitor,
                                               events=self.events, cfg=cfg)
        self.router = ModelRouter.from_config(providers, pool=self.pool,
                                              ledger=self.ledger,
                                              monitor=self.monitor,
                                              policy=self.policy,
                                              events=self.events, cfg=cfg)
        self.scheduler = Scheduler(store, providers, self.events, cfg=cfg,
                                   worker_id=worker_id, resources=resources,
                                   ledger=self.ledger, monitor=self.monitor,
                                   policy=self.policy,
                                   warm=self.pool.warm,
                                   router=self.router)
        self.executor = TaskExecutor(
            self.scheduler, workspace_root, max_tasks=max_tasks,
            run_tests=run_tests, poll_interval_s=poll_interval_s,
            heartbeat_interval_s=heartbeat_interval_s,
            retry_backoff_s=retry_backoff_s, tools=self.tools,
            memory=self.memory, resources=resources,
            router=self.router, pool=self.pool)

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> "MasterController":
        """Start claiming/executing and the scheduler's recovery loop."""
        if not self.executor.running:
            self.executor.start()
        self.scheduler.start()
        self.pool.start()
        self.events.emit(
            "master", status="started", agent_id=self.worker_id,
            detail=f"max_tasks={self.executor.max_tasks} "
                   f"local_model_slots={self.pool.max_concurrent} "
                   f"heavy_slots={self.ledger.limits.get('local_llm')}")
        return self

    def stop(self, release: bool = True) -> None:
        """Stop claiming work. With ``release`` the worker's claims are handed
        back to the board so an interrupted run is resumable, never stuck."""
        self.executor.stop()
        self.scheduler.stop()
        self.pool.stop()
        if release:
            self.store.release_all_for_worker(self.scheduler.worker_id,
                                              self.scheduler.max_attempts)
        self.events.emit("master", status="stopped", agent_id=self.worker_id)

    @property
    def running(self) -> bool:
        return self.executor.running

    # -- planning / submission ----------------------------------------------
    def pipeline(self) -> AgentPipeline:
        return AgentPipeline(
            self.providers, self.store, events=self.events,
            cfg=self.cfg if isinstance(self.cfg, Config) else None,
            memory=self.memory, resources=self.resources, tools=self.tools,
            router=self.router)

    # -- resource / queue reporting ------------------------------------------
    def resource_report(self) -> dict:
        """Who is running, what is queued, and WHY nothing else can start."""
        r = self.scheduler.resource_status()
        r["pool"] = self.pool.status()
        r["router"] = self.router.status()
        r["providers"] = self.providers.resource_summary()
        warm = r["pool"].get("warm") or {}
        r["models"] = [{"provider": k, **v} for k, v in warm.items()]
        return r

    def queue_report(self) -> dict:
        """Every not-yet-started task with its blocking reason."""
        waiting = self.scheduler.why_waiting()
        running = [t for status in ("claimed", "running", "testing", "reviewing")
                   for t in self.store.list(status=status, limit=50)]
        pool = self.pool.status()
        return {"waiting": waiting,
                "running": [{"task_id": t["id"], "title": (t.get("title") or "")[:80],
                             "status": t["status"],
                             "priority_class": t.get("priority_class"),
                             "resource_class": t.get("resource_class"),
                             "worker": t.get("worker"),
                             "provider": t.get("provider"),
                             "model": t.get("model")} for t in running],
                "local_slot": {"slots": pool.get("slots"),
                               "running": len(pool.get("running") or []),
                               "queued": pool.get("queued_count"),
                               "not_held": self.ledger.counts().get("local_llm", 0)},
                "resources": self.scheduler.resource_status()["snapshot"]}

    def efficiency_report(self, task_id: int | None = None,
                          limit: int = 10) -> dict:
        """AI calls vs deterministic checks per task — the real cost picture."""
        rows = []
        tasks = ([self.store.get(task_id)] if task_id is not None
                 else self.store.list(limit=limit))
        for t in tasks:
            if not t:
                continue
            usage = t.get("usage_json") or {}
            rows.append({
                "task_id": t["id"],
                "title": (t.get("title") or "")[:70],
                "status": t["status"],
                "resource_class": t.get("resource_class"),
                "priority_class": t.get("priority_class"),
                "ai_calls": int(usage.get("requests") or 0),
                "deterministic_checks": int(usage.get("deterministic_checks")
                                            or usage.get("checks") or 0),
                "tokens_in": int(usage.get("tokens_in") or 0),
                "tokens_out": int(usage.get("tokens_out") or 0),
                "ai_seconds": round(float(usage.get("latency_s") or 0.0), 2),
                "failures": int(usage.get("failures") or 0),
                "retries": int(t.get("retries") or 0),
                "estimated_cost_usd": round(float(t.get("cost_usd") or 0.0), 6),
            })
        totals = {k: round(sum(r[k] for r in rows), 3) if k.endswith(("s", "usd"))
                  else sum(r[k] for r in rows)
                  for k in ("ai_calls", "deterministic_checks", "tokens_in",
                            "tokens_out", "ai_seconds", "failures", "retries",
                            "estimated_cost_usd")}
        return {"tasks": rows, "totals": totals,
                "note": "token counts are estimates; checks are real tool runs"}

    def workspace_summary(self) -> str:
        """What repository are we in, and how is it built (project intel).

        Without this the planner plans blind; with it, plans name real files and
        the right test command.
        """
        try:
            from .project import ProjectIntel
            return ProjectIntel(self.workspace_root).to_context()
        except Exception:  # noqa: BLE001 — intel must never block planning
            return ""

    def plan(self, goal: str, workspace_summary: str = "") -> dict:
        """Turn a goal into an ordered sub-task list (planner logical agent).

        The result is then treated as a GRAPH: dependencies, file ownership and
        executability are checked, and only the repairs that are safe and
        mechanical are applied (dropping unknown/cyclic dependencies, giving a
        file one owner, splitting oversized tasks). Every repair is reported in
        ``repairs`` — never applied silently.
        """
        if not workspace_summary:
            workspace_summary = self.workspace_summary()
        res = self.pipeline().plan_task(goal, workspace_summary)
        if not res.get("ok"):
            return res
        caps = role_capabilities(self.cfg)
        tasks = res.get("tasks") or []
        analysis = analyze_graph(tasks, root=self.workspace_root,
                                 providers=self.providers, role_caps=caps)
        repairs = {"changes": [], "before": len(tasks), "after": len(tasks)}
        if analysis["issues"]:
            attempt = replan_graph(tasks, issues=analysis["issues"],
                                   root=self.workspace_root)
            if attempt["changes"]:
                repairs = attempt
                tasks = attempt["plan"]
                analysis = analyze_graph(tasks, root=self.workspace_root,
                                         providers=self.providers, role_caps=caps)
        res["raw_tasks"] = res.get("tasks") or []
        res["tasks"] = tasks
        res["graph"] = analysis
        res["repairs"] = repairs
        self.events.emit("goal.planned",
                         status="ok" if analysis["ok"] else "warn",
                         detail=graph_summary(analysis))
        try:
            self.memory.remember_decision(
                f"plan graph for: {goal[:160]}",
                graph_summary(analysis) + (
                    "; repairs: " + "; ".join(repairs["changes"]) if
                    repairs["changes"] else ""),
                actor="master", tags=["plan", "graph"])
        except Exception:  # noqa: BLE001
            pass
        return res

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

    # -- planning simulation (Phase 61) --------------------------------------
    def simulate(self, goal: str, subs: list[dict] | None = None,
                 plan_with_model: bool = True) -> dict:
        """Dry-run a goal. Writes NOTHING: no workspace files, no board rows,
        no scheduler start. Answers what *would* happen, who would do it, which
        provider would answer, whether the roles may write, and what is wrong
        with the plan (orphan tasks, unservable roles, conflicting ownership,
        circular dependencies).
        """
        goal = (goal or "").strip()
        if not goal:
            return {"ok": False, "mode": "simulation", "error": "empty goal"}
        raw_subs, repairs = None, {"changes": [], "before": 0, "after": 0}
        if subs is None:
            if not plan_with_model:
                return {"ok": False, "mode": "simulation",
                        "error": "no sub-tasks supplied and model planning disabled"}
            res = self.plan(goal)
            if not res.get("ok"):
                return {"ok": False, "mode": "simulation",
                        "error": res.get("error") or "planning failed"}
            raw_subs = res.get("raw_tasks") or []
            repairs = res.get("repairs") or repairs
            subs = res.get("tasks") or []
        if not subs:
            return {"ok": False, "mode": "simulation",
                    "error": "planner produced no sub-tasks"}
        caps_by_role = role_capabilities(self.cfg)
        # One canonical analyser decides ownership conflicts, cycles, oversized
        # and unservable tasks (elysia.core.graph) — no second opinion here.
        analysis = analyze_graph(subs, root=self.workspace_root,
                                 providers=self.providers,
                                 role_caps=caps_by_role)
        graph_issues = {}
        for issue in analysis["issues"]:
            for idx in issue["nodes"] or [-1]:
                graph_issues.setdefault(idx, []).append(issue)
        nodes = []
        for i, s in enumerate(subs):
            detail = s.get("detail") or s.get("title") or ""
            files = [f for f in (s.get("owned_files")
                                 or extract_owned_files(detail)) if f]
            role = s.get("agent_role") or DEFAULT_SUBTASK_ROLE
            caps = list(caps_by_role.get(role) or ["chat"])
            routing = self.providers.explain(capabilities=caps)
            granted = self.tools.grant(role) if self.tools else []
            can_write = "workspace:write" in granted
            issues = [{"kind": g["kind"], "blocking": g["severity"] == "blocker",
                       "severity": g["severity"], "detail": g["detail"],
                       "fix": g.get("fix", "")}
                      for g in graph_issues.get(i, [])]
            if not can_write:
                issues.append({"kind": "no_write_permission", "blocking": True,
                               "severity": "blocker",
                               "detail": f"role '{role}' cannot write files "
                                         f"(ceiling denies workspace:write)",
                               "fix": "grant workspace:write to this role"})
            nodes.append({
                "index": i, "title": (s.get("title") or goal)[:120],
                "agent_role": role, "owned_files": files,
                "required_capabilities": sorted(caps),
                "provider": routing.get("selected"), "model": routing.get("model"),
                "routing_reason": routing.get("reason"),
                "permissions": granted, "can_write": can_write,
                "after": [j for j in (s.get("after") or s.get("dependencies") or [])
                          if isinstance(j, int)],
                "issues": issues})
        # What the RAW plan (before repair) got wrong is reported too, so a
        # silent auto-repair can never hide a badly planned goal.
        raw_analysis = (analyze_graph(raw_subs, root=self.workspace_root,
                                      providers=self.providers,
                                      role_caps=caps_by_role)
                        if raw_subs else analysis)

        def _dedup(issues: list) -> list:
            seen, out = set(), []
            for i in issues:
                key = (i["kind"], i.get("detail"))
                if key not in seen:
                    seen.add(key)
                    out.append(i)
            return out

        conflicts = _dedup([i for i in raw_analysis["issues"]
                            if i["kind"] == "duplicate_file_ownership"]
                           + [i for i in analysis["issues"]
                              if i["kind"] == "duplicate_file_ownership"])
        cycles = _dedup(
            [{"kind": "circular_dependency", "blocking": True,
              "severity": "blocker", "nodes": i["nodes"], "tasks": i["nodes"],
              "detail": f"dependency cycle among plan items {i['nodes']}"}
             for i in raw_analysis["issues"]
             if i["kind"] == "circular_dependency"]
            + [{"kind": "circular_dependency", "blocking": True,
                "severity": "blocker", "nodes": i["nodes"], "tasks": i["nodes"],
                "detail": f"dependency cycle among plan items {i['nodes']}"}
               for i in analysis["issues"]
               if i["kind"] == "circular_dependency"])
        # ``blocked`` describes what would ACTUALLY run — i.e. the plan after
        # repair. What the raw planner output got wrong stays visible in
        # ``conflicts``/``circular_dependencies``/``raw_blockers``.
        blocked = [{"index": n["index"], **i} for n in nodes for i in n["issues"]
                   if i["blocking"]]
        raw_blockers = [i for i in raw_analysis["issues"]
                        if i["severity"] == "blocker"]
        return {"ok": not blocked, "mode": "simulation", "goal": goal,
                "nodes": nodes,
                "files_that_would_change": sorted(
                    {f for n in nodes for f in n["owned_files"]}),
                "conflicts": conflicts, "circular_dependencies": cycles,
                "blocked": blocked,
                "issues": analysis["issues"],
                "raw_issues": raw_analysis["issues"],
                "raw_blockers": raw_blockers,
                "repairs": repairs,
                # For an EXPLICIT plan we never rewrite the caller's graph; we
                # show what the analyser would repair so it can be applied
                # deliberately (replan() is the same function the planner path
                # uses automatically).
                "suggested_repairs": (
                    replan_graph(raw_subs, issues=raw_analysis["issues"],
                                 root=self.workspace_root)["changes"]
                    if raw_subs else replan_graph(
                        subs, issues=analysis["issues"],
                        root=self.workspace_root)["changes"]),
                "raw_task_count": len(raw_subs or subs),
                "estimates": analysis["estimates"],
                "would_create_tasks": len(nodes), "writes": 0,
                "executor_started": False,
                "budget": self.scheduler.current_budget(),
                "providers": self.providers.health_report(),
                "note": "simulation only — nothing was written to the workspace, "
                        "the task board or the scheduler"}

    def explain_routing(self, capabilities=None) -> dict:
        """Why the manager would pick a given provider/model right now."""
        return self.providers.explain(capabilities=capabilities,
                                      avoid_models=None)

    def health(self) -> dict:
        """Independent health dimensions (no aggregate score)."""
        return health_dimensions(self, tools=self.tools, cfg=self.cfg)

    def tools_report(self) -> list[dict]:
        """The canonical tool surface with risk + required permissions."""
        return self.tools.describe() if self.tools else []

    def tool_permissions(self, role: str = "implementer") -> dict:
        """What one logical role may invoke, and why anything is refused."""
        if not self.tools:
            return {"role": role, "granted": [], "allowed": [], "denied": []}
        return tool_audit(self.tools, role)

    def report(self, task_ids: list[int]) -> dict:
        """What actually happened: states, agents, providers, files, checks."""
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
            "tools_available": len(self.tools.registry.names()) if self.tools else 0,
            "file_changes": [e.get("detail") for e in self.events.recent(500)
                             if e.get("event_type") == "file.changed"],
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
            "provider_availability": self.providers.availability_report(),
            "stages_seen": self.stages(),
            "health": self.health(),
            "tools": len(self.tools.registry.names()) if self.tools else 0,
        }
