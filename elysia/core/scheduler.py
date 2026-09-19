"""Resource- and provider-aware scheduler.

The scheduler owns the task lifecycle. A background leader loop:

  1. releases expired leases (crashed worker -> task back to ready or failed
     after max_attempts)
  2. enforces per-task timeouts
  3. propagates dependency failures (a failed dep -> dependent = failed)
  4. re-queues ready work to claimable status

`dispatch_once` claims dependency-eligible tasks for a provider, respecting:

  - provider concurrency slots
  - resource budget (adaptive local worker budget)
  - global max_concurrency
  - per-task backoff (retry wait)
  - dedup (idempotency) checks happen at enqueue time, not here

A worker registry (worker_id -> last_seen + lease) lets the scheduler recover
stale leases when a worker disappears without marking everything failed.
"""
from __future__ import annotations

import threading
import time

from .events import EventBus
from .providers import ProviderManager
from .resources import (
    BACKGROUND, INTERACTIVE, LOCAL_LLM, NORMAL, REMOTE_LLM, ResourceLedger,
    ResourceMonitor, ResourcePolicy, estimate_resource_class,
    local_worker_budget, priority_rank, task_resource_needs,
)
from .tasks import TaskStore


class WorkerRegistry:
    """Tracks live workers so a disappearance is recoverable, not fatal."""

    def __init__(self, stale_after_s: float = 300.0):
        self._workers: dict[str, float] = {}
        self._mu = threading.Lock()
        self.stale_after_s = stale_after_s

    def register(self, worker: str) -> None:
        with self._mu:
            self._workers[worker] = time.time()

    def heartbeat(self, worker: str) -> None:
        self.register(worker)

    def unregister(self, worker: str) -> None:
        with self._mu:
            self._workers.pop(worker, None)

    def list(self) -> list[str]:
        with self._mu:
            return sorted(self._workers.keys())

    def stale(self) -> list[str]:
        now = time.time()
        with self._mu:
            return [w for w, ts in self._workers.items()
                    if now - ts > self.stale_after_s]

    def expire(self, worker: str) -> None:
        self.unregister(worker)


