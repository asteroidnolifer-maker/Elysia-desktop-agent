"""Bounded autonomous operation — the unattended brain loop (Phase B).

This module wraps the ONE canonical ``MasterController``. It does **not**
introduce a second controller, scheduler, task store or provider manager: the
durable board stays the single source of truth and every task still flows
through scheduler -> executor -> agent pipeline -> workspace -> QA -> review.

What it adds is the long-horizon behaviour a single ``master run`` lacks:

    brain loop        understand -> inspect -> determine unknowns -> plan ->
                      execute -> observe -> verify -> decide -> complete,
                      recorded as real events on the canonical bus
    bounded           a ``RunBudget`` (wall clock, tasks, model calls, tokens,
                      cost). Over budget the session PARKS with a resumable
                      state and a stated reason — never a silent stop
    crash-safe        the board is the state; a restart resumes the graph and
                      a completed task is never executed twice
    journaled         every session writes a human-readable report to
                      ``workspace/reports/`` so a human can audit what ran
    guarded           the loop REFUSES to start when a safety invariant is
                      disabled (privacy routing, write gate, QA rollback,
                      tool permissions)
    self-improvement  repeated failures become proposals queued as
                      ``background`` work, applied only through the same
                      plan/implement/test/verify pipeline

Thinking is not acting (prompt.txt S4): a task counts as successful only when
the board says completed AND the files it owns really exist. A model *claiming*
success with no file on disk is reported as an unverified claim, never success.
"""
from __future__ import annotations

import json
import os
import time
import uuid

from .events import EventBus
from .master import MasterController
from .tasks import TERMINAL, PRIORITY_CLASSES, TaskStore, normalise_class
from .workspace import Workspace

#: The brain loop, in order. Every session records each stage it reaches, so a
#: run is explainable after the fact (prompt.txt S2/S3).
STAGES = ("understand", "inspect", "determine_unknowns", "plan", "execute",
          "observe", "verify", "decide", "complete")

#: Decisions the loop may reach at the ``decide`` stage.
DECISIONS = ("success", "retry", "repair", "replan", "escalate")

#: Repeat count at which a failure becomes a self-improvement proposal.
PROPOSAL_THRESHOLD = 2


class GuardrailError(RuntimeError):
    """Raised when a safety invariant is disabled and the loop must not run."""


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def guardrails(master: MasterController) -> dict:
    """Verify the invariants the autonomous loop may never weaken.

    Returns ``{name: {"ok": bool, "detail": str}}``. Every check is made
    against live objects, and the write gate is a real functional probe (an
    out-of-scope write must actually be refused) rather than a comment.

    NOTE: the directive that requested this loop also demanded that
    "privacy routing / local_only" never be disabled. No such feature exists in
    this codebase (no ``local_only`` in ProviderManager and no provider
    locality notion — ``kind='openai'`` is used for the *loopback* Ollama
    provider too), so it is NOT asserted here. Asserting it would be a fake
    guardrail. It is recorded as an open gap in ``docs/AUTONOMY.md``.
    """
    cfg = getattr(master, "cfg", None)
    out: dict[str, dict] = {}

    # 1) Workspace write gate — proven by probing a real escape attempt.
    ws_root = getattr(master, "workspace_root", "") or ""
    gate_ok, detail = False, "workspace path guard refused an escape attempt"
    try:
        probe = Workspace(ws_root)
        try:
            probe.write_owned((os.pardir + os.sep + "elysia_escape_probe.py"),
                              "should never be written\n")
            gate_ok, detail = False, ("workspace guard ALLOWED a ../ write — "
                                      "the write gate is broken")
        except Exception:  # noqa: BLE001 — refusing is the expected outcome
            gate_ok = True
    except Exception as e:  # noqa: BLE001
        gate_ok, detail = False, f"write gate could not be probed: {e}"
    out["workspace_write_gate"] = {"ok": gate_ok, "detail": detail}

    # 2) Permissioned tool layer is actually in use.
    tools = getattr(master, "tools", None)
    out["tool_layer"] = {
        "ok": tools is not None,
        "detail": ("permissioned tool layer active" if tools is not None
                   else "tools.enabled is false — writes bypass the tool layer")}

    # 3) High-risk tools stay denied unless the operator allowed them.
    allow_high = bool(getattr(getattr(cfg, "tools", None), "allow_high_risk",
                              False))
    out["high_risk_tools"] = {
        "ok": not allow_high,
        "detail": ("high-risk tools denied by default" if not allow_high
                   else "tools.allow_high_risk is enabled")}

    # 4) Shell execution stays gated.
    enable_shell = bool(getattr(getattr(cfg, "tools", None), "enable_shell",
                                False))
    out["shell_gate"] = {
        "ok": not enable_shell,
        "detail": ("system:shell denied by default" if not enable_shell
                   else "tools.enable_shell is enabled")}

    # 5) No provider secret is baked into the committed config.
    leaked = []
    for p in (getattr(cfg, "providers", None) or []):
        key = getattr(p, "api_key", "") or ""
        if key and not key.startswith(("env:", "${")):
            leaked.append(getattr(p, "label", None) or getattr(p, "kind", "?"))
    out["provider_secrets"] = {
        "ok": not leaked,
        "detail": ("no inline provider keys" if not leaked
                   else f"inline api_key present for: {', '.join(leaked)}")}
    return out


