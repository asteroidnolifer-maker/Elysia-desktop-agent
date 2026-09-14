"""OpenReacher integration for Elysia.

OpenReacher is the open-source deep-research agent pattern made popular by
openreacher/deep-research-style projects: refine a research direction across
bounded breadth/depth levels, gathering sources and synthesizing a cited
report. Elysia implements this natively in ``elysia.core.research``
(``ResearchEngine.run_deep``); this module is the first-class adapter so
docs, tools and CLI can reference "openreacher" directly.
"""
from __future__ import annotations

import os

from elysia.core.research import (  # noqa: F401  (re-exports for compat)
    DuckDuckGoSearch, OfflineSearch, ResearchEngine, SearchProvider,
    build_search,
)


class OpenReacher:
    """Breadth/depth deep-research agent (openreacher-style)."""

    def __init__(self, providers, memory=None, events=None, search=None,
                 max_sources: int = 5, output_dir: str = ""):
        from elysia.core.memory import Memory
        self.engine = ResearchEngine(
            providers,
            memory=memory or Memory(os.path.join(output_dir or ".", "state")),
            events=events, search=search,
            max_sources=max_sources, output_dir=output_dir)

    def research(self, question: str, format_spec: str = "", breadth: int = 2,
                 depth: int = 1, task_id=None, correlation_id=None) -> dict:
        return self.engine.run_deep(question, format_spec=format_spec,
                                    breadth=breadth, depth=depth,
                                    task_id=task_id,
                                    correlation_id=correlation_id)

    # convenience alias consistent with the ResearchEngine API
    def run(self, question: str, **kw) -> dict:
        return self.research(question, **kw)


def openreacher_research(question: str, cfg=None, breadth: int = 2,
                         depth: int = 1, output_dir: str = "") -> dict:
    """One-shot helper: run openreacher with the default configured backend."""
    from elysia.core.config import load_config
    from elysia.core.memory import Memory
    from elysia.core.providers import ProviderManager
    cfg = cfg or load_config()
    from elysia.core.research import build_search
    pm = ProviderManager()
    pm.register_many(cfg.providers)
    orx = OpenReacher(
        pm,
        memory=Memory(os.path.join(output_dir or ".", "state", "memory"),
                      max_entries=cfg.memory.max_entries),
        search=build_search(cfg),
        max_sources=cfg.research.max_sources,
        output_dir=output_dir or ".")
    return orx.research(question, breadth=breadth, depth=depth)