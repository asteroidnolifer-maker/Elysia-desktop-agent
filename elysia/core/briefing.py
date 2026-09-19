"""Jarvis-style briefings: one fused, honest status report for the operator.

``brief()`` combines:
  - machine capability digest (what tools actually exist — toolcatalog)
  - task-board state (counts, blocked, recent results — TaskStore)
  - provider health (which models answer — ProviderManager)
  - control plane (which logical agent role runs on which provider)
  - optional focused knowledge digest for a topic (knowledge)

Design: offline-first, stdlib-only, never raises. Missing data is reported as
missing — a briefing that guesses is worse than one that admits gaps.
CLI: ``elysia brief [topic]``.
"""
from __future__ import annotations


def _board_line(store) -> str:
    counts = store.counts()
    total = counts.get("total", 0)
    active = (counts.get("ready", 0) + counts.get("claimed", 0)
              + counts.get("running", 0) + counts.get("testing", 0)
              + counts.get("reviewing", 0) + counts.get("retrying", 0))
    done = counts.get("completed", 0) + counts.get("done", 0)
    failed = counts.get("failed", 0)
    blocked = len(store.blocked_tasks())
    return (f"Tasks: {total} total, {active} active, {done} completed, "
            f"{failed} failed" + (f", {blocked} blocked" if blocked else ""))


TERMINAL_OK = {"completed", "done"}
TERMINAL_BAD = {"failed", "dependency_failed", "cancelled"}
ACTIVE = {"ready", "claimed", "running", "testing", "reviewing",
          "retrying", "queued"}


def goal_progress(store, goal_id: int | None = None, max_tasks: int = 10) -> str:
    """Trace of the latest (or named) goal and its sub-tasks.

    This is the canonical answer to "is it done?" — it reads durable board
    state, so it reports the truth even when the workflow is still running or
    a worker died. Never raises; an empty board is stated plainly.
    """
    try:
        rows = store.list(limit=4000)
    except Exception as e:  # noqa: BLE001
        return f"board unavailable: {e}"
    goals = [t for t in rows if (t.get("kind") or "task") == "goal"]
    if not goals:
        return ("No goal has been submitted yet. Submit one from the HUD "
                "chat or with `elysia master run \"<goal>\"`.")
    goals.sort(key=lambda t: t.get("id", 0), reverse=True)
    goal = None
    if goal_id is not None:
        goal = next((g for g in goals if g.get("id") == goal_id), None)
    goal = goal or goals[0]
    gid = goal.get("id")
    subs = [t for t in rows if gid in (t.get("dependencies") or [])]
    done = sum(1 for t in subs if t.get("status") in TERMINAL_OK)
    failed = sum(1 for t in subs if t.get("status") in TERMINAL_BAD)
    active = sum(1 for t in subs if t.get("status") in ACTIVE)
    total = len(subs)
    if not total:
        verdict = "no sub-tasks were planned"
    elif done == total:
        verdict = "DONE — every sub-task completed"
    elif failed and done + failed == total:
        verdict = (f"stopped — {failed} sub-task(s) failed, {done} completed")
    else:
        verdict = (f"still running — {done}/{total} sub-task(s) completed, "
                   f"{active} active, {failed} failed")
    lines = [f"Goal #{gid}: {(goal.get('title') or '')[:110]}",
             f"  {verdict}"]
    subs.sort(key=lambda t: t.get("id", 0))
    for t in subs[:max_tasks]:
        who = t.get("worker") or t.get("agent_role") or "-"
        row = (f"    #{t.get('id')} [{t.get('status')}] {who}: "
               f"{(t.get('title') or '')[:70]}")
        if t.get("last_error"):
            row += f"  (error: {str(t['last_error'])[:80]})"
        lines.append(row)
    if total > max_tasks:
        lines.append(f"    … {total - max_tasks} more sub-task(s)")
    return "\n".join(lines)