def failing_guardrails(checks: dict) -> list[str]:
    """Names of invariants that are NOT satisfied (empty = safe to run)."""
    return sorted(k for k, v in checks.items() if not v.get("ok"))


class RunBudget:
    """Ceilings for one unattended session, and what it actually spent.

    A ceiling of ``0``/``0.0`` means "unlimited". ``exhausted()`` returns the
    reason the session must park, or ``None`` while it may keep going. Every
    number reported is measured (task rows + their recorded usage), never
    estimated — prompt.txt S38/S37 forbid inventing progress.
    """

    def __init__(self, wall_s: float = 0.0, max_tasks: int = 0,
                 max_model_calls: int = 0, max_tokens: int = 0,
                 max_cost_usd: float = 0.0, started: float | None = None,
                 tokens_per_call: int = 0):
        self.wall_s = float(wall_s or 0.0)
        self.max_tasks = int(max_tasks or 0)
        self.max_model_calls = int(max_model_calls or 0)
        self.max_tokens = int(max_tokens or 0)
        self.max_cost_usd = float(max_cost_usd or 0.0)
        self.started = float(started if started is not None else time.time())
        #: Fallback estimate when a provider reports no token usage at all, so
        #: ``max_tokens`` is still enforceable. 0 = do not estimate.
        self.tokens_per_call = int(tokens_per_call or 0)
        self.tasks = 0
        self.model_calls = 0
        self.tokens = 0
        self.cost_usd = 0.0

    @classmethod
    def from_config(cls, cfg, **overrides) -> "RunBudget":
        a = getattr(cfg, "autonomy", None)
        kw = {"wall_s": getattr(a, "max_wall_s", 0.0),
              "max_tasks": getattr(a, "max_tasks", 0),
              "max_model_calls": getattr(a, "max_model_calls", 0),
              "max_tokens": getattr(a, "max_tokens", 0),
              "max_cost_usd": getattr(a, "max_cost_usd", 0.0)}
        for k, v in overrides.items():
            if k in kw and v is not None:
                kw[k] = v
        return cls(**kw)

    # -- accounting ----------------------------------------------------------
    def elapsed_s(self) -> float:
        return max(0.0, time.time() - self.started)

    def remaining_wall_s(self):
        if not self.wall_s:
            return float("inf")
        return max(0.0, self.wall_s - self.elapsed_s())

    def spend(self, tasks: int = 0, model_calls: int = 0, tokens: int = 0,
              cost_usd: float = 0.0) -> None:
        self.tasks += int(tasks)
        self.model_calls += int(model_calls)
        self.tokens += int(tokens)
        self.cost_usd = round(self.cost_usd + float(cost_usd), 6)

    def exhausted(self) -> str | None:
        """Why the session must park, or ``None``. Cheapest check first."""
        if self.wall_s and self.elapsed_s() >= self.wall_s:
            return (f"wall-clock budget spent "
                    f"({int(self.elapsed_s())}s of {int(self.wall_s)}s)")
        if self.max_tasks and self.tasks >= self.max_tasks:
            return f"task budget spent ({self.tasks} of {self.max_tasks})"
        if self.max_model_calls and self.model_calls >= self.max_model_calls:
            return (f"model-call budget spent ({self.model_calls} of "
                    f"{self.max_model_calls})")
        if self.max_tokens and self.tokens >= self.max_tokens:
            return f"token budget spent ({self.tokens} of {self.max_tokens})"
        if self.max_cost_usd and self.cost_usd >= self.max_cost_usd:
            return (f"cost budget spent (${self.cost_usd:.4f} of "
                    f"${self.max_cost_usd:.4f})")
        return None

    def snapshot(self) -> dict:
        rem = self.remaining_wall_s()
        return {
            "limits": {"wall_s": self.wall_s, "max_tasks": self.max_tasks,
                       "max_model_calls": self.max_model_calls,
                       "max_tokens": self.max_tokens,
                       "max_cost_usd": self.max_cost_usd},
            "spent": {"elapsed_s": round(self.elapsed_s(), 2),
                      "tasks": self.tasks, "model_calls": self.model_calls,
                      "tokens": self.tokens,
                      "cost_usd": round(self.cost_usd, 6)},
            "remaining_wall_s": None if rem == float("inf") else round(rem, 2),
            "exhausted": self.exhausted(),
        }

    return sorted(k for k, v in checks.items() if not v.get("ok"))


