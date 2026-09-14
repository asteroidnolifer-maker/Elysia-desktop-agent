"""Jarvis-style briefings: one fused, honest status report for the operator.

``brief()`` combines:
  - machine capability digest (what tools actually exist — toolcatalog)
  - task-board state (counts, blocked, recent results — TaskStore)
  - provider health (which models answer — ProviderManager)
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
    return (f"Providers: {len(healthy)}/{len(rows)} healthy — {names}")


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

    # 4) focused knowledge (optional)
    if topic:
        try:
            from .knowledge import for_context
            digest = for_context(topic, max_entries=max_knowledge)
            if digest:
                sections.append(("Knowledge", digest[:1600]))
        except Exception:  # noqa: BLE001
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
