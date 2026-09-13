"""Dependency-aware scheduler with leases, heartbeats and retries.

The scheduler owns the task lifecycle: it picks dependency-eligible tasks,
claims them for a worker (via the provider manager), tracks heartbeats, and
auto-releases tasks whose lease expires. A crashed worker loses its lease; the
task returns to the queue automatically (until max_attempts).
"""
from __future__ import annotations

import os
import threading
import time

from .events import EventBus
from .providers import ProviderManager
from .resources import available_memory_mb
from .tasks import TaskStore


class Scheduler:
    def __init__(self, store: TaskStore, providers: ProviderManager,
                 events: EventBus, cfg=None, worker_id: str = "sched"):
        self.store = store
        self.providers = providers
        self.events = events
        self.cfg = cfg
        self.worker_id = worker_id
        self.max_attempts = getattr(cfg.scheduler, "max_attempts", 3) if cfg else 3
        self.lease_seconds = getattr(cfg.scheduler, "lease_seconds", 1200) if cfg else 1200
        self._stop = threading.Event()
        self._workers: dict[str, threading.Thread] = {}
        self._mu = threading.Lock()

    # -- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Start the background loop that releases expired leases."""
        t = threading.Thread(target=self._loop, daemon=True, name="sched-loop")
        t.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                retried = self.store.release_expired(self.max_attempts)
                for tid in retried:
                    self.events.emit("task_released", task_id=tid,
                                     status="released",
                                     error="lease expired")
                if retried:
                    self.events.emit("scheduler", status="ok",
                                     detail=f"released {len(retried)} expired tasks")
            except Exception as e:
                self.events.emit("scheduler", status="error", error=str(e))
            self._stop.wait(10)

    # -- dispatch -------------------------------------------------------------
    def dispatch_once(self, capabilities=None, max_tasks: int = 4) -> list[dict]:
        """Claim eligible tasks for anonymous worker slots.

        Returns the claimed task dicts. No hard-coded total cap — bounded by
        `max_tasks`, provider slots and resource budget. This is a building
        block: a real pooled runner calls it in a loop.
        """
        claimed = []
        ready = self.store.ready_tasks()
        for task in ready:
            if len(claimed) >= max_tasks:
                break
            provider = self.providers.select(capabilities)
            if provider is None:
                self.events.emit("scheduler", status="no_provider",
                                 task_id=task["id"])
                continue
            if not self.store.claim(task["id"], self.worker_id,
                                    provider.name, provider.cfg.model,
                                    self.lease_seconds):
                continue
            self.events.emit("task_claimed", task_id=task["id"],
                             agent_id=self.worker_id,
                             provider=provider.name,
                             model=provider.cfg.model, status="claimed")
            claimed.append(self.store.get(task["id"]))
        return claimed

    def heartbeat(self, task_id: int, worker: str) -> bool:
        ok = self.store.heartbeat(task_id, worker, self.lease_seconds)
        if not ok:
            self.events.emit("heartbeat_failed", task_id=task_id, agent_id=worker)
        return ok

    def finish(self, task_id: int, worker: str, status: str, result: str = "",
               test_status: str | None = None) -> None:
        self.store.complete(task_id, status, result or "", test_status)
        self.events.emit("task_finished", task_id=task_id, agent_id=worker,
                         status=status, result=(result or "")[:200])

    # -- resource-aware worker budget ----------------------------------------
    def worker_budget(self, reserve_mb: int = 1536, worker_mb: int = 600) -> int:
        from .resources import local_worker_budget
        return local_worker_budget(reserve_mb=reserve_mb, worker_mb=worker_mb)