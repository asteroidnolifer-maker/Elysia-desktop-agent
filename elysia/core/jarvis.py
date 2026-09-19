"""Jarvis entry point: one natural-language front door for Elysia.

``route(text)`` classifies the operator's request into an action:

  environment— questions about THIS machine/repos ("what github repos do i own?")
               answered by inspecting real local state, never by the model
  progress   — follow-ups about a submitted goal ("is it done?", "any progress?")
  briefing   — status/capability questions ("what's running?", "are we ok?")
  knowledge  — tooling/authorization questions ("which tool scans ports?")
  research   — open questions needing the web ("what changed in CVE-X?")
  goal       — build/fix requests ("add feature X to the exporter")
  chat       — everything else: conversational answer

Design: tiny, explainable keyword/regex heuristics (no model call to decide
how to call a model), each route returns what it did so the CLI/HUD can show
the operator exactly what happened. Fails soft: every route catches its own
errors and reports them in the response dict.
"""
from __future__ import annotations

import re

# (route, pattern) — first match wins
_ROUTES: list[tuple[str, re.Pattern]] = [
    # Questions about the operator's own machine/repos. These must be answered
    # from real local state (git remotes, gh, workspace) — the local model
    # otherwise invents refusals like "I don't have access to your GitHub".
    ("environment", re.compile(
        r"\b(what|which|where|list|show) .{0,30}"
        r"(repos?|repositories|remotes?|github|gitlab|checkout|workspace)\b|"
        r"\bmy (repos?|repositories|remotes?|github)\b|"
        r"\brepos? (do|can) i (own|have|access)\b|"
        r"\bwhat('| i)?s my (branch|remote|repo)\b|"
        r"\bwhere (is|are) (the|my) (repo|checkout|project)\b", re.I)),
    # Follow-ups about a submitted goal — answered from durable board state.
    ("progress", re.compile(
        r"\b(is|are|was|were) (it|that|they|we|the tasks?|the jobs?) "
        r"(done|finished|complete|completed|ready)\b|"
        r"\b(done|finished|complete|completed) yet\b|"
        r"\b(any|what|how much) (progress|update|status on (it|that))\b|"
        r"\bdid (it|that|they) (finish|complete|work|succeed|fail)\b|"
        r"\bhow('| i)?s (it|that|the (goal|task|workflow|job)) "
        r"(going|coming|doing)\b|"
        r"\bwhat happened (to|with) (it|that|the (goal|task|job))\b|"
        r"\bstill (running|working|going)\b", re.I)),
    ("briefing", re.compile(
        r"\b(status|how are (we|things)|what('| i)?s running|any (tasks|work)"
        r"|board|are we (ok|good)|briefing|report in|capabilities?|"
        r"what can you do|installed tools?)\b", re.I)),
    ("knowledge", re.compile(
        r"\b(which|what) tool\b|how (do|should) i (scan|test|audit|check)\b|"
        r"\b(pentest|scan|audit) .*\b(authoriz|legal|allowed|permission)\b|"
        r"\bauthorized use\b|\bis (nmap|hydra|sqlmap|metasploit|wireshark|"
        r"nuclei|gobuster|sherlock|volatility|yara|radare)\b", re.I)),
    ("research", re.compile(
        r"\b(research|look up|find out|latest|news|who is|what is the "
        r"difference|compare)\b", re.I)),
    ("goal", re.compile(
        r"\b(add|implement|build|fix|refactor|create|write|migrate|update)\b"
        r"\s+(a |an |the )?[\w-]+", re.I)),
]


def classify(text: str) -> str:
    """The route for a request: briefing|knowledge|research|goal|chat."""
    t = (text or "").strip()
    if len(t) < 3:
        return "chat"
    for name, pat in _ROUTES:
        if pat.search(t):
            return name
    return "chat"


def handle(text: str, deep: bool = False, timeout_s: float = 45.0) -> dict:
    """Route and execute a request. Returns a dict with route + result."""
    route = classify(text)
    out: dict = {"route": route, "request": (text or "")[:200]}
    try:
        if route == "environment":
            from .environment import environment_report
            out.update(ok=True, text=environment_report())
        elif route == "progress":
            from .briefing import goal_progress
            from .tasks import TaskStore
            store = None
            try:
                import os
                from .config import repo_root
                db = os.path.join(repo_root(), "orchestrator",
                                  "taskboard.sqlite")
                if os.path.exists(db):
                    store = TaskStore(db)
            except Exception:  # noqa: BLE001
                store = None
            if store is None:
                out.update(ok=False,
                           text="No task board found — no goal has been "
                                "submitted on this machine yet.")
            else:
                out.update(ok=True, text=goal_progress(store))
        elif route == "briefing":
            from .briefing import brief
            from .config import load_config
            from .providers import ProviderManager
            from .tasks import TaskStore
            store = None
            try:
                from .config import repo_root
                import os
                db = os.path.join(repo_root(), "orchestrator",
                                  "taskboard.sqlite")
                if os.path.exists(db):
                    store = TaskStore(db)
            except Exception:  # noqa: BLE001
                store = None
            pm = None
            try:
                cfg = load_config()
                pm = ProviderManager()
                pm.register_many(cfg.providers)
            except Exception:  # noqa: BLE001
                pm = None
            r = brief(text[:60], store=store, providers=pm)
            out.update(ok=r["ok"], text=r["text"], sections=r["sections"])
        elif route == "knowledge":
            from .knowledge import for_context
            digest = for_context(text, max_entries=3)
            out.update(ok=bool(digest),
                       text=digest or "No vendored knowledge matches that "
                                      "query. `elysia tools --missing` shows "
                                      "what this machine lacks.")
        elif route == "research":
            from .server_api import deep_research
            r = deep_research(text, timeout_s=timeout_s,
                              breadth=3 if deep else 2,
                              depth=2 if deep else 1)
            out.update(ok=r.get("ok", False), text=r.get("reply", ""),
                       status=r.get("status"))
        elif route == "goal":
            from .server_api import run_agent
            r = run_agent(text, timeout_s=timeout_s)
            out.update(ok=r.get("ok", False), text=r.get("reply", ""),
                       status=r.get("status"), detail=r.get("detail"))
        else:   # chat
            from .server_api import run_chat
            r = run_chat(text, timeout_s=timeout_s)
            out.update(ok=r.get("ok", False), text=r.get("reply", ""))
    except Exception as e:  # noqa: BLE001 — the front door never crashes
        out.update(ok=False, text=f"error: {type(e).__name__}: {e}")
    return out
