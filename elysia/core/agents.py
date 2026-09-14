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


def command_exists(root: str, cmd: str) -> bool:
    """True if ``cmd`` is resolvable as a binary (test-runner discovery)."""
    import shutil
    return shutil.which(cmd) is not None


def git_diff_text(root: str, head: str = "") -> str:
    """Return the current working-tree diff (capped) for code review."""
    import subprocess
    r = subprocess.run(["git", "-C", root, "diff", "--stat", "--", "."],
                       capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return ""
    body = subprocess.run(["git", "-C", root, "diff", "--", "."],
                          capture_output=True, text=True, timeout=15)
    return (body.stdout or "")[:8000]


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
        self.events.emit("provider.selected", status="ok",
                         agent_id=self.correlation.agent_role, task_id=task_id)
        text, err = self.providers.execute(messages, capabilities=capabilities,
                                           preferred=None)
        if err:
            self.events.emit("provider.fallback", status="error",
                             agent_id=self.correlation.agent_role,
                             task_id=task_id, error=err[:200])
            return None, err
        return text, ""

    def _call(self, messages, role: str, task_id=None, reservation=None):
        """Provider call for one pipeline stage.

        If a held ProviderReservation is supplied (scheduler-owned slot) it is
        used directly — the slot was acquired once and is released on finish.
        Otherwise fall back to Manager.execute (atomic self-service reserve).
        """
        caps = self._role_caps(role)
        if reservation is not None:
            text, err = reservation.call_failover(messages, capabilities=caps)
        else:
            text, err = self.providers.execute(messages, capabilities=caps)
        if err:
            self.events.emit("provider.fallback", status="error",
                             agent_id=role, task_id=task_id, error=err[:200])
            return None, err
        return text, ""

    # -- execution -----------------------------------------------------------
    def solve_task(self, task: dict, workspace, reservation=None,
                   run_tests: bool = True) -> dict:
        """Execute ONE claimed task against the real workspace.

        Pipeline: status=running -> implementer writes owned files through the
        controlled Workspace layer -> QA validates each written file -> tester
        runs available test commands -> code_reviewer inspects the real git
        diff -> store transition. Any provider failure marks the task failed
        locally (scheduler decides retry).

        Returns {"ok", "status", "result", "tests", "review"}.
        """
        from .qa import validate_file
        from .git import dirty_files, is_repo
        from .workspace import Workspace

        tid = task.get("id")
        ws = workspace if isinstance(workspace, Workspace) else Workspace(workspace)
        owned = [f for f in (task.get("owned_files") or []) if f]
        spec = task.get("description") or task.get("title") or ""
        self.events.emit("agent.run", agent_id="implementer", task_id=tid,
                         status="started")
        if tid is not None:
            try:
                self.store.transition(tid, "running")
            except Exception:  # already past running is fine
                pass
        prompt = (
            f"TASK: {task.get('title','')}\nDETAILS: {spec}\n"
            f"FILES YOU OWN (write complete content for these only): {owned}\n"
            f"Workspace root: {ws.root}\n\n"
            "Output each file as a fenced code block whose opening fence line "
            "ends with the relative path, e.g. ```md README.md. Never invent "
            "paths outside the workspace.")
        messages = [{"role": "system", "content":
                     "You are the Elysia implementer writing repository files."},
                    {"role": "user", "content": prompt}]
        text, err = self._call(messages, "implementer", task_id=tid,
                               reservation=reservation)
        if err:
            return self._stage_fail(tid, "running", f"implementer: {err}")

        from orchestrator.brain import parse_file_blocks
        files = parse_file_blocks(text, owned)
        written, qa_failures = [], []
        for path, content in files.items():
            # SECURITY: the model may emit a path outside the task's owned
            # set (mislabeled fence, traversal, another task's file). Never
            # silently remap or accept it — reject the file, fail QA loudly
            # (same hard rule as worker_local).
            if owned and path not in owned:
                qa_failures.append(f"{path}: not in owned files")
                continue
            try:
                ws.write_owned(path, content)
                written.append(path)
                ok, reason = validate_file(path, content)
                if not ok:
                    qa_failures.append(f"{path}: {reason}")
            except Exception as e:  # noqa: BLE001
                qa_failures.append(f"{path}: {e}")

        # tester: run project tests if requested and a runner exists
        test_result = ""
        if run_tests and written:
            test_result = self._run_tests(ws)
        # code reviewer inspects the real git diff
        review = ""
        diff_text = ""
        if is_repo(ws.root):
            try:
                diff_text = git_diff_text(ws.root)
            except Exception:  # noqa: BLE001
                diff_text = ""
        if diff_text:
            r = self.review(diff_text, task_id=tid)
            review = r.get("review", "") if r.get("ok") else ""

        if qa_failures:
            msg = "QA failed: " + "; ".join(qa_failures[:5])
            return self._stage_fail(tid, "testing", msg)
        lines = [f"wrote {len(written)} file(s): {', '.join(written[:5])}"]
        if test_result:
            lines.append(test_result)
        if review:
            lines.append(review[:300])
        if tid is not None:
            self.store.complete(tid, "reviewing", "\n".join(lines))
        return {"ok": True, "status": "reviewing", "result": "\n".join(lines),
                "tests": test_result, "review": review}

    def _run_tests(self, ws, timeout=120) -> str:
        """Best-effort test runner via the QA harness (no unsafe shell)."""
        from elysia.core.qa import run as qa_run
        for cmd in (["python3", "-m", "pytest", "-q"],
                    ["python3", "manage.py", "test", "--verbosity=1"]):
            if command_exists(ws.root, cmd[0]):
                rc, out = qa_run(cmd, cwd=ws.root, timeout=timeout)
                if out:
                    head = out.strip().splitlines()
                    return f"tests ({cmd[0]}): rc={rc} :: {head[-1][:120] if head else ''}"
        return ""

    def _stage_fail(self, tid, status, reason):
        if tid is not None:
            try:
                self.store.fail_attempt(tid, reason, backoff_s=self._backoff_s())
            except Exception:  # noqa: BLE001
                pass
        return {"ok": False, "status": status, "error": reason,
                "result": reason}

    def _backoff_s(self) -> float:
        sc = getattr(self.cfg, "scheduler", None) if self.cfg else None
        return float(getattr(sc, "retry_backoff_s", 30) or 30)

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
        self.events.emit("agent.run", agent_id="planner",
                         status="started")
        text, err = self._execute(messages, self._role_caps("planner"))
        if err:
            return {"ok": False, "error": err}
        tasks = parse_plan(text)
        self.events.emit("agent.decision", agent_id="planner",
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
        self.events.emit("agent.run", agent_id="architect",
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
        self.events.emit("agent.run", agent_id="implementer",
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
        self.events.emit("agent.run", agent_id="tester",
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
        self.events.emit("agent.run", agent_id="code_reviewer",
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
        self.events.emit("agent.run", agent_id="documentation_agent",
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