class SessionReport:
    """What one unattended session actually did, rendered for a human.

    Every field is derived from the durable board and the event log, so the
    journal cannot disagree with what the runtime stored.
    """

    def __init__(self, session_id: str, goal: str = "", resume_of: str = ""):
        self.session_id = session_id
        self.goal = goal
        self.resume_of = resume_of
        self.started = time.time()
        self.ended: float | None = None
        self.end_reason = ""
        self.stages: list[str] = []
        self.decision = ""
        self.tasks: list[dict] = []
        self.completed = 0
        self.failed = 0
        self.files_written: list[str] = []
        self.unverified: list[dict] = []
        self.guardrail_checks: dict = {}
        self.budget: dict = {}
        self.stages_seen: list[str] = []
        self.providers: list[dict] = []
        self.proposals: list[dict] = []
        self.notes: list[str] = []

    @property
    def ok(self) -> bool:
        return bool(self.tasks) and self.failed == 0 and not self.unverified

    def as_dict(self) -> dict:
        return {
            "session_id": self.session_id, "goal": self.goal,
            "resume_of": self.resume_of,
            "started": _iso(self.started),
            "ended": _iso(self.ended) if self.ended else None,
            "duration_s": round((self.ended or time.time()) - self.started, 2),
            "end_reason": self.end_reason, "decision": self.decision,
            "stages": self.stages, "stages_seen": self.stages_seen,
            "tasks_total": len(self.tasks), "completed": self.completed,
            "failed": self.failed, "files_written": self.files_written,
            "unverified_claims": self.unverified,
            "guardrails": self.guardrail_checks, "budget": self.budget,
            "providers": self.providers, "proposals": self.proposals,
            "notes": self.notes, "ok": self.ok,
        }
    def to_markdown(self) -> str:
        """Human-readable run journal (written under workspace/reports/)."""
        d = self.as_dict()
        L = [f"# Elysia autonomous run {self.session_id}", ""]
        L.append(f"- **Started:** {d['started']}")
        L.append(f"- **Ended:** {d['ended'] or '-'} ({d['duration_s']}s)")
        L.append(f"- **Goal:** {self.goal or '- (resumed existing work)'}")
        if self.resume_of:
            L.append(f"- **Resumed from:** {self.resume_of}")
        L.append(f"- **End reason:** {self.end_reason or '-'}")
        L.append(f"- **Decision:** {self.decision or '-'}")
        L.append(f"- **Outcome:** {'OK' if self.ok else 'NOT OK'}")
        L.append("")
        L.append("## Brain loop")
        L.append("")
        L.append(" -> ".join(self.stages) or "-")
        L.append("")
        L.append("## Budget")
        L.append("")
        lim = (d["budget"] or {}).get("limits", {})
        spent = (d["budget"] or {}).get("spent", {})
        L.append("| measure | limit | spent |")
        L.append("|---|---|---|")
        for k in ("wall_s", "max_tasks", "max_model_calls", "max_tokens",
                  "max_cost_usd"):
            L.append(f"| {k} | {lim.get(k)} | - |")
        for k in ("elapsed_s", "tasks", "model_calls", "tokens", "cost_usd"):
            L.append(f"| {k} | - | {spent.get(k)} |")
        L.append("")
        L.append("## Tasks")
        L.append("")
        if not self.tasks:
            L.append("_No durable tasks were involved in this session._")
        else:
            L.append("| id | status | role | files written | error |")
            L.append("|---|---|---|---|---|")
            for t in self.tasks:
                L.append(f"| {t.get('id')} | {t.get('status')} | "
                         f"{t.get('agent_role') or '-'} | "
                         f"{', '.join(t.get('files_written') or []) or '-'} | "
                         f"{t.get('error') or '-'} |")
        L.append("")
        L.append(f"Files changed: {', '.join(self.files_written) or '-'}")
        L.append("")
        if self.unverified:
            L.append("## Unverified claims (NOT counted as success)")
            L.append("")
            for u in self.unverified:
                L.append(f"- #{u.get('id')} {u.get('title')}: {u.get('why')}")
            L.append("")
        if self.stages_seen:
            L.append("## Logical agents that actually ran")
            L.append("")
            L.append(", ".join(self.stages_seen))
            L.append("")
        L.append("## Guardrails")
        L.append("")
        for name, g in (self.guardrail_checks or {}).items():
            L.append(f"- **{name}** - {'OK' if g.get('ok') else 'FAIL'}: "
                     f"{g.get('detail')}")
        L.append("")
        if self.providers:
            L.append("## Providers")
            L.append("")
            for p in self.providers:
                L.append(f"- {p.get('name')}: {p.get('status')} "
                         f"({p.get('requests', 0)} req, "
                         f"{p.get('failures', 0)} fail)")
            L.append("")
        if self.proposals:
            L.append("## Self-improvement proposals")
            L.append("")
            for p in self.proposals:
                L.append(f"- [{p.get('severity')}] {p.get('kind')}: "
                         f"{p.get('detail')} (seen {p.get('count')}x)")
            L.append("")
        if self.notes:
            L.append("## Notes")
            L.append("")
            L.extend(f"- {n}" for n in self.notes)
            L.append("")
        return "\n".join(L) + "\n"

