"""Multi-agent pipeline with role-specific contexts.

Roles: planner, architect, implementer, tester, debugger, code_reviewer,
security_reviewer, documentation_agent, research_agent, integration_agent,
release_agent.

The pipeline is NOT a graph framework — it is a determinable sequence of stages
with dependency/rollback rules. Each stage:

  1. selects a provider matching the role's capabilities (with fallback)
  2. builds a role-specific prompt from the shared context
  3. emits structured events (agent.run / agent.decision)
  4. records outcomes + cost telemetry to the task
  5. lets the orchestrator decide whether to continue/retry

A failed provider call never crashes the pipeline: it transitions to "failed",
and the orchestrator decides whether to fall back to another provider, retry
with backoff, or abandon.
"""
from __future__ import annotations

import time

from .agents_context import build_agent_context
from .config import Config
from .context import ContextBuilder
from .events import EventBus
from .memory import Memory
from .providers import ProviderManager
from .resources import ResourceManager
from .tasks import TaskStore
from .telemetry import CostTracker, Correlation, ExecutionHistory


ROLES = ["planner", "architect", "implementer", "tester", "debugger",
         "code_reviewer", "security_reviewer", "documentation_agent",
         "research_agent", "integration_agent", "release_agent"]


class AgentPipelineError(Exception):
    pass


class AgentPipeline:
    def __init__(self, providers: ProviderManager, store: TaskStore,
                 resources: ResourceManager | None = None,
                 events: EventBus | None = None, cfg: Config | None = None,
                 memory: Memory | None = None,
                 correlation: Correlation | None = None,
                 execution_history: ExecutionHistory | None = None):
        self.providers = providers
        self.store = store
        self.resources = resources
        self.events = events or EventBus()
        self.cfg = cfg
        self.memory = memory or Memory(getattr(cfg, "memory", None)
                                       and cfg.memory.dir or "state/memory")
        self.correlation = correlation or Correlation()
        self.history = execution_history or ExecutionHistory()

    # -- provider selection with fallback ------------------------------------
    def _execute(self, messages, capabilities, task_id=None):
        self.events.emit("provider.selected", event_type="provider", status="ok",
                         agent_id=self.correlation.agent_role, task_id=task_id)
        text, err = self.providers.execute(messages, capabilities=capabilities,
                                           preferred=None)
        if err:
            self.events.emit("provider.fallback", status="error",
                             agent_id=self.correlation.agent_role,
                             task_id=task_id, error=err[:200])
            return None, err
        return text, ""

    def _role_caps(self, role: str) -> list[str]:
        if self.cfg:
            return self.cfg.model_routing.role_capabilities.get(
                role, self.cfg.model_routing.default_capabilities)
        return {"planner": ["chat", "reasoning"],
                "architect": ["chat", "reasoning"],
                "implementer": ["chat", "coding"],
                "tester": ["chat", "coding"],
                "debugger": ["chat", "coding", "reasoning"],
                "code_reviewer": ["chat", "reasoning"],
                "security_reviewer": ["chat", "reasoning"],
                "documentation_agent": ["chat"],
                "research_agent": ["chat", "reasoning"],
                "integration_agent": ["chat", "coding"],
                "release_agent": ["chat"]}[role]

    # -- stage: planner ------------------------------------------------------
    def plan_task(self, goal: str, workspace_summary: str = "") -> dict:
        ctx = build_agent_context(self.cfg, goal, workspace_summary)
        messages = [
            {"role": "system", "content":
                "You are the Elysia planner. Turn the goal into a concise "
                "ordered task list. Return output as plain bullet lines: "
                "'- <short title>| <detail>'. Do NOT include commentary."},
            {"role": "user", "content": ctx},
        ]
        self.events.emit("agent.run", event_type="agent", agent_id="planner",
                         status="started")
        text, err = self._execute(messages, self._role_caps("planner"))
        if err:
            return {"ok": False, "error": err}
        tasks = parse_plan(text)
        self.events.emit("agent.decision", event_type="agent", agent_id="planner",
                         status="ok", detail=f"planned {len(tasks)} sub-tasks")
        return {"ok": True, "tasks": tasks, "raw": text}

    # -- stage: architect -----------------------------------------------------
    def architect(self, plan: str, task_id=None) -> dict:
        messages = [{
            "role": "system",
            "content": "You are the Elysia architect. From this plan, produce "
                       "a concise architecture: modules, data flow, and any "
                       "risks. Return markdown sections: '## Modules', "
                       "'## Risks'.",
        }, {"role": "user", "content": plan or "No plan supplied"}]
        self.events.emit("agent.run", event_type="agent", agent_id="architect",
                         status="started")
        text, err = self._execute(messages, self._role_caps("architect"),
                                  task_id=task_id)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "architecture": text}

    # -- stage: implementer ----------------------------------------------------
    def implement(self, spec: str, owned_files: list[str] = [],
                  task_id=None) -> dict:
        messages = [{
            "role": "system",
            "content": f"You are the Elysia implementer. Implement the task. "
                       f"You may only position under files: {owned_files or ['(any new)']}",
        }, {"role": "user", "content": spec}]
        self.events.emit("agent.run", event_type="agent", agent_id="implementer",
                         status="started")
        text, err = self._execute(messages, self._role_caps("implementer"),
                                  task_id=task_id)
        if err:
            return {"ok": False, "error": err}
        # a null-op "implementer" just records output; real code runs via tools
        return {"ok": True, "output": text}

    # -- stage: tester ---------------------------------------------------------
    def test(self, spec: str, commands: dict | None = None, task_id=None) -> dict:
        messages = [{
            "role": "system",
            "content": "You are the Elysia tester. Propose the exact test "
                       "commands and what a green result looks like for this "
                       "task.",
        }, {"role": "user", "content": spec}]
        self.events.emit("agent.run", event_type="agent", agent_id="tester",
                         status="started")
        text, err = self._execute(messages, self._role_caps("tester"),
                                  task_id=task_id)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "test_plan": text}

    # -- stage: code reviewer ---------------------------------------------------
    def review(self, diff: str, task_id=None) -> dict:
        messages = [{
            "role": "system",
            "content": "You are the Elysia code reviewer. Review for correctness, "
                       "security, simplicity and maintainability. Use comment "
                       "format: 'SEVERITY: path:line: note', where severity is "
                       "BLOCKER/MAJOR/MINOR/NIT.",
        }, {"role": "user", "content": diff or "No diff provided"}]
        self.events.emit("agent.run", event_type="agent", agent_id="code_reviewer",
                         status="started")
        text, err = self._execute(messages, self._role_caps("code_reviewer"),
                                  task_id=task_id)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "review": text}

    # -- stage: docs -------------------------------------------------------------
    def document(self, spec: str, task_id=None) -> dict:
        messages = [{
            "role": "system",
            "content": "You are the Elysia documentation agent. Write concise, "
                       "accurate docs for the given change.",
        }, {"role": "user", "content": spec}]
        self.events.emit("agent.run", event_type="agent", agent_id="documentation_agent",
                         status="started")
        text, err = self._execute(messages, self._role_caps("documentation_agent"),
                                  task_id=task_id)
        if err:
            return {"ok": False, "error": err}
        return {"ok": True, "documentation": text}


def parse_plan(text: str) -> list[dict]:
    tasks = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("```") or line.startswith("#"):
            continue
        line = line.lstrip("-*").strip()
        if not line or len(line) < 4:
            continue
        if "|" in line:
            title, _, detail = line.partition("|")
        else:
            title, detail = line, ""
        tasks.append({"title": title.strip(), "detail": detail.strip()})
    return tasks[:12]