def _provider_line(pm) -> str:
    try:
        rows = pm.health_report()
    except Exception:  # noqa: BLE001
        return "Providers: unknown (health probe failed)"
    if not rows:
        return "Providers: none configured"
    healthy = [r for r in rows if r.get("status") == "healthy"]
    names = ", ".join(f"{r.get('name', '?')}({r.get('status', '?')})"
                      for r in rows[:5])
    # Never report "healthy" for a provider nobody has actually contacted.
    note = (" (unverified — probe with `elysia master status`)"
            if healthy and not any(r.get("probed") for r in healthy) else "")
    return f"Providers: {len(healthy)}/{len(rows)} healthy{note} — {names}"


def brief(topic: str = "", store=None, providers=None, workspace_root: str = "",
          max_knowledge: int = 2) -> dict:
    """Build the briefing. Returns {"text", "sections", "ok"}."""
    sections: list[str] = []
    issues = 0

    # 1) capabilities
    try:
        from .toolcatalog import capability_brief, summary
        s = summary()
        if s["installed"] < 3:
            issues += 1
        sections.append(("Capabilities", capability_brief()))
    except Exception as e:  # noqa: BLE001
        sections.append(("Capabilities", f"unavailable: {e}"))
        issues += 1

    # 2) task board
    if store is not None:
        try:
            sections.append(("Task board", _board_line(store)))
        except Exception as e:  # noqa: BLE001
            sections.append(("Task board", f"unavailable: {e}"))
            issues += 1

    # 3) providers
    if providers is not None:
        try:
            line = _provider_line(providers)
            if "none configured" in line or line.split("Providers: ")[-1].startswith("0/"):
                issues += 1
            sections.append(("Providers", line))
        except Exception as e:  # noqa: BLE001
            sections.append(("Providers", f"unavailable: {e}"))
            issues += 1

    # 3b) control plane: logical agent roles -> provider that serves them
    if providers is not None:
        try:
            from .master import role_assignments
            rows = role_assignments(providers)
            served = [r for r in rows if r["provider"]]
            if served:
                by_provider: dict[str, list[str]] = {}
                for r in served:
                    by_provider.setdefault(
                        f"{r['provider']} ({r['model']})", []).append(r["role"])
                body = "\n".join(
                    f"  {target} <- {', '.join(roles)}"
                    for target, roles in by_provider.items())
                if len(served) != len(rows):
                    body += (f"\n  unserved roles: "
                             f"{', '.join(r['role'] for r in rows if not r['provider'])}")
                sections.append(("Control plane", body))
            else:
                sections.append(("Control plane",
                                 "no provider matches any logical role — "
                                 "`elysia providers --catalog`"))
                issues += 1
        except Exception as e:  # noqa: BLE001
            sections.append(("Control plane", f"unavailable: {e}"))
            issues += 1

    # 4) focused knowledge (optional)
    if topic:
        try:
            from .knowledge import for_context
            digest = for_context(topic, max_entries=max_knowledge)
            if digest:
                sections.append(("Knowledge", digest[:1600]))
        except Exception:  # noqa: BLE001
            pass

    # 4b) live progress of the latest goal (answers "is it done?")
    if store is not None:
        try:
            progress = goal_progress(store)
            if not progress.startswith("No goal has been submitted"):
                sections.append(("Latest goal", progress))
        except Exception:  # noqa: BLE001 — a briefing must never fail
            pass

    # 5) next action
    next_action = _next_action(store, topic)
    sections.append(("Next action", next_action))

    text = "\n\n".join(f"## {name}\n{body}" for name, body in sections)
    return {"text": text, "sections": dict(sections), "ok": issues == 0}


def _next_action(store, topic: str) -> str:
    try:
        if store is not None:
            counts = store.counts()
            if counts.get("ready", 0):
                return (f"Dispatch: {counts['ready']} ready task(s) waiting "
                        "for a worker or the in-process executor.")
            if counts.get("failed", 0):
                return ("Review failures: tasks exhausted retries; inspect "
                        "last_error before re-queuing.")
            if counts.get("claimed", 0) or counts.get("running", 0):
                return "Stand by: work is executing; the HUD shows live state."
        if topic:
            return ("Run the authorized-use check first: confirm written "
                    f"scope for '{topic[:60]}' before any tooling is used.")
        return "No work queued — submit a goal via the HUD or `taskboard add`."
    except Exception:  # noqa: BLE001
        return "Board unavailable; run `elysia doctor`."