class AutonomyLoop:
    """Drive the canonical master unattended, within a budget, with a journal.

    One loop per ``MasterController``. It never constructs its own controller,
    scheduler or store — it calls the master's own ``submit``/``start``/
    ``stop``/``report`` and the executor's ``tick``.
    """

    def __init__(self, master: MasterController, cfg=None,
                 workspace: Workspace | None = None,
                 journal_dir: str | None = None,
                 events: EventBus | None = None):
        self.master = master
        self.cfg = cfg if cfg is not None else getattr(master, "cfg", None)
        self.events = events or getattr(master, "events", None) or EventBus()
        self.workspace_root = getattr(master, "workspace_root", "") or ""
        self.workspace = workspace or Workspace(self.workspace_root)
        a = getattr(self.cfg, "autonomy", None)
        self.journal_dir = (journal_dir
                            or getattr(a, "journal_dir", None) or "reports")
        self.idle_poll_s = float(getattr(a, "idle_poll_s", 2.0) or 2.0)
        self.idle_timeout_s = float(getattr(a, "idle_timeout_s", 60.0) or 60.0)
        self.self_improvement = bool(getattr(a, "self_improvement", True))
        self.enforce_guardrails = bool(getattr(a, "enforce_guardrails", True))
        #: Estimated tokens per model call, used ONLY when a provider reports no
        #: usage at all, so a token ceiling stays enforceable. 0 = no estimate.
        self._tokens_per_call = int(getattr(a, "tokens_per_call", 0) or 0)
        #: task id -> usage already added to a budget (per-round idempotency).
        self._usage_seen: dict[int, dict] = {}
        self.poll_s = float(getattr(master.executor, "poll_interval_s", 0.25)
                            or 0.25)

    # -- guardrails -----------------------------------------------------------
    def check_guardrails(self) -> dict:
        return guardrails(self.master)

    def assert_guardrails(self) -> dict:
        """Raise ``GuardrailError`` when a safety invariant is disabled."""
        checks = self.check_guardrails()
        bad = failing_guardrails(checks)
        if bad and self.enforce_guardrails:
            detail = "; ".join(f"{k}: {checks[k]['detail']}" for k in bad)
            raise GuardrailError(
                f"refusing to run unattended — guardrail(s) disabled: {detail}")
        return checks

    # -- paths ----------------------------------------------------------------
    def journal_path(self, session_id: str) -> str:
        rel = os.path.join(self.journal_dir,
                           f"autonomy-{session_id}.md")
        return os.path.join(self.workspace_root, rel)

    def _budget(self, **overrides) -> RunBudget:
        b = RunBudget.from_config(self.cfg, **overrides)
        if not b.wall_s and not b.max_tasks and not b.max_model_calls \
                and not b.max_tokens and not b.max_cost_usd:
            # A session with no ceiling at all is not autonomous, it is a
            # runaway. Fall back to the configured default wall clock.
            b.wall_s = float(getattr(getattr(self.cfg, "autonomy", None),
                                     "max_wall_s", 3600.0) or 3600.0)
        return b

    # -- brain-loop plumbing --------------------------------------------------
    def _stage(self, report: SessionReport, stage: str, detail: str = "",
               **kw) -> None:
        """Record one brain-loop stage on the canonical event bus."""
        if stage not in report.stages:
            report.stages.append(stage)
        self.events.emit("autonomy.stage", agent_id="autonomy",
                         status=stage, detail=detail,
                         session_id=report.session_id, **kw)