class Scheduler:
    def __init__(self, store: TaskStore, providers: ProviderManager,
                 events: EventBus | None = None, cfg=None,
                 worker_id: str = "sched", resources=None, ledger=None,
                 monitor=None, policy=None, warm=None, router=None):
        self.store = store
        self.providers = providers
        self.events = events or EventBus()
        self.cfg = cfg
        self.worker_id = worker_id
        self.resources = resources  # optional ResourceManager
        # Resource-aware execution (see RESOURCE_ARCHITECTURE.md). The master
        # passes the shared monitor/policy/ledger; when the scheduler is used
        # standalone they are built from config so admission still applies.
        self.monitor = monitor
        self.policy = policy
        self.ledger = ledger
        # warm-model registry: idle local models are unloaded under sustained
        # memory pressure (with hysteresis, so nothing thrashes).
        self.warm = warm
        #: Optional shared ModelRouter: decides local vs remote at dispatch.
        self.router = router
        if cfg is not None and self.monitor is None:
            rc = getattr(cfg, "resources", None)
            self.monitor = ResourceMonitor(
                sample_interval_s=float(getattr(rc, "monitor_sample_interval_s",
                                                1.0) or 1.0))
        if cfg is not None and self.policy is None:
            self.policy = ResourcePolicy.from_config(cfg)
        if cfg is not None and self.ledger is None:
            self.ledger = ResourceLedger.from_config(cfg, monitor=self.monitor,
                                                    policy=self.policy)
        if cfg is not None:
            sc = getattr(cfg, "scheduler", None) or cfg
            self.max_concurrency = getattr(sc, "max_concurrency", 4)
            self.max_attempts = getattr(sc, "max_attempts", 3)
            self.lease_seconds = getattr(sc, "lease_seconds", 1200)
            self.heartbeat_grace_s = getattr(sc, "heartbeat_grace_s", 60)
            self.reserve_mb = getattr(sc, "resource_reserve_mb", 1536)
            self.worker_est_mb = getattr(sc, "worker_est_mb", 600)
            self.aging_s = float(getattr(sc, "dispatch_aging_s", 30.0) or 30.0)
            self.interactive_preempt = bool(
                getattr(sc, "interactive_preempt", True))
        else:
            self.max_concurrency = 4
            self.max_attempts = 3
            self.lease_seconds = 1200
            self.heartbeat_grace_s = 60
            self.reserve_mb = 1536
            self.worker_est_mb = 600
            self.aging_s = 30.0
            self.interactive_preempt = True
        self.workers = WorkerRegistry(self.heartbeat_grace_s * 3)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        # Provider slots we hold while a claimed task is being executed. The
        # slot is released when the task finishes/cancels or the worker is
        # declared stale — this is what makes selection+reservation atomic.
        self._reserved: dict[int, "ProviderReservation"] = {}
        #: Ledger reservations (heavy slot / build slot) held per running task.
        self._held_slots: dict[int, object] = {}
        #: Last admission verdict per ready task id — powers `elysia queue`.
        self._verdicts: dict[int, dict] = {}
        self._reserved_mu = threading.Lock()

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        t = threading.Thread(target=self._loop, daemon=True, name="sched-loop")
        t.start()
        self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)

    def register_worker(self, worker: str) -> None:
        self.workers.register(worker)
        self.events.emit("worker.registered", agent_id=worker, status="ok")

    def unregister_worker(self, worker: str) -> None:
        self.workers.unregister(worker)
        self.events.emit("worker.unregistered", agent_id=worker, status="ok")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.maintenance()
            except Exception as e:  # noqa: BLE001
                self.events.emit("scheduler", status="error", error=str(e)[:300])
            self._stop.wait(5)

    def maintenance(self) -> None:
        """Recurring recovery work: leases, timeouts, dep-failure propagation."""
        now = time.time()
        # 1) auto-release queued tasks that have no dependencies
        for t in self.store.list(status="queued"):
            if not (t.get("dependencies") or []):
                self.store.mark_ready(t["id"])
        # 2) expired leases
        released = self.store.release_expired(self.max_attempts)
        for tid in released:
            self.release_reserved(tid)  # slot freed; task back to ready/failed
            self.events.emit("task.lease_expired", task_id=tid, status="ready")
        # 3) per-task timeouts
        for t in self.store.list(status="claimed"):
            ts = t.get("timeout_s")
            if ts and t.get("started_at") and now - t["started_at"] > ts:
                self.store.timeout_task(t["id"])
                self.release_reserved(t["id"])
                self.events.emit("task.timeout", task_id=t["id"], status="ready")
        # 4) dependency failure propagation
        for dep in self.store.list(status="failed"):
            for affected in self.store.failed_after_dependency(dep["id"]):
                self.events.emit("task.dependency_failed", task_id=affected,
                                 status="dependency_failed",
                                 detail=f"dependency {dep['id']} failed")
        # 5) release expired workers' claims
        for w in self.workers.stale():
            for tid in self.store.release_all_for_worker(w, self.max_attempts):
                self.release_reserved(tid)
                self.events.emit("task.worker_lost", task_id=tid, worker=w,
                                 status="ready")
            self.workers.expire(w)
            self.events.emit("worker.crashed", agent_id=w, status="expired")
        # 6) idle model unloading under sustained memory pressure (hysteresis)
        if self.warm is not None and self.monitor is not None \
                and self.policy is not None:
            try:
                for action in self.warm.maybe_unload(self.monitor, self.policy):
                    if action.get("action") in ("unloaded", "unload_failed",
                                                "unsupported"):
                        self.events.emit("model." + action["action"],
                                         status=action.get("action"),
                                         model=action.get("model"),
                                         detail=action.get("reason", "")[:200])
            except Exception as e:  # noqa: BLE001 — housekeeping must not crash
                self.events.emit("scheduler", status="error",
                                 error=f"model unload check: {e}"[:200])

    # -- dispatch -------------------------------------------------------------
    def ordered_ready(self, limit: int = 50) -> list[dict]:
        """Ready tasks in dispatch order: priority class, aged, then urgency.

        Aging lifts a task one priority rank per ``dispatch_aging_s`` it has
        waited, so a long-running background fleet can never starve a short
        interactive request (and a queued task is never starved by newer
        high-priority work).
        """
        now = time.time()
        rows = self.store.ready_tasks(limit=limit)

        def key(t):
            rank = float(priority_rank(t.get("priority_class") or NORMAL))
            waited = max(0.0, now - (t.get("created_at") or now))
            aged = waited / max(1.0, self.aging_s)
            return (max(0.0, rank - aged), -int(t.get("priority") or 5),
                    int(t.get("id") or 0))

        return sorted(rows, key=key)

    def _needs_model(self, task) -> bool:
        """True when this task genuinely requires a model call.

        A ``local_only`` task (or one whose only providers are local) is bound
        to the shared local slot; everything else may be offloaded to a
        remote provider by the router at call time.
        """
        cls = estimate_resource_class(task)
        return cls in (LOCAL_LLM, REMOTE_LLM)

    def _uses_local(self, task) -> bool:
        """True when this task must run on the local model slot."""
        if (task.get("privacy") or "").strip().lower() == "local_only":
            return True
        priv = getattr(self.cfg, "privacy", None) if self.cfg else None
        if bool(getattr(priv, "local_only", False)):
            return True
        try:
            if not self.providers.remote_providers():
                return True
        except AttributeError:
            return True
        return False

    def admit(self, task, interactive_pending: bool = False,
              snap=None) -> dict:
        """May this task start RIGHT NOW? Never mutates the board.

        Returns the verdict with a human-readable reason, the resource classes
        it needs, and whether it would take the local model slot.
        """
        snap = snap if snap is not None else (self.monitor.snapshot()
                                              if self.monitor else None)
        priority = task.get("priority_class") or NORMAL
        local = self._uses_local(task) if self._needs_model(task) else False
        needs = task_resource_needs(task, use_local=local)
        primary = estimate_resource_class(task, use_local=local)
        verdict = {"task_id": task.get("id"),
                   "title": (task.get("title") or "")[:80],
                   "agent_role": task.get("agent_role"),
                   "priority_class": priority,
                   "resource_class": primary, "needs": needs,
                   "needs_model": self._needs_model(task),
                   "local": local, "allowed": True, "reason": "",
                   "throttle": "normal"}
        if snap is None:
            return verdict   # no monitor: admission is not enforced
        # background work yields to a waiting interactive request
        if (self.interactive_preempt and interactive_pending
                and priority_rank(priority) >= priority_rank(BACKGROUND)):
            verdict.update(allowed=False, throttle="defer",
                           reason="interactive request is waiting "
                                  "(background work deferred)")
            return verdict
        if self.policy is None:
            return verdict
        # ONE policy decision for the task's primary class: the CPU/RAM ladder
        # already treats heavy classes differently from light ones.
        dec = self.policy.decide(primary, snap, priority)
        if not dec.allowed:
            verdict.update(allowed=False, throttle=dec.throttle,
                           reason=dec.reason)
            return verdict
        verdict["throttle"] = dec.throttle
        return verdict

    def dispatch_plan(self, max_tasks: int = 4) -> list[dict]:
        """Ordered ready work with an admission verdict per task.

        This is what ``elysia queue`` shows and what ``dispatch_once`` acts on:
        one function decides, so the report can never disagree with behaviour.
        """
        active = self._active_count()
        budget = self.current_budget()
        ordered = self.ordered_ready(limit=max(4, max_tasks * 4))
        snap = self.monitor.snapshot() if self.monitor is not None else None
        interactive_pending = any(
            priority_rank(t.get("priority_class") or NORMAL)
            <= priority_rank(INTERACTIVE) for t in ordered)
        plan = []
        for t in ordered:
            v = self.admit(t, interactive_pending=interactive_pending, snap=snap)
            if v["allowed"] and active + len([p for p in plan
                                              if p["allowed"]]) \
                    >= self.max_concurrency:
                v.update(allowed=False, throttle="defer",
                         reason=f"max_concurrency {self.max_concurrency} reached")
            elif v["allowed"] and len([p for p in plan if p["allowed"]]) >= budget:
                v.update(allowed=False, throttle="defer",
                         reason=f"adaptive worker budget {budget} reached")
            plan.append(v)
        with self._reserved_mu:
            self._verdicts = {v["task_id"]: v for v in plan}
        return plan

    def why_waiting(self) -> list[dict]:
        """Ready tasks that are NOT startable, and exactly why."""
        with self._reserved_mu:
            verdicts = dict(self._verdicts)
        out = []
        for tid, v in verdicts.items():
            if v.get("allowed"):
                continue
            row = dict(v)
            row["status"] = "WAITING"
            out.append(row)
        return sorted(out, key=lambda r: (priority_rank(r.get("priority_class")),
                                          r.get("task_id") or 0))

    def dispatch_once(self, capabilities=None, max_tasks: int = 4) -> list[dict]:
        """Claim startable tasks for anonymous worker slots.

        Ordering, resource admission, provider binding and slot holding all
        come from ``dispatch_plan`` so the report and the behaviour agree.
        """
        claimed = []
        for verdict in self.dispatch_plan(max_tasks=max_tasks):
            if not verdict["allowed"]:
                self.events.emit("scheduler", status="deferred",
                                 task_id=verdict["task_id"],
                                 detail=verdict["reason"][:200])
                continue
            if len(claimed) >= max_tasks:
                break
            task = self.store.get(verdict["task_id"])
            if not task:
                continue
            tid = task["id"]
            # hold the resource class BEFORE the work starts (requirement 20)
            slot = None
            if self.ledger is not None:
                slot = self.ledger.reserve(verdict["resource_class"],
                                           owner=f"task-{tid}",
                                           priority=verdict["priority_class"],
                                           check_policy=False)
                if slot is None:
                    self.events.emit("scheduler", status="deferred", task_id=tid,
                                     detail=f"no {verdict['resource_class']} slot")
                    continue
            res, target, why = None, None, ""
            if verdict["needs_model"]:
                res, target, why = self._reserve_for(task, capabilities)
                if res is None:
                    if slot is not None and self.ledger is not None:
                        self.ledger.release(slot)
                    self.events.emit("scheduler", status="deferred", task_id=tid,
                                     detail=(why or "no provider slot")[:200])
                    continue
            provider_name, model_name = self.worker_id, ""
            if res is not None:
                provider_name = res.provider.name
                model_name = res.provider.cfg.model
            if not self.store.claim(tid, self.worker_id, provider_name or None,
                                    model_name or None, self.lease_seconds):
                if res is not None:
                    res.release()
                if slot is not None and self.ledger is not None:
                    self.ledger.release(slot)
                continue
            with self._reserved_mu:
                if res is not None:
                    self._reserved[tid] = res   # held until finish/cancel
                if slot is not None:
                    self._held_slots[tid] = slot
            self.events.emit("task.claimed", task_id=tid,
                             agent_id=self.worker_id, provider=provider_name,
                             model=model_name, status="claimed",
                             detail=f"class={verdict['resource_class']} "
                                    f"priority={verdict['priority_class']}"
                                    + (f" route={target}" if target else ""))
            claimed.append(self.store.get(tid))
        return claimed

    def _reserve_for(self, task, capabilities=None) -> tuple:
        """Book the model slot for a task BEFORE it starts.

        Returns ``(reservation, target, why)``. The target is decided by the
        shared router: a ``local_only`` task may only take the local slot (and
        then waits rather than being sent away), while a normal task overflows
        to a remote/CLI provider when the local slot is occupied — which is
        exactly the "prefer remote when local compute is saturated" rule.
        """
        caps = set(capabilities or []) or set(self._role_caps(
            task.get("agent_role")) or [])
        local_only = self._uses_local(task)
        try:
            locals_ = self.providers.local_providers()
        except AttributeError:
            locals_ = []
        if local_only:
            if not locals_:
                return None, "local", ("task is local_only but no local "
                                       "provider is configured")
            r = self.providers.reserve(capabilities=caps or None,
                                       preferred=locals_[0].name)
            if r is None:
                return None, "local", self._why_local_refused(caps)
            return r, "local", ""
        preferred, target, why = None, "local", ""
        if self.router is not None:
            decision = self.router.decide(task)
            target = decision.get("target") or "local"
            why = decision.get("why") or ""
            if target == "remote":
                preferred = decision.get("provider")
        r = self.providers.reserve(capabilities=caps or None, preferred=preferred)
        if r is None and target == "remote":
            # remote preferred but unavailable: fall back to local rather than
            # leaving the machine idle
            r = self.providers.reserve(capabilities=caps or None,
                                       preferred=(locals_[0].name if locals_
                                                  else None))
            if r is not None:
                target = "local"
        if r is None:
            return None, target, why or "no provider slot free"
        return r, target, ""

    def _why_local_refused(self, caps) -> str:
        """Honest reason the local provider's slot could not be taken."""
        try:
            locals_ = self.providers.local_providers()
        except AttributeError:
            return "no local provider available"
        if not locals_:
            return "no local provider available"
        p = locals_[0]
        missing = sorted(set(caps) - set(p.cfg.capabilities or []))
        if missing:
            return (f"local provider {p.name} is missing capabilities "
                    f"{missing} this role needs")
        if p.cfg.concurrency <= 0 or p.in_flight >= p.cfg.concurrency:
            return f"local model slot occupied by another task ({p.name})"
        if p.circuit_state() == getattr(p, "OPEN", "open"):
            return (f"local provider {p.name} quarantined "
                    f"({p.cooldown_remaining():.0f}s cooldown left)")
        return f"local model slot unavailable ({p.name})"

    def _reserve_provider(self, task, capabilities):
        """Atomically select AND hold a provider slot for this task.

        Returns a held ProviderReservation (slot acquired) or None. The slot
        stays held until the task is finished/cancelled or the worker is
        declared stale — two schedulers can never both hold the final slot.
        """
        caps = set(capabilities or [])
        if not caps:
            caps = self._role_caps(task.get("agent_role")) or set()
        return self.providers.reserve(capabilities=caps) or None

    def release_reserved(self, task_id: int) -> None:
        """Return every slot a task holds (provider + resource). Idempotent."""
        with self._reserved_mu:
            res = self._reserved.pop(task_id, None)
            slot = self._held_slots.pop(task_id, None)
        if res is not None:
            try:
                res.release()
            except Exception as e:  # noqa: BLE001 — never leak the local slot
                self.events.emit("scheduler", status="error", task_id=task_id,
                                 error=f"provider release failed: {e}"[:200])
        if slot is not None and self.ledger is not None:
            self.ledger.release(slot)

    def resource_status(self) -> dict:
        """Live resource view for the CLI/HUD: limits, holders, waiting tasks."""
        snap = self.monitor.snapshot() if self.monitor is not None else None
        out = {
            "snapshot": snap.as_dict() if snap is not None else None,
            "limits": self.policy.limits() if self.policy is not None else {},
            "ledger": self.ledger.status() if self.ledger is not None else {},
            "running": self.store.counts(),
            "waiting": self.why_waiting(),
            "budget": self.current_budget(),
            "max_concurrency": self.max_concurrency,
        }
        if out["snapshot"]:
            out["snapshot"].pop("per_process", None)
        return out

    def reservation_for(self, task_id: int):
        """The held ProviderReservation for a claimed task, if any."""
        with self._reserved_mu:
            return self._reserved.get(task_id)

    @staticmethod
    def _role_caps(role):
        mapping = {
            "planner": {"chat", "reasoning"},
            "architect": {"chat", "reasoning"},
            "implementer": {"chat", "coding"},
            "tester": {"chat", "coding"},
            "debugger": {"chat", "coding", "reasoning"},
            "code_reviewer": {"chat", "reasoning"},
            "security_reviewer": {"chat", "reasoning"},
            "documentation_agent": {"chat"},
            "research_agent": {"chat", "reasoning"},
            "integration_agent": {"chat", "coding"},
            "release_agent": {"chat"},
        }
        return mapping.get(role)

    def _active_count(self) -> int:
        counts = self.store.counts()
        return counts.get("claimed", 0) + counts.get("running", 0) + \
               counts.get("testing", 0) + counts.get("reviewing", 0)

    def current_budget(self) -> int:
        """Adaptive worker budget based on RAM/CPU right now."""
        base = local_worker_budget(reserve_mb=self.reserve_mb,
                                   worker_mb=self.worker_est_mb,
                                   max_cpu_fraction=0.8)
        if self.resources is not None:
            if self.resources.memory_pressure():
                base = max(1, base // 2)
        return base

    # -- worker-facing helpers ----------------------------------------------
    def heartbeat(self, task_id: int, worker: str) -> bool:
        self.workers.heartbeat(worker)
        ok = self.store.heartbeat(task_id, worker, self.lease_seconds)
        if not ok:
            self.events.emit("heartbeat_failed", task_id=task_id, agent_id=worker)
        return ok

    def finish(self, task_id: int, worker: str, status: str, result: str = "",
               test_status: str | None = None) -> None:
        self.store.complete(task_id, status, result or "", test_status)
        self.release_reserved(task_id)
        self.events.emit("task.finished", task_id=task_id, agent_id=worker,
                         status=status, result=(result or "")[:200])

    def cancel(self, task_id: int, by: str = "user") -> list[int]:
        affected = self.store.cancel(task_id, by=by, deps_cascade=True)
        for tid in affected:
            self.release_reserved(tid)
            self.events.emit("task.cancelled", task_id=tid, status="cancelled",
                             by=by)
        return affected

    # -- in-process execution --------------------------------------------------
    def execute_claimed(self, task: dict, workspace_root: str,
                        run_tests: bool = True, timeout_s=600) -> dict:
        """Execute a claimed task to completion in THIS process.

        Runs the AgentPipeline stage chain (implementer -> QA -> tester ->
        reviewer) against the real Workspace, reusing the provider slot the
        scheduler reserved at dispatch time. ALWAYS resolves the task at the
        end: completed on success; failed/retrying on pipeline failure or
        exception (the retry/backoff policy then applies) — an externally
        claimed task (no held reservation) is finished the same way, so no
        task is ever left stuck mid-flight.
        Returns {"ok", "status", "result"}.
        """
        from .agents import AgentPipeline

        tid = task.get("id")
        res = self.reservation_for(tid)
        pipeline = AgentPipeline(self.providers, self.store, events=self.events,
                                 cfg=self.cfg)
        try:
            outcome = pipeline.solve_task(task, workspace_root,
                                          reservation=res,
                                          run_tests=run_tests)
        except Exception as e:  # noqa: BLE001 — never leave the task mid-air
            outcome = {"ok": False, "error": f"pipeline exception: "
                                              f"{type(e).__name__}: {e}"}
        ok = bool(outcome.get("ok"))
        self.finish(tid, self.worker_id,
                    "completed" if ok else "failed",
                    outcome.get("result") or outcome.get("error") or "")
        return outcome
