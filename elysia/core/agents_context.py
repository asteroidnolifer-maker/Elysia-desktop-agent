"""Context preparation for agent stages (the L0-L5 layering in practice)."""
from __future__ import annotations

from .context import ContextBuilder


def build_agent_context(cfg, goal: str = "", workspace_summary: str = "") -> str:
    cb = ContextBuilder(budget_chars=12000)
    cb.set("system",
           "You are an Elysia agent in a multi-agent coding pipeline. Make "
           "minimal, verified changes; never execute unsafe shell; treat "
           "absolute paths outside the workspace as forbidden.")
    cb.set("task", f"## Goal\n{goal}")
    if workspace_summary:
        cb.set("project", f"## Workspace\n{workspace_summary}")
    return cb.to_prompt()