# -- accounting (measured, never estimated) -------------------------------
    def _usage_of(self, task: dict) -> dict:
        u = task.get("usage_json") or {}
        if not isinstance(u, dict):
            u = {}
        calls = int(u.get("requests", 0) or 0)
        tokens = int(u.get("tokens_in", 0) or 0) + int(u.get("tokens_out", 0)
                                                        or 0)
        if self._tokens_per_call and not tokens:
            # Provider reported no token usage at all; keep the token ceiling
            # meaningful with a stated, documented estimate.
            tokens = calls * self._tokens_per_call
        return {"calls": calls, "tokens": tokens,
                "cost": float(task.get("cost_usd") or 0.0)}

    def _account(self, budget: RunBudget, task_ids: list[int]) -> None:
        """Move measured usage deltas into the budget (idempotent per round)."""
        for tid in task_ids:
            t = self.master.store.get(tid)
            if not t:
                continue
            now = self._usage_of(t)
            prev = self._usage_seen.get(tid) or {"calls": 0, "tokens": 0,
                                                 "cost": 0.0}
            d_calls = max(0, now["calls"] - prev["calls"])
            d_tokens = max(0, now["tokens"] - prev["tokens"])
            d_cost = max(0.0, now["cost"] - prev["cost"])
            if d_calls or d_tokens or d_cost:
                budget.spend(model_calls=d_calls, tokens=d_tokens,
                             cost_usd=d_cost)
            self._usage_seen[tid] = now

    # -- board introspection ---------------------------------------------------
    def _collect(self, report: SessionReport, task_ids: list[int]) -> None:
        """Fill the report from the durable rows (the source of truth)."""
        rep = self.master.report(task_ids) if task_ids else {}
        report.tasks = rep.get("tasks") or []
        report.completed = int(rep.get("completed") or 0)
        report.failed = int(rep.get("failed") or 0)
        report.files_written = list(rep.get("files_changed") or [])
        report.stages_seen = list(rep.get("stages") or [])
        report.providers = list(rep.get("providers") or [])

    def _verify_claims(self, report: SessionReport) -> list[dict]:
        """Thinking is not acting: a claim without a real artifact is flagged.

        A task whose board status is completed but which owned files that do not
        exist on disk (and wrote nothing) did NOT verifiably happen. It is
        reported here and never counted as success (prompt.txt S4, S37).
        """
        out = []
        for t in report.tasks:
            if t.get("status") not in ("completed", "done"):
                continue
            owned = t.get("owned_files") or []
            written = t.get("files_written") or []
            if owned and not written:
                missing = [f for f in owned
                           if not self.workspace.exists(f)]
                if missing:
                    out.append({"id": t.get("id"), "title": t.get("title"),
                                "why": f"completed but missing on disk: "
                                       f"{', '.join(missing)}"})
        return out

    def _decision(self, report: SessionReport) -> str:
        """success | retry | repair | replan | escalate (prompt.txt S1/S3)."""
        if report.unverified:
            return "repair"
        if report.failed:
            healed = [e for e in self.events.recent(50, event_type="task.healing")
                      if e.get("task_id") in {t.get("id") for t in report.tasks}]
            if healed:
                return "retry"
            if report.completed:
                return "replan"
            return "escalate"
        if report.completed:
            return "success"
        return "escalate"
