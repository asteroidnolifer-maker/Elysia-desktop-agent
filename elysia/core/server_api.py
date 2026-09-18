"""Safe HTTP-facing adapters for the Elysia core.

These are the ONLY entry points the web server should call. They keep each
HTTP request bounded (timeouts, size caps), drive the master control plane
(``elysia.core.master``), and always return JSON-serializable results with
graceful failure — never raise, never execute provider calls on the caller's
thread for longer than the cap.
"""
from __future__ import annotations

import os
import sys
import threading

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from elysia.core.config import load_config  # noqa: E402
from elysia.core.master import (  # noqa: E402
    MasterController, extract_owned_files, persist_goal)
from elysia.core.memory import Memory  # noqa: E402
from elysia.core.providers import ProviderManager  # noqa: E402
from elysia.core.resources import ResourceManager  # noqa: E402
from elysia.core.tasks import TaskStore  # noqa: E402

MAX_GOAL_CHARS = 2000
_MAX_WAIT_S = 15


def _store_path() -> str:
    return os.path.join(REPO_ROOT, "orchestrator", "taskboard.sqlite")


# -- master control plane ------------------------------------------------------
# The controller is memoized: one scheduler + executor per process, so
# concurrency caps, provider slots and lease accounting are global rather than
# per request. It is rebuilt only when the configured provider set changes.
_MASTER: MasterController | None = None
_MASTER_SIG = None


def _provider_sig(cfg) -> tuple:
    return tuple((p.kind, p.label, p.model, p.base_url, p.concurrency)
                 for p in (cfg.providers or []))


def master() -> MasterController:
    """The process-wide master controller (goal -> agents -> completion)."""
    global _MASTER, _MASTER_SIG
    cfg = load_config()
    sig = (_provider_sig(cfg), cfg.workspace.root)
    if _MASTER is None or sig != _MASTER_SIG:
        if _MASTER is not None:
            try:
                _MASTER.stop(release=False)
            except Exception:  # noqa: BLE001
                pass
        pm = ProviderManager()
        if cfg.providers:
            pm.register_many(cfg.providers)
        _MASTER = MasterController(TaskStore(_store_path()), pm,
                                   cfg.workspace.root, cfg=cfg,
                                   resources=ResourceManager.from_config(cfg),
                                   max_tasks=2)
        _MASTER_SIG = sig
    return _MASTER


def _extract_files(text: str | None) -> list[str]:
    """Heuristic owned-file hints from a planner subtask (never traversal)."""
    return extract_owned_files(text)


def _persist_goal(goal: str, subs: list[dict],
                  store: TaskStore | None = None) -> list[dict]:
    """Persist a goal durably on the board (compatibility wrapper).

    Goal becomes a done milestone; each planned subtask is a ready board task
    depending on it. Because everything lives in SQLite, a crash before the
    scheduler runs them is survivable: after restart the ready subtasks are
    picked up by the scheduler exactly like any other board work.
    """
    return persist_goal(goal, subs or [], store or TaskStore(_store_path()))


def _master_reply(run: dict) -> str:
    """Human-readable trace of what the master actually controlled."""
    rep = run.get("report") or {}
    tasks = rep.get("tasks") or []
    lines = [f"Goal: {(run.get('goal') or '')[:160]}",
             f"Plan: {len(run.get('subtasks') or [])} sub-task(s) "
             f"persisted on the board"]
    for t in tasks[:12]:
        files = ", ".join(t.get("files_written") or []) or "-"
        lines.append(f"  #{t['id']} [{t['status']}] "
                     f"{t.get('agent_role') or 'agent'}: "
                     f"{(t.get('title') or '')[:70]} -> {files}")
        if t.get("error"):
            lines.append(f"      error: {str(t['error'])[:160]}")
    if rep.get("stages"):
        lines.append("Logical agents: " + " -> ".join(rep["stages"]))
    if rep.get("files_changed"):
        lines.append("Files changed: " + ", ".join(rep["files_changed"][:8]))
    provs = rep.get("providers") or []
    if provs:
        lines.append("Providers: " + ", ".join(
            f"{p.get('name')}({p.get('status')}, {p.get('requests')} req, "
            f"{p.get('failures')} fail)" for p in provs[:5]))
    state = ("completed" if rep.get("ok") else
             "still running" if (run.get("wait") or {}).get("timeout") else
             "not all tasks completed")
    lines.append(f"Outcome: {rep.get('completed', 0)}/{len(tasks)} completed "
                 f"({state})")
    return "\n".join(lines)


