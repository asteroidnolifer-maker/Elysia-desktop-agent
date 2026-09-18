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
from .context import ContextBuilder, ContextPlanner
from .events import EventBus
from .healing import MAX_BACKOFF_S, Healer, classify
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
                 execution_history: ExecutionHistory | None = None,
                 tools=None):
        self.providers = providers
        self.store = store
        self.resources = resources
        self.events = events or EventBus()
        self.cfg = cfg
        # Canonical permissioned tool layer (elysia.core.toolkit.ToolLayer).
        # When attached, every file write/read the pipeline performs goes
        # through it, so per-role permissions are enforced on the live path.
        self.tools = tools
        self.memory = memory or Memory(getattr(cfg, "memory", None)
                                       and cfg.memory.dir or "state/memory")
        self.correlation = correlation or Correlation()
        self.history = execution_history or ExecutionHistory()
        # Canonical failure classifier/recoverer (Phase 21). It is the ONE
        # place a failure is turned into an action, so retries, failover and
        # escalation agree everywhere in the runtime.
        self.healer = Healer(store=store, memory=self.memory, events=self.events,
                             providers=providers, resources=resources)

    # -- context planning -----------------------------------------------------
    #: Token budget for one implementer call. Kept modest so low-resource
    #: hardware (2-core/16 GB) is not asked to hold a whole repository.
    IMPLEMENTER_BUDGET_TOKENS = 6000
    #: How much of each owned file is included as "what exists today".
    FILE_LAYER_CHARS = 2500

    def _current_file_text(self, ws, path: str) -> str:
        """Existing content of an owned file (empty when it does not exist)."""
        try:
            if self.tools is not None:
                res = self.tools.invoke("fs.read", {
                    "path": path, "max_chars": self.FILE_LAYER_CHARS},
                    "implementer")
                if res.get("ok"):
                    return ((res.get("data") or {}).get("content") or "")
                return ""
            if not ws.exists(path):
                return ""
            return ws.read(path, max_chars=self.FILE_LAYER_CHARS)
        except Exception:  # noqa: BLE001 — context must never break a task
            return ""

    def _failure_memories(self, task: dict, goal: str, limit: int = 3) -> list:
        try:
            return self.memory.rec_about(task, extra_terms=[goal], limit=limit)
        except Exception:  # noqa: BLE001
            return []

    def implementer_messages(self, task: dict, ws, owned: list[str]) -> tuple:
        """Assemble the implementer prompt through the context planner.

        Answers "what does this agent actually need?" instead of dumping the
        repository: the task, the current content of only the files it owns,
        what failed before and how it was classified, the last test result,
        relevant memory, and the provider constraints in force.
        """
        tid = task.get("id")
        spec = task.get("description") or task.get("title") or ""
        planner = ContextPlanner(budget_tokens=self.IMPLEMENTER_BUDGET_TOKENS,
                                 role="implementer")
        planner.add("system", "You are the Elysia implementer writing "
                              "repository files.", required=True)
        planner.add(
            "task",
            (f"TASK: {task.get('title','')}\nDETAILS: {spec}\n"
             f"FILES YOU OWN (write complete content for these only): {owned}\n"
             f"Workspace root: {ws.root}\n\n"
             "Output each file as a fenced code block whose opening fence line "
             "ends with the relative path, e.g. ```md README.md. Never invent "
             "paths outside the workspace."),
            source="task")
        current = {}
        for p in owned:
            body = self._current_file_text(ws, p)
            if body:
                current[p] = body
        if current:
            planner.add("files", ContextPlanner.file_layer(current),
                        source="workspace.read")
        last_error = task.get("last_error")
        prior = self._failure_memories(task, spec)
        classification = None
        if last_error:
            cls = classify(last_error, attempt=task.get("attempts") or 1,
                           task_id=tid)
            classification = {"kind": cls["kind"], "action": cls["action"],
                              "retryable": cls["retryable"],
                              "hint": cls["hint"]}
            planner.add("failures",
                        ContextPlanner.failure_layer(prior, classification),
                        source="healing.classify")
            if cls.get("hint"):
                planner.add("failures", f"DO THIS DIFFERENTLY: {cls['hint']}",
                            source="healing.hint")
        elif prior:
            planner.add("failures", ContextPlanner.failure_layer(prior),
                        source="memory.failure")
        test_text = ContextPlanner.test_layer(
            task.get("test_status") or task.get("result"))
        if test_text:
            planner.add("tests", f"previous run: {test_text}",
                        source="task.result")
        memories = [h for h in prior if h.get("namespace") in
                    ("solution", "decision", "project")]
        if memories:
            planner.add("memory", ContextPlanner.memory_layer(memories),
                        source="memory.recall")
        caps = self._role_caps("implementer")
        try:
            route = self.providers.explain(capabilities=caps) if self.providers \
                else {}
        except Exception:  # noqa: BLE001
            route = {}
        if route:
            planner.add("provider", ContextPlanner.provider_layer(route),
                        source="providers.explain")
        plan = planner.plan(cache_key=f"implementer:{tid}")
        if tid is not None:
            try:
                self.memory.remember_task_context(
                    task, {"context_report": plan["report"],
                           "context_tokens": plan["report"]["used_tokens_est"]})
            except Exception:  # noqa: BLE001
                pass
        messages = [{"role": "system",
                     "content": "You are the Elysia implementer writing "
                                "repository files."},
                    {"role": "user", "content": plan["prompt"]}]
        return messages, plan["report"]

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
        messages, context_report = self.implementer_messages(task, ws, owned)
        text, err = self._call(messages, "implementer", task_id=tid,
                               reservation=reservation)
        if err:
            return self._stage_fail(tid, "running", f"implementer: {err}",
                                    task=task)

        from .fileblocks import parse_file_blocks
        files = parse_file_blocks(text, owned)
        if not files:
            # An implementer that emits no parseable file block cannot have
            # changed anything — classify it and let the scheduler retry with
            # an explicit "reply with fenced blocks" hint.
            self.events.emit("agent.run", agent_id="implementer", task_id=tid,
                             status="error", detail="no parseable file blocks")
            return self._stage_fail(
                tid, "running",
                "implementer: no file blocks produced (empty or malformed "
                "model output)", task=task)
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
                prior = self._read_prior(ws, path)
                denied = self._write_owned(ws, path, content)
                if denied:
                    qa_failures.append(f"{path}: {denied}")
                    continue
                ok, reason = validate_file(path, content)
                if ok:
                    written.append(path)
                else:
                    # NEVER leave code that failed validation in the workspace:
                    # restore the previous content (or remove a new file).
                    qa_failures.append(f"{path}: {reason}")
                    self._rollback_file(ws, path, prior)
            except Exception as e:  # noqa: BLE001
                qa_failures.append(f"{path}: {e}")

        # tester: run project tests if requested and a runner exists
        test_result = ""
        if run_tests and written:
            self.events.emit("agent.run", agent_id="tester", task_id=tid,
                             status="started", detail="running project tests")
            test_result = self._run_tests(ws)
            self.events.emit("agent.run", agent_id="tester", task_id=tid,
                             status="ok" if test_result else "skipped",
                             detail=test_result[:200] or "no test runner found")
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
            return self._stage_fail(tid, "testing", msg, task=task)
        lines = [f"wrote {len(written)} file(s): {', '.join(written[:5])}"]
        if test_result:
            lines.append(test_result)
        if review:
            lines.append(review[:300])
        summary = "\n".join(lines)
        if tid is not None:
            self.store.complete(tid, "reviewing", summary,
                                test_status=test_result or None)
        # solution + task memory: the next task that looks like this one can
        # reuse what worked (and what it cost in context tokens).
        try:
            self.memory.remember_solution(task, summary, files=written)
            if test_result or review:
                self.memory.remember_task_context(
                    task, {"test_result": test_result[:400],
                           "review": review[:400],
                           "context_report": context_report})
        except Exception:  # noqa: BLE001 — memory must never fail a task
            pass
        return {"ok": True, "status": "reviewing", "result": summary,
                "tests": test_result, "review": review,
                "context": context_report}

    # -- permissioned workspace access (tool layer when attached) -------------
    def _write_owned(self, ws, path: str, content: str) -> str:
        """Write an owned file; return a denial reason ("") when it succeeded.

        With a tool layer attached the write is a permission-checked tool call:
        a role without ``workspace:write`` cannot write at all, and the refusal
        is reported as a QA failure instead of being silently ignored.
        """
        if self.tools is None:
            ws.write_owned(path, content)
            return ""
        res = self.tools.invoke("fs.write", {"path": path, "content": content},
                                "implementer")
        if res.get("ok"):
            return ""
        return f"tool fs.write refused: {res.get('error') or 'denied'}"

    #: Cap for reading a file back before overwriting it. Must NOT be the
    #: 9 KiB reference read limit, or a QA rollback would silently truncate a
    #: larger original file.
    ROLLBACK_READ_CHARS = 5_000_000

    def _read_prior(self, ws, path: str) -> str | None:
        """Previous content of a file we are about to overwrite (or None)."""
        if self.tools is not None:
            res = self.tools.invoke("fs.read", {
                "path": path, "max_chars": self.ROLLBACK_READ_CHARS}, "implementer")
            if res.get("ok"):
                return ((res.get("data") or {}).get("content"))
            return None
        if not ws.exists(path):
            return None
        return ws.read(path, max_chars=self.ROLLBACK_READ_CHARS)

    def _rollback_file(self, ws, path: str, prior: str | None) -> None:
        """Undo a write whose content failed QA (best effort, never raises)."""
        import os
        try:
            if prior is None:
                if self.tools is not None:
                    self.tools.invoke("fs.remove", {"path": path}, "implementer")
                else:
                    os.remove(ws.resolve(path))
            else:
                self._write_owned(ws, path, prior)
        except Exception:  # noqa: BLE001 — a failed cleanup must not mask the QA failure
            pass

    def _run_tests(self, ws, timeout=120) -> str:
        """Run the project's tests through the QA harness (no unsafe shell).

        Discovery is the ONE canonical helper (elysia.core.toolkit) shared with
        the ``qa.run_tests`` tool, so pytest/go/cargo/npm projects are detected
        the same way wherever tests are launched.
        """
        import os
        from elysia.core.qa import run as qa_run
        from elysia.core.toolkit import discover_test_command
        cmd, kind = discover_test_command(ws.root)
        if not cmd:
            if os.path.exists(os.path.join(ws.root, "manage.py")):
                cmd, kind = (["python3", "manage.py", "test", "--verbosity=1"],
                             "django")
            else:
                return ""
        rc, out = qa_run(cmd, cwd=ws.root, timeout=timeout)
        head = (out or "").strip().splitlines()
        return f"tests ({kind}): rc={rc} :: {head[-1][:120] if head else ''}"

    def _stage_fail(self, tid, status, reason, task=None):
        """Classify a stage failure, recover what is safe, record it.

        The classification decides the retry backoff (exponential per failure
        class, jittered) and whether the action is retry / failover / replan
        / escalate / give up. Recovery routines that are safe to run here
        (releasing a stale lease, reclaiming disk) are executed.
        """
        failure = None
        if tid is not None:
            try:
                failure = self.healer.handle(reason, task or {"id": tid},
                                             attempt=(task or {}).get("attempts"))
            except Exception:  # noqa: BLE001 — healing must never mask a failure
                failure = None
        # Retry cadence: the configured ``retry_backoff_s`` is the base for
        # THIS attempt and the failure class scales it exponentially (with
        # jitter), so a provider timeout genuinely waits longer each time
        # without hard-coding one global delay.
        backoff = self._backoff_s()
        if failure and failure.get("backoff_growth"):
            backoff = round(min(backoff * float(failure["backoff_growth"]),
                                MAX_BACKOFF_S), 2)
        detail = reason
        if failure:
            detail = (f"{reason} [healing: {failure['kind']} -> "
                      f"{failure['action']} backoff={backoff:.1f}s]")
        if tid is not None:
            try:
                self.store.fail_attempt(tid, detail, backoff_s=backoff)
            except Exception:  # noqa: BLE001
                pass
        out = {"ok": False, "status": status, "error": reason,
               "result": detail}
        if failure:
            out["healing"] = failure
        return out

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
        # long-term memory: past decisions/solutions and known failures for a
        # goal like this one, so planning does not repeat a known dead end.
        planner = ContextPlanner(budget_tokens=3000, role="planner")
        planner.add("task", ctx, required=True, source="agents_context")
        try:
            memories = self.memory.rec_about(
                {"title": goal, "description": goal}, limit=4)
        except Exception:  # noqa: BLE001
            memories = []
        if memories:
            planner.add("memory", ContextPlanner.memory_layer(memories),
                        source="memory.recall")
        plan = planner.plan(cache_key=f"planner:{goal[:80]}")
        messages = [
            {"role": "system", "content":
                "You are the Elysia planner. Turn the goal into a concise "
                "ordered task list. Return output as plain bullet lines: "
                "'- <short title>| <detail>'. Do NOT include commentary."},
            {"role": "user", "content": plan["prompt"]},
        ]
        self.events.emit("agent.run", agent_id="planner",
                         status="started")
        text, err = self._execute(messages, self._role_caps("planner"))
        if err:
            return {"ok": False, "error": err}
        tasks = parse_plan(text)
        self.events.emit("agent.decision", agent_id="planner",
                         status="ok", detail=f"planned {len(tasks)} sub-tasks")
        try:
            self.memory.remember_decision(
                f"plan for: {goal[:200]}",
                "planner produced: " + "; ".join(
                    t.get("title", "") for t in tasks[:8]),
                actor="agent:planner", tags=["plan"])
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True, "tasks": tasks, "raw": text,
                "context": plan["report"]}

    # -- stage: architect -----------------------------------------------------
    def architect(self, plan: str, task_id=None) -> dict:
        messages = [{
            "role": "system",
            "content": "You are the Elysia architect. From this plan, produce "
                       "a concise architecture: modules, data flow, and any "
                       "risks. Return markdown sections: '## Modules', "
                       "'## Risks'.",
        }, {"role": "user", "content": plan or "No plan supplied"}]
        self.events.emit("agent.run", agent_id="architect", task_id=task_id,
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
        self.events.emit("agent.run", agent_id="tester", task_id=task_id,
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
                         task_id=task_id, status="started")
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
                         task_id=task_id, status="started")
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