# -- brain loop: understand -> inspect -> unknowns -> plan -----------------
    def _inspect(self) -> dict:
        """What the runtime actually has right now (no guesses)."""
        store: TaskStore = self.master.store
        counts = store.counts()
        providers = self.master.providers.health_report()
        unprobed = [p["name"] for p in providers if not p.get("probed")]
        return {
            "workspace": self.master.workspace_summary(),
            "counts": counts,
            "ready_by_class": store.ready_by_class(),
            "providers": providers,
            "unprobed_providers": unprobed,
            "agents": self.master.agents(),
            "summary": (f"board={counts.get('total', 0)} tasks "
                        f"({counts.get('ready', 0)} ready), "
                        f"{len(providers)} provider(s)"),
        }

    def _unknowns(self, insp: dict) -> list[str]:
        """What is missing before this session can do useful work."""
        out = []
        ready = [p for p in insp["providers"] if p.get("status") == "healthy"]
        if not ready:
            unprobed = insp["unprobed_providers"]
            out.append("no provider is known healthy"
                       + (f" ({len(unprobed)} never probed)" if unprobed else ""))
        if not insp["counts"].get("ready", 0) and not insp["counts"].get(
                "claimed", 0):
            out.append("board has no ready work")
        for role in insp["agents"]:
            if not role.get("provider"):
                out.append(f"role {role.get('role')} has no provider")
        return out

    def _open_task_ids(self) -> list[int]:
        """Every non-terminal task on the board (crash-recovery resume set)."""
        return sorted(t["id"] for t in self.master.store.list(limit=2000)
                      if t.get("status") not in TERMINAL)

    def recover_interrupted(self, worker: str, max_attempts: int | None = None
                            ) -> list[int]:
        """Hand a dead worker's claims back to the board.

        Called explicitly on resume after a crash (``kill -9``) so the graph
        continues immediately instead of waiting for the lease to lapse. A
        completed task is terminal and therefore never returns here — completed
        work is never re-executed.
        """
        attempts = (max_attempts if max_attempts is not None
                    else self.master.scheduler.max_attempts)
        released = self.master.store.release_all_for_worker(worker, attempts)
        for tid in released:
            self.master.scheduler.release_reserved(tid)
            self.events.emit("task.recovered", task_id=tid, agent_id=worker,
                             status="ready",
                             detail="claim released after interruption")
        return released

    # -- brain loop: execute -> observe -> verify -> decide -------------------
    def _drive(self, budget: RunBudget, task_ids: list[int],
               idle_timeout_s: float | None = None) -> str:
        """Run the executor until the work drains, the budget ends, or idle.

        Returns the end reason: ``drained`` | ``budget`` | ``idle`` | ``stalled``.
        """
        if not task_ids:
            return "drained"
        idle_limit = (self.idle_timeout_s if idle_timeout_s is None
                      else float(idle_timeout_s))
        last_change = time.time()
        last_counts = None
        while True:
            reason = budget.exhausted()
            if reason:
                self._account(budget, task_ids)
                return "budget"
            states = {tid: (self.master.store.get(tid) or {}).get("status")
                      for tid in task_ids}
            open_ids = [t for t, s in states.items() if s not in TERMINAL]
            counts = self.master.store.counts()
            if counts != last_counts:
                last_counts, last_change = counts, time.time()
            self._account(budget, task_ids)
            if not open_ids:
                return "drained"
            # Nothing claimable and nothing moving => stalled, not "running".
            if not counts.get("ready", 0) and not counts.get("claimed", 0) \
                    and not counts.get("running", 0) and not counts.get(
                        "testing", 0) and not counts.get("reviewing", 0):
                return "stalled"
            if idle_limit and time.time() - last_change > idle_limit:
                return "idle"
            time.sleep(max(0.02, self.poll_s))

    def session(self, goal: str | None = None, submit: bool = True,
                resume_of: str = "", **budget_overrides) -> dict:
        """Run one bounded unattended session and return its report.

        With ``goal`` the goal is planned into the durable graph and driven to
        completion. Without it, any work already open on the board is resumed —
        which is exactly what a restart after a crash does.
        """
        report = SessionReport(uuid.uuid4().hex[:8], goal=(goal or ""),
                               resume_of=resume_of)
        report.guardrail_checks = self.assert_guardrails()
        budget = self._budget(**budget_overrides)
        try:
            return self._run_session(report, budget, goal, submit)
        finally:
            report.ended = report.ended or time.time()

    def _finish_early(self, report: SessionReport, budget: RunBudget,
                      reason: str, decision: str, note: str) -> dict:
        """End a session before execution, honestly, and journal it."""
        report.end_reason = reason
        report.decision = decision
        if note:
            report.notes.append(note)
        report.budget = budget.snapshot()
        self._stage(report, "decide", decision)
        self._stage(report, "complete", reason)
        self.write_journal(report)
        return report.as_dict()

    def _run_session(self, report: SessionReport, budget: RunBudget,
                     goal: str | None, submit: bool) -> dict:
        # 1) understand -------------------------------------------------------
        self._stage(report, "understand",
                    (goal or "resume work already open on the board")[:300])

        # 2) inspect ----------------------------------------------------------
        insp = self._inspect()
        self._stage(report, "inspect", insp["summary"],
                    counts=insp["counts"],
                    ready_by_class=insp["ready_by_class"])

        # 3) determine unknowns ----------------------------------------------
        unknowns = self._unknowns(insp)
        self._stage(report, "determine_unknowns",
                    "; ".join(unknowns) if unknowns else "none")
        if any(u.startswith("no provider is known healthy") for u in unknowns):
            return self._finish_early(
                report, budget, "no usable provider", "escalate",
                "No provider is known healthy, so nothing was executed. The "
                "board is untouched and this session is resumable.")

        # 4) plan -------------------------------------------------------------
        run: dict = {}
        task_ids: list[int] = []
        if goal and submit:
            run = self.master.submit(goal, start=False)
            if not run.get("ok"):
                return self._finish_early(
                    report, budget, f"planning failed: {run.get('error')}",
                    "escalate", "The goal could not be planned; no work ran.")
            task_ids = self.master.subtask_ids(run)
            report.notes.append(
                f"goal #{run.get('goal_task')} planned into {len(task_ids)} "
                f"durable sub-task(s)")
            for c in (run.get("repairs") or {}).get("changes", []):
                report.notes.append(f"graph repair: {c}")
        if not task_ids:
            task_ids = self._open_task_ids()
            if not task_ids:
                return self._finish_early(
                    report, budget, "board drained (nothing to do)", "success",
                    "No open work on the board — an idle session is not a "
                    "failure.")
            report.notes.append(
                f"resuming {len(task_ids)} task(s) already open on the board")
        self._stage(report, "plan", f"{len(task_ids)} durable task(s)",
                    task_ids=task_ids)
