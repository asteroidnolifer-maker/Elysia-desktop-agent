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
from .resources import local_worker_budget
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
                 worker_id: str = "sched", resources=None):
        self.store = store
        self.providers = providers
        self.events = events or EventBus()
        self.cfg = cfg
        self.worker_id = worker_id
        self.resources = resources  # optional ResourceManager
        if cfg is not None:
            sc = getattr(cfg, "scheduler", None) or cfg
            self.max_concurrency = getattr(sc, "max_concurrency", 4)
            self.max_attempts = getattr(sc, "max_attempts", 3)
            self.lease_seconds = getattr(sc, "lease_seconds", 1200)
            self.heartbeat_grace_s = getattr(sc, "heartbeat_grace_s", 60)
            self.reserve_mb = getattr(sc, "resource_reserve_mb", 1536)
            self.worker_est_mb = getattr(sc, "worker_est_mb", 600)
        else:
            self.max_concurrency = 4
            self.max_attempts = 3
            self.lease_seconds = 1200
            self.heartbeat_grace_s = 60
            self.reserve_mb = 1536
            self.worker_est_mb = 600
        self.workers = WorkerRegistry(self.heartbeat_grace_s * 3)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

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
            self.events.emit("task.lease_expired", task_id=tid, status="ready")
        # 3) per-task timeouts
        for t in self.store.list(status="claimed"):
            ts = t.get("timeout_s")
            if ts and t.get("started_at") and now - t["started_at"] > ts:
                self.store.timeout_task(t["id"])
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
                self.events.emit("task.worker_lost", task_id=tid, worker=w,
                                 status="ready")
            self.workers.expire(w)
            self.events.emit("worker.crashed", agent_id=w, status="expired")

    # -- dispatch -------------------------------------------------------------
    def dispatch_once(self, capabilities=None, max_tasks: int = 4) -> list[dict]:
        """Claim eligible tasks for anonymous worker slots.

        Respects resource budget, provider slots, and global concurrency. The
        caller then runs each returned task to completion (see `run_claimed`).
        """
        claimed = []
        ready = self.store.ready_tasks(limit=max_tasks * 4)
        active = self._active_count()
        budget = self.current_budget()
        for task in ready:
            if len(claimed) >= max_tasks:
                break
            if active + len(claimed) >= self.max_concurrency:
                break
            if len(claimed) >= budget:
                break
            provider = self._select_provider(task, capabilities)
            if provider is None:
                self.events.emit("scheduler", status="no_provider",
                                 task_id=task["id"])
                continue
            if not self.store.claim(task["id"], self.worker_id,
                                    provider.name, provider.cfg.model,
                                    self.lease_seconds):
                continue
            self.events.emit("task.claimed", task_id=task["id"],
                             agent_id=self.worker_id, provider=provider.name,
                             model=provider.cfg.model, status="claimed")
            claimed.append(self.store.get(task["id"]))
        return claimed

    def _select_provider(self, task, capabilities):
        caps = set(capabilities or [])
        if not caps:
            caps = self._role_caps(task.get("agent_role"))
        return self.providers.select(capabilities=caps or None)

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
        self.events.emit("task.finished", task_id=task_id, agent_id=worker,
                         status=status, result=(result or "")[:200])

    def cancel(self, task_id: int, by: str = "user") -> list[int]:
        affected = self.store.cancel(task_id, by=by, deps_cascade=True)
        for tid in affected:
            self.events.emit("task.cancelled", task_id=tid, status="cancelled",
                             by=by)
        return affected
