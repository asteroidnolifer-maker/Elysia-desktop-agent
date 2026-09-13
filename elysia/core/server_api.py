"""Safe HTTP-facing adapters for the Elysia core.

These are the ONLY entry points the web server should call. They keep each
HTTP request bounded (timeouts, size caps), resolve to the new multi-agent
engine, and always return JSON-serializable results with graceful failure —
never raise, never execute provider calls on the caller's thread for > cap.
"""
from __future__ import annotations

import os
import sys
import threading

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from elysia.core.agents import AgentPipeline  # noqa: E402
from elysia.core.config import load_config  # noqa: E402
from elysia.core.memory import Memory  # noqa: E402
from elysia.core.providers import ProviderManager  # noqa: E402
from elysia.core.tasks import TaskStore  # noqa: E402

MAX_GOAL_CHARS = 2000
_MAX_WAIT_S = 15


def _store_path() -> str:
    return os.path.join(REPO_ROOT, "orchestrator", "taskboard.sqlite")


def _pipeline() -> AgentPipeline:
    cfg = load_config()
    pm = ProviderManager()
    pm.register_many(cfg.providers)
    store = TaskStore(_store_path())
    return AgentPipeline(pm, store, cfg=cfg,
                         memory=Memory(cfg.memory.dir))


def run_agent(task: str, timeout_s: float = _MAX_WAIT_S) -> dict:
    """Run a goal through the pipeline on a bounded thread.

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
            pipe = _pipeline()
            holder[0] = pipe.plan_task(task)
        except Exception as e:  # noqa: BLE001
            errors[0] = str(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        # Bounded wait exceeded; never let HTTP hang on a downstream provider.
        return {"ok": True, "status": "running",
                "reply": "Agent started on your request; check the task board "
                         "for progress."}
    if errors[0]:
        return _enqueue_or_error(task, errors[0])
    res = holder[0] or {}
    if not res.get("ok"):
        return _enqueue_or_error(task, res.get("error") or "planning failed")
    tasks = res.get("tasks") or []
    lines = [f"Planned {len(tasks)} sub-tasks:"] + [
        f"  - {t.get('title', '')}" for t in tasks[:10]]
    return {"ok": True, "status": "done", "reply": "\n".join(lines),
            "detail": {"tasks": tasks}}


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