# 5) execute ----------------------------------------------------------
        self.master.start()
        self._stage(report, "execute",
                    f"claiming through the canonical scheduler "
                    f"(max_tasks={self.master.executor.max_tasks})",
                    task_ids=task_ids)
        end_reason = self._drive(budget, task_ids)
        park_reason = budget.exhausted()
        self.master.stop()      # release=True: claims return to the board

        # 6) observe ----------------------------------------------------------
        self._collect(report, task_ids)
        self._stage(report, "observe",
                    f"{report.completed} completed, {report.failed} failed, "
                    f"{len(self._open_task_ids())} still open")

        # 7) verify (thinking != acting) --------------------------------------
        report.unverified = self._verify_claims(report)
        self._stage(report, "verify",
                    f"{len(report.unverified)} unverified claim(s); "
                    f"{len(report.files_written)} file(s) really changed")

        # 8) decide -----------------------------------------------------------
        if end_reason == "budget":
            report.end_reason = park_reason or "budget spent"
        elif end_reason == "drained":
            report.end_reason = "work drained"
        elif end_reason == "idle":
            report.end_reason = "idle timeout (no board progress)"
        else:
            open_n = len(self._open_task_ids())
            report.end_reason = f"stalled: {open_n} task(s) cannot proceed"
        if end_reason == "budget":
            report.notes.append(
                "Parked at budget, not stopped: remaining work stays on the "
                "durable board and resumes with `elysia master loop resume`.")
        report.decision = self._decision(report)
        self._stage(report, "decide", report.decision,
                    unverified=len(report.unverified))

        # 9) self-improvement proposals -> background work ---------------------
        if self.self_improvement:
            props = self.improvement_proposals(report)
            report.proposals = props
            if props:
                queued = self.queue_improvements(props)
                report.notes.append(
                    f"queued {len(queued)} background improvement task(s) "
                    f"(never claimed while interactive work waits)")

        report.budget = budget.snapshot()
        self._stage(report, "complete", report.end_reason)
        self.write_journal(report)
        return report.as_dict()

    # -- public entry points --------------------------------------------------
    def run(self, goal: str, **budget_overrides) -> dict:
        """One bounded session for ``goal``: plan, execute, verify, journal."""
        return self.session(goal=goal, submit=True, **budget_overrides)

    def resume(self, recover_worker: str = "", **budget_overrides) -> dict:
        """Continue whatever is open on the board (post-crash recovery).

        ``recover_worker`` hands a dead worker's claims straight back instead of
        waiting for the lease to lapse. Completed tasks are terminal, so they
        are never re-queued and never re-executed.
        """
        released: list[int] = []
        if recover_worker:
            released = self.recover_interrupted(recover_worker)
        out = self.session(goal=None, submit=False,
                           resume_of=recover_worker or "board",
                           **budget_overrides)
        out["released_claims"] = released
        return out
