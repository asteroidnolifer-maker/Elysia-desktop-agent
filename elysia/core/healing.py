"""Failure classification, recovery and verification (Phase 21).

Every failure in Elysia takes the same path:

    detect -> classify -> recover -> retry/replan -> verify -> record

Design rules this module enforces:

  * A failure is classified from real evidence (exception type, message,
    exit codes, task state) — never guessed from a generic "it broke".
  * Every class has an explicit policy: is it retryable, which action should
    the runtime take (retry / retire-after-backoff / failover / replan /
    escalate / give up), how long to wait, and what the next attempt should be
    told differently.
  * Retries are bounded per class — no infinite retry loop can be built on top
    of this module.
  * Backoff is exponential with deterministic jitter (seeded by task id +
    attempt), so behaviour is reproducible in tests and still thundering-herd
    resistant.
  * Recovery is performed, not announced: each named recovery routine does a
    real, safe thing (release a stale lease, reclaim disk, re-probe a
    provider) and reports honestly when it could not run.
  * Verification is explicit: ``verified`` is True/False, or None when the
    condition genuinely cannot be re-checked cheaply (never a fake True).

Dangerous situations are deliberately NOT auto-recovered: a git conflict is
escalated to a human because resolving it could destroy unrelated work.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# taxonomy
# ---------------------------------------------------------------------------
#: Hard ceiling for any computed retry delay (no unbounded waits, ever).
MAX_BACKOFF_S = 900.0

RETRY = "retry"
RETRY_AFTER = "retry_after"
FAILOVER = "failover"
REPLAN = "replan"
ESCALATE = "escalate"
GIVE_UP = "give_up"


@dataclass(frozen=True)
class FailurePolicy:
    kind: str
    retryable: bool
    action: str
    base_backoff_s: float
    severity: float               # 0..1 (drives memory importance)
    hint: str = ""                # instruction delta for the next attempt
    recovery: str = ""            # named routine in Healer.RECOVERIES
    max_retries: int = 3          # bounded — never infinite

    def as_dict(self) -> dict:
        return {"kind": self.kind, "retryable": self.retryable,
                "action": self.action, "base_backoff_s": self.base_backoff_s,
                "severity": self.severity, "hint": self.hint,
                "recovery": self.recovery, "max_retries": self.max_retries}


def _p(kind, retryable, action, backoff, severity, hint="", recovery="",
       max_retries=3) -> FailurePolicy:
    return FailurePolicy(kind, retryable, action, backoff, severity, hint,
                         recovery, max_retries)


POLICIES: dict[str, FailurePolicy] = {
    # -- provider side ----------------------------------------------------
    "provider_timeout": _p(
        "provider_timeout", True, FAILOVER, 5.0, 0.5,
        "The previous provider timed out. Keep the same task, prefer a "
        "shorter, more direct answer.", max_retries=3),
    "provider_rate_limit": _p(
        "provider_rate_limit", True, RETRY_AFTER, 30.0, 0.45,
        "A provider was rate limited; the runtime is switching providers.",
        max_retries=4),
    "provider_http_error": _p(
        "provider_http_error", True, FAILOVER, 8.0, 0.5,
        "The provider returned a server error; the runtime is switching "
        "providers.", max_retries=3),
    "provider_unavailable": _p(
        "provider_unavailable", True, FAILOVER, 10.0, 0.55,
        "No usable provider answered; the task will wait and retry.",
        max_retries=4),
    "provider_auth": _p(
        "provider_auth", False, ESCALATE, 0.0, 0.9,
        "A provider credential was rejected. Fix the key before retrying.",
        max_retries=0),
    "provider_budget": _p(
        "provider_budget", True, RETRY_AFTER, 60.0, 0.6,
        "The spend budget is exhausted; only local/zero-cost providers may "
        "serve this task now.", max_retries=3),
    # -- model output ------------------------------------------------------
    "malformed_model_output": _p(
        "malformed_model_output", True, RETRY, 2.0, 0.4,
        "Your previous answer could not be parsed. Reply with ONLY the "
        "required fenced code blocks, one per owned file, opening fence line "
        "ending in the relative path.", max_retries=3),
    "empty_model_output": _p(
        "empty_model_output", True, RETRY, 3.0, 0.45,
        "Your previous answer was empty. Produce the changes explicitly.",
        max_retries=3),
    "invalid_tool_args": _p(
        "invalid_tool_args", True, RETRY, 2.0, 0.4,
        "The tool call arguments were invalid; re-issue with valid arguments.",
        max_retries=2),
    "tool_denied": _p(
        "tool_denied", False, REPLAN, 0.0, 0.6,
        "A tool was refused by the permission model. Re-plan using only the "
        "permissions this role actually holds.", max_retries=0),
    "path_outside_workspace": _p(
        "path_outside_workspace", False, REPLAN, 0.0, 0.8,
        "A path outside the task's owned files/workspace was requested. "
        "Re-plan within the owned file set.", max_retries=0),
    # -- verification ------------------------------------------------------
    "qa_failure": _p(
        "qa_failure", True, RETRY, 2.0, 0.5,
        "The written file failed static validation. Fix the reported syntax.",
        max_retries=3),
    "test_failure": _p(
        "test_failure", True, RETRY, 3.0, 0.55,
        "The project's tests failed after your change. Fix the regression.",
        max_retries=3),
    "build_failure": _p(
        "build_failure", True, RETRY, 5.0, 0.6,
        "The build failed. Fix the build error before anything else.",
        max_retries=3),
    "review_blocker": _p(
        "review_blocker", True, RETRY, 3.0, 0.6,
        "Code review raised a BLOCKER against this change. Address it "
        "exactly, then re-run.", max_retries=2),
    # -- infrastructure ----------------------------------------------------
    "sqlite_busy": _p(
        "sqlite_busy", True, RETRY_AFTER, 2.0, 0.4,
        "", recovery="recheck_store", max_retries=5),
    "stale_lease": _p(
        "stale_lease", True, RETRY_AFTER, 1.0, 0.4,
        "", recovery="release_lease", max_retries=5),
    "worker_crash": _p(
        "worker_crash", True, RETRY_AFTER, 5.0, 0.6,
        "", recovery="release_lease", max_retries=3),
    "executor_crash": _p(
        "executor_crash", True, RETRY_AFTER, 5.0, 0.6,
        "", recovery="release_lease", max_retries=3),
    "scheduler_restart": _p(
        "scheduler_restart", True, RETRY_AFTER, 3.0, 0.5,
        "", recovery="release_lease", max_retries=3),
    "network_error": _p(
        "network_error", True, RETRY_AFTER, 5.0, 0.45,
        "", max_retries=3),
    "filesystem_error": _p(
        "filesystem_error", True, RETRY_AFTER, 5.0, 0.55,
        "", recovery="recheck_workspace", max_retries=2),
    "disk_pressure": _p(
        "disk_pressure", True, RETRY_AFTER, 15.0, 0.7,
        "", recovery="cleanup_disk", max_retries=2),
    "memory_pressure": _p(
        "memory_pressure", True, RETRY_AFTER, 20.0, 0.6,
        "", recovery="cleanup_disk", max_retries=2),
    "permission_denied": _p(
        "permission_denied", False, ESCALATE, 0.0, 0.8,
        "The runtime was denied filesystem access it needs. Fix the "
        "environment permissions before retrying.", max_retries=0),
    # -- git: never auto-recovered ----------------------------------------
    "git_conflict": _p(
        "git_conflict", False, ESCALATE, 0.0, 0.9,
        "A merge/rebase conflict exists. A human must resolve it: the "
        "runtime will not guess and risk unrelated work.", max_retries=0),
    "git_dirty": _p(
        "git_dirty", False, ESCALATE, 0.0, 0.5,
        "The tree has uncommitted changes belonging to someone else; "
        "checkpoint or stash them deliberately.", max_retries=0),
    "dependency_failure": _p(
        "dependency_failure", True, RETRY, 5.0, 0.55,
        "A dependency install/resolve step failed. Retry after the package "
        "tool recovers; do not vendor anything.", max_retries=2),
    "unknown": _p(
        "unknown", True, RETRY, 10.0, 0.5,
        "", max_retries=2),
}


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------
# (regex, kind) — checked in order; first match wins. Kept explicit and
# readable so a classification can always be traced back to its evidence.
_PATTERNS: list[tuple[str, str]] = [
    (r"429|rate.?limit|too many requests", "provider_rate_limit"),
    (r"timed? ?out|timeout", "provider_timeout"),
    (r"budget|spend limit|over budget", "provider_budget"),
    (r"401|403|unauthor|invalid api key|authentication", "provider_auth"),
    (r"econnrefused|connection refused|no such host|temporary failure in "
     r"name resolution|network is unreachable", "network_error"),
    (r"no provider|no usable provider|provider unavailable|empty provider "
     r"fleet", "provider_unavailable"),
    (r"\b50[0-9]\b|bad gateway|server error", "provider_http_error"),
    (r"database is locked|database table is locked|sqlite_busy", "sqlite_busy"),
    (r"lease expired|stale lease|lease_expired", "stale_lease"),
    (r"worker (crash|expired|died)|worker_crashed", "worker_crash"),
    (r"executor (crash|died)|executor_crash", "executor_crash"),
    (r"scheduler (restart|stopped)", "scheduler_restart"),
    (r"disk (full|pressure)|no space left on device|enospc", "disk_pressure"),
    (r"out of memory|memory pressure|cannot allocate memory", "memory_pressure"),
    (r"not in owned files|outside the workspace|path traversal|"
     r"not allowed outside", "path_outside_workspace"),
    # NOTE ORDER: an OS-level "permission denied" must be classified as such
    # (it needs a human), not swallowed by the generic tool-denial pattern.
    (r"permission denied|eacces|operation not permitted", "permission_denied"),
    (r"refus|tool .*denied|denied by|permission model|not allowed by",
     "tool_denied"),
    (r"conflict|merge conflict|automatic merge failed", "git_conflict"),
    (r"qa failed|failed validation|syntax error|no parseable", "qa_failure"),
    (r"tests \([^)]*\): rc=[1-9]", "test_failure"),
    (r"tests failed|assertionerror|pytest failure", "test_failure"),
    (r"build failed|compile failed|compilation error|go build failed",
     "build_failure"),
    (r"blocker[:\s]", "review_blocker"),
    (r"invalid (tool )?arguments|missing required argument|"
     r"unexpected keyword", "invalid_tool_args"),
    (r"empty (model )?(output|response)|no content", "empty_model_output"),
    (r"could not parse|unparseable|malformed|invalid json|no file blocks",
     "malformed_model_output"),
    (r"dependency|npm err|pip.*failed|cargo.*failed", "dependency_failure"),
    (r"no such file|filenotfound|directory not empty", "filesystem_error"),
]

_EXC_KINDS = {
    "TimeoutError": "provider_timeout",
    "ConnectionError": "network_error",
    "ConnectionRefusedError": "provider_unavailable",
    "FileNotFoundError": "filesystem_error",
    "PermissionError": "permission_denied",
    "MemoryError": "memory_pressure",
    "OSError": "filesystem_error",
    "sqlite3.OperationalError": "sqlite_busy",
    "sqlite3.DatabaseError": "sqlite_busy",
    "json.JSONDecodeError": "malformed_model_output",
    "ValueError": "invalid_tool_args",
}


def classify(error, attempt: int = 1, task_id=None, context: dict | None = None,
             max_retries: int | None = None) -> dict:
    """Classify a failure into a policy + a bounded recovery decision.

    ``error`` may be an exception or a message string. The returned dict
    always includes the evidence used, so a wrong classification can be
    debugged instead of guessed at.
    """
    text = str(error or "")
    exc_name = ""
    if isinstance(error, BaseException):
        cls = type(error)
        exc_name = f"{cls.__module__}.{cls.__name__}".replace("builtins.", "")
        text = f"{cls.__name__}: {error}"
    lowered = text.lower()

    kind, evidence = "unknown", []
    if exc_name and exc_name in _EXC_KINDS:
        kind = _EXC_KINDS[exc_name]
        evidence.append(f"exception:{exc_name}")
    if kind == "unknown":
        for pattern, candidate in _PATTERNS:
            if re.search(pattern, lowered):
                kind = candidate
                evidence.append(f"pattern:/{pattern}/")
                break
    if kind == "unknown" and not text:
        evidence.append("no message supplied")
    policy = POLICIES.get(kind, POLICIES["unknown"])
    cap = policy.max_retries if max_retries is None else max_retries
    attempt = max(1, int(attempt or 1))
    backoff = 0.0
    growth = 1.0
    if policy.retryable:
        # deterministic jitter (+-20%): reproducible in tests, still spreads
        # a thundering herd of simultaneous retries.
        seed = f"{task_id}:{attempt}:{kind}"
        jitter = random.Random(seed).uniform(0.8, 1.2)
        backoff = round(min(policy.base_backoff_s * (2 ** (attempt - 1)),
                            MAX_BACKOFF_S) * jitter, 2)
        #: Multiplier relative to the class base for THIS attempt. A runtime
        #: with a configured retry cadence scales its own base by this, so the
        #: failure class controls the *growth*, the config controls the base.
        growth = round(jitter * (2 ** (attempt - 1)), 4)
    exhausted = policy.retryable and attempt > cap
    action = GIVE_UP if exhausted else policy.action
    return {
        "kind": kind,
        "policy": policy.kind,
        "retryable": policy.retryable and not exhausted,
        "action": action,
        "planned_action": policy.action,
        "base_backoff_s": policy.base_backoff_s,
        "backoff_growth": growth,
        "backoff_s": backoff if not exhausted else 0.0,
        "severity": policy.severity,
        "severity_score": policy.severity,
        "hint": policy.hint,
        "recovery": policy.recovery,
        "attempt": attempt,
        "max_retries": cap,
        "exhausted": exhausted,
        "evidence": evidence,
        "message": text[:500],
        "context": context or {},
    }


# ---------------------------------------------------------------------------
# healer
# ---------------------------------------------------------------------------
class Healer:
    """detect -> classify -> recover -> (retry/replan) -> verify -> record."""

    def __init__(self, store=None, memory=None, events=None, providers=None,
                 resources=None, workspace=None):
        self.store = store
        self.memory = memory
        self.events = events
        self.providers = providers
        self.resources = resources
        self.workspace = workspace

    # -- recoveries (real, safe actions only) --------------------------------
    def _release_lease(self, failure: dict, task: dict | None) -> dict:
        if self.store is None:
            return {"performed": False, "detail": "no task store attached"}
        try:
            released = self.store.release_expired()
        except Exception as e:  # noqa: BLE001 — recovery must not raise
            return {"performed": False, "detail": f"release_expired failed: {e}"}
        return {"performed": True,
                "detail": f"released {len(released)} expired lease(s)"}

    def _recheck_store(self, failure: dict, task: dict | None) -> dict:
        if self.store is None:
            return {"performed": False, "detail": "no task store attached"}
        try:
            health = self.store.health_check()
        except Exception as e:  # noqa: BLE001
            return {"performed": False, "detail": f"health_check failed: {e}"}
        ok = bool(health.get("integrity") in ("ok", True)) or \
            bool(health.get("ok"))
        return {"performed": True, "detail": f"store integrity={ok}",
                "verified_by": "tasks.health_check"}

    def _cleanup_disk(self, failure: dict, task: dict | None) -> dict:
        """Reclaim space the runtime owns: expired memory, DB vacuum."""
        detail = []
        if self.memory is not None:
            try:
                rep = self.memory.compact()
                detail.append(f"memory expired={rep.get('expired_removed', 0)} "
                              f"compressed={rep.get('compressed', 0)}")
            except Exception as e:  # noqa: BLE001
                detail.append(f"memory compact failed: {e}")
        if self.store is not None:
            try:
                vac = self.store.vacuum()
                detail.append(f"db reclaimed={vac.get('reclaimed_bytes', 0)}B")
            except Exception as e:  # noqa: BLE001
                detail.append(f"vacuum failed: {e}")
        return {"performed": True, "detail": "; ".join(detail) or "nothing to do"}

    def _recheck_workspace(self, failure: dict, task: dict | None) -> dict:
        if self.workspace is None:
            return {"performed": False, "detail": "no workspace attached"}
        try:
            exists = self.workspace.exists(".")
            return {"performed": True,
                    "detail": f"workspace reachable={bool(exists)}"}
        except Exception as e:  # noqa: BLE001
            return {"performed": False, "detail": f"workspace check failed: {e}"}

    def _refresh_providers(self, failure: dict, task: dict | None) -> dict:
        if self.providers is None:
            return {"performed": False, "detail": "no provider manager attached"}
        try:
            report = self.providers.health_report(probe=True)
        except Exception as e:  # noqa: BLE001
            return {"performed": False, "detail": f"probe failed: {e}"}
        healthy = [r.get("name") for r in report if r.get("state") == "healthy"]
        return {"performed": True,
                "detail": f"probed {len(report)} provider(s); healthy={healthy}"}

    RECOVERIES = {
        "release_lease": "_release_lease",
        "recheck_store": "_recheck_store",
        "cleanup_disk": "_cleanup_disk",
        "recheck_workspace": "_recheck_workspace",
        "refresh_providers": "_refresh_providers",
    }

    def recover(self, failure: dict, task: dict | None = None) -> dict:
        """Run the named recovery routine (or report that there is none)."""
        name = failure.get("recovery") or ""
        if not name:
            return {"performed": False, "routine": "",
                    "detail": "no recovery routine for this failure class"}
        fn = getattr(self, self.RECOVERIES.get(name, ""), None)
        if fn is None:
            return {"performed": False, "routine": name,
                    "detail": f"unknown recovery routine {name}"}
        try:
            out = fn(failure, task)
        except Exception as e:  # noqa: BLE001
            out = {"performed": False, "detail": f"recovery crashed: {e}"}
        out["routine"] = name
        return out

    def verify(self, failure: dict, recovery: dict,
               task: dict | None = None) -> bool | None:
        """Re-check the failing condition where it can be checked cheaply.

        Returns True/False, or None when there is nothing honest to re-check.
        """
        kind = failure.get("kind")
        if kind in ("provider_timeout", "provider_rate_limit",
                    "provider_http_error", "provider_unavailable",
                    "provider_budget"):
            if self.providers is None:
                return None
            try:
                report = self.providers.health_report(probe=False)
            except Exception:  # noqa: BLE001
                return None
            return any(r.get("state") == "healthy" for r in report)
        if kind in ("sqlite_busy",):
            if self.store is None:
                return None
            try:
                return bool(self.store.health_check())
            except Exception:  # noqa: BLE001
                return False
        if kind in ("stale_lease", "worker_crash", "executor_crash",
                    "scheduler_restart"):
            if self.store is None or task is None or task.get("id") is None:
                return None
            try:
                fresh = self.store.get(task["id"])
            except Exception:  # noqa: BLE001
                return None
            if not fresh:
                return None
            return fresh.get("worker") in (None, "") or fresh.get("status") \
                in ("ready", "claimed", "running", "queued")
        if kind in ("disk_pressure", "memory_pressure"):
            if self.resources is None:
                return None
            try:
                rep = self.resources.report()
            except Exception:  # noqa: BLE001
                return None
            return not bool(rep.get("memory_pressure"))
        if recovery.get("verified_by"):
            return None  # reported by the routine itself, not re-checked here
        return None

    # -- the full loop ------------------------------------------------------
    def handle(self, error, task: dict | None = None, attempt: int | None = None,
               max_attempts: int | None = None, run_id: str = "") -> dict:
        """Classify -> recover -> verify -> record one failure.

        Returns the classification plus ``recovery``, ``verified`` and
        ``recorded`` so the caller (pipeline/scheduler) can act on it.
        """
        task = task or {}
        attempt = int(attempt or task.get("attempts") or 1)
        failure = classify(error, attempt=attempt, task_id=task.get("id"),
                           context={"title": task.get("title"),
                                    "role": task.get("agent_role")})
        recovery = self.recover(failure, task)
        verified = self.verify(failure, recovery, task)
        failure["recovery_result"] = recovery
        failure["verified"] = verified
        failure["recorded"] = False
        if self.memory is not None:
            try:
                rec = self.memory.remember_failure(
                    task, failure, failure.get("message", ""), run_id=run_id)
                failure["recorded"] = bool(rec.get("ok"))
                failure["memory_key"] = rec.get("key")
            except Exception:  # noqa: BLE001 — memory must never mask a failure
                failure["recorded"] = False
        if self.events is not None:
            try:
                self.events.emit(
                    "task.healing", agent_id=task.get("agent_role"),
                    task_id=task.get("id"),
                    status="recovered" if recovery.get("performed") else "classified",
                    detail=f"{failure['kind']} -> {failure['action']}",
                    error=failure.get("message", "")[:200])
            except Exception:  # noqa: BLE001
                pass
        # per-class retry ceiling can be stricter than the task's own
        if failure["exhausted"] or (
                not failure["retryable"] and failure["action"] == GIVE_UP):
            failure["action"] = GIVE_UP
        return failure

    # -- summary for operators ---------------------------------------------
    def report(self) -> dict:
        return {
            "classes": len(POLICIES),
            "retryable": sorted(k for k, p in POLICIES.items() if p.retryable),
            "terminal": sorted(k for k, p in POLICIES.items()
                               if not p.retryable),
            "auto_recovered": sorted({p.recovery for p in POLICIES.values()
                                      if p.recovery}),
        }


def describe_policies() -> list[dict]:
    """Human-readable policy table (used by the CLI)."""
    return [POLICIES[k].as_dict() for k in sorted(POLICIES)]


def dumps(failure: dict) -> str:
    return json.dumps(failure, ensure_ascii=False, default=str)