def run_agent(task: str, timeout_s: float = _MAX_WAIT_S) -> dict:
    """Run a goal through the master control plane on a bounded thread.

    Returns a dict always (never raises):
        {"ok": bool, "status": "done"|"running"|"queued"|"error",
         "reply": str, "detail": dict}
    When providers are unavailable the goal is still captured: it is enqueued
    on the task board so the scheduler can pick it up later.
    """
    task = (task or "").strip()
    if len(task) < 3:
        return {"ok": False, "status": "error", "reply": "task too short"}
    if len(task) > MAX_GOAL_CHARS:
        return {"ok": False, "status": "error",
                "reply": f"task too long (max {MAX_GOAL_CHARS} chars)"}
    holder = [None]
    errors = [None]

    def _run():
        try:
            holder[0] = master().run(task, timeout_s=timeout_s)
        except Exception as e:  # noqa: BLE001
            errors[0] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        # Bounded wait exceeded; never let HTTP hang on a downstream provider.
        # The worker thread keeps driving the workflow in this process, and the
        # task rows stay durable so the server's own executor takes over.
        return {"ok": True, "status": "running",
                "reply": "Master started the workflow; it is still running — "
                         "check the task board / HUD for the live trace."}
    if errors[0]:
        return _enqueue_or_error(task, errors[0])
    run = holder[0] or {}
    if not run.get("ok"):
        return _enqueue_or_error(task, run.get("error") or "planning failed")
    return {"ok": True, "status": run.get("status", "done"),
            "reply": _master_reply(run), "detail": run,
            "report": run.get("report")}


def run_goal(task: str, timeout_s: float = _MAX_WAIT_S) -> dict:
    """Explicit goal entry point (same master path as ``run_agent``)."""
    return run_agent(task, timeout_s=timeout_s)


def _enqueue_or_error(task: str, reason: str) -> dict:
    """If providers are down, persist the goal on the board for later pickup."""
    reason = (reason or "")[:300]
    if "provider" in reason.lower() or "unavailable" in reason.lower() \
            or "down" in reason.lower() or "reached" in reason.lower():
        try:
            store = TaskStore(_store_path())
            tid = store.add_task(title=task[:120], description=task,
                                 priority=3)
            store.mark_ready(tid)
            return {"ok": True, "status": "queued",
                    "reply": f"Goal queued as task #{tid} — agents were "
                             f"unavailable ({reason}); the scheduler will "
                             f"process it when they come back."}
        except Exception as e:  # noqa: BLE001
            reason = f"{reason}; enqueue failed: {e}"[:300]
    return {"ok": False, "status": "error", "reply": reason}


def run_chat(message: str, timeout_s: float = _MAX_WAIT_S) -> dict:
    """Simple conversational answering through the pipeline planner path."""
    return run_agent(message, timeout_s=timeout_s)


def deep_research(question: str, timeout_s: float = 45.0,
                  breadth: int = 2, depth: int = 1) -> dict:
    """Run the openreacher (breadth/depth) deep-research engine, bounded."""
    from elysia.core.openreacher import OpenReacher, build_search
    question = (question or "").strip()
    if len(question) < 3:
        return {"ok": False, "status": "error", "reply": "question too short"}
    cfg = load_config()
    holder = [None]
    errors = [None]

    def _run():
        try:
            pm = ProviderManager()
            pm.register_many(cfg.providers)
            orx = OpenReacher(
                pm, memory=Memory(cfg.memory.dir),
                search=build_search(cfg),
                max_sources=cfg.research.max_sources,
                output_dir=os.path.join(REPO_ROOT, "workspace"))
            holder[0] = orx.research(question, breadth=breadth, depth=depth)
        except Exception as e:  # noqa: BLE001
            errors[0] = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        return {"ok": True, "status": "running",
                "reply": "Deep research in progress; the report will be "
                         "written to workspace/reports/."}
    if errors[0]:
        return {"ok": False, "status": "error", "reply": errors[0][:300]}
    res = holder[0] or {}
    return {"ok": True, "status": "done",
            "reply": (res.get("report") or "")[:6000],
            "detail": {"sources": len(res.get("sources", [])),
                       "depth": res.get("depth"),
                       "report_path": res.get("report_path")}}


def research(question: str, timeout_s: float = 30.0) -> dict:
    """Run the OpenResearcher-style deep-research engine, bounded."""
    from elysia.core.research import ResearchEngine, build_search
    question = (question or "").strip()
    if len(question) < 3:
        return {"ok": False, "status": "error", "reply": "question too short"}
    cfg = load_config()
    holder = [None]
    errors = [None]

    def _run():
        try:
            pm = ProviderManager()
            pm.register_many(cfg.providers)
            eng = ResearchEngine(
                pm, memory=Memory(cfg.memory.dir),
                search=build_search(cfg),
                max_sources=cfg.research.max_sources,
                output_dir=os.path.join(REPO_ROOT, "workspace"))
            holder[0] = eng.run(question)
        except Exception as e:  # noqa: BLE001
            errors[0] = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        return {"ok": True, "status": "running",
                "reply": "Research in progress; the report will be written to "
                         "workspace/reports/."}
    if errors[0]:
        return {"ok": False, "status": "error", "reply": errors[0][:300]}
    res = holder[0] or {}
    return {"ok": True, "status": "done",
            "reply": (res.get("report") or "")[:6000],
            "detail": {"sources": len(res.get("sources", [])),
                       "report_path": res.get("report_path")}}