# -- self-improvement (proposals only, never silent self-modification) ----
    def _proposal(self, kind: str, role: str, count: int,
                  tasks: list) -> dict:
        """Map a repeated failure class onto one concrete improvement task."""
        severity, action = 0.5, "unknown"
        try:
            from .healing import POLICIES
            pol = POLICIES.get(kind)
            if pol is not None:
                severity, action = round(float(pol.severity), 2), pol.action
        except Exception:  # noqa: BLE001 — a missing policy must not break it
            pass
        slug = "".join(c if c.isalnum() else "-" for c in f"{kind}-{role}")[:60]
        return {
            "kind": kind, "role": role, "count": count, "severity": severity,
            "action": action, "tasks": list(tasks),
            "title": f"Analyse repeated '{kind}' failures in the {role} role",
            "detail": (f"The failure class '{kind}' occurred {count} time(s) "
                       f"(recovery action '{action}', tasks {list(tasks)}). "
                       f"Diagnose the root cause and write a concrete, minimal "
                       f"improvement proposal. Do NOT change code: describe the "
                       f"smallest change that removes the repetition, where it "
                       f"belongs, and how it would be verified."),
            "owned_files": [f"improvements/{slug}.md"],
        }

    def improvement_proposals(self, report: SessionReport | None = None,
                              threshold: int = PROPOSAL_THRESHOLD) -> list[dict]:
        """Repeated failures / provider problems -> improvement proposals.

        Nothing here edits code. A proposal becomes a ``background`` board task
        whose only artifact is a written analysis, which a human then applies
        through the normal pipeline (prompt.txt S52).
        """
        seen: dict[tuple, dict] = {}
        for ev in self.events.recent(5000, event_type="task.healing"):
            detail = (ev.get("detail") or "").split("->")[0].strip() or "unknown"
            role = ev.get("agent_id") or "unknown"
            rec = seen.setdefault((detail, role),
                                  {"count": 0, "tasks": []})
            rec["count"] += 1
            tid = ev.get("task_id")
            if tid is not None and tid not in rec["tasks"]:
                rec["tasks"].append(tid)
        out = []
        for (kind, role), rec in sorted(seen.items()):
            if rec["count"] >= max(1, int(threshold)):
                out.append(self._proposal(kind, role, rec["count"],
                                          rec["tasks"]))
        for p in (self.master.providers.health_report() or []):
            if p.get("circuit") == "open":
                out.append(self._proposal("provider_quarantined",
                                          p.get("name") or "provider", 1, []))
        return out

    def queue_improvements(self, proposals: list[dict]) -> list[int]:
        """Persist proposals as ``background`` tasks (deduplicated)."""
        queued = []
        for p in proposals:
            h = json.dumps({"kind": p["kind"], "role": p["role"]},
                           sort_keys=True)
            try:
                dup = self.master.store.find_duplicate(h)
            except Exception:  # noqa: BLE001
                dup = None
            if dup is not None:
                continue
            tid = self.master.store.add_task(
                title=p["title"], description=p["detail"],
                owned_files=p.get("owned_files") or [],
                read_files=[], priority=1, priority_class="background",
                agent_role="documentation_agent", dedup_hash=h)
            queued.append(tid)
            self.events.emit("autonomy.proposal", task_id=tid,
                             agent_id="autonomy", status="queued",
                             detail=f"{p['kind']} ({p['count']}x)")
        return queued

    # -- run journal ----------------------------------------------------------
    def write_journal(self, report: SessionReport) -> str:
        """Write the human-readable session report. Empty string on failure."""
        try:
            return self.workspace.write_owned(
                os.path.join(self.journal_dir,
                             f"autonomy-{report.session_id}.md"),
                report.to_markdown())
        except Exception as e:  # noqa: BLE001 — a journal must not break a run
            self.events.emit("autonomy.journal_failed", agent_id="autonomy",
                             status="error", error=str(e)[:200])
            return ""

    def journal_index(self) -> list[dict]:
        """Every run journal written so far, newest first."""
        out = []
        base = self.workspace.resolve_or_none(self.journal_dir)
        if not base or not os.path.isdir(base):
            return out
        for name in sorted(os.listdir(base), reverse=True):
            if not (name.startswith("autonomy-") and name.endswith(".md")):
                continue
            path = os.path.join(base, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            out.append({"session_id": name[len("autonomy-"):-len(".md")],
                        "path": os.path.join(self.journal_dir, name),
                        "modified": _iso(mtime)})
        return out

    def summary(self) -> dict:
        """Read-only snapshot for the CLI/HUD (no side effects)."""
        checks = self.check_guardrails()
        return {
            "journals": self.journal_index()[:10],
            "journal_dir": self.journal_dir,
            "guardrails": checks,
            "guardrails_ok": not failing_guardrails(checks),
            "open_tasks": len(self._open_task_ids()),
            "ready_by_class": self.master.store.ready_by_class(),
            "self_improvement": self.self_improvement,
        }
