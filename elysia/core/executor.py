"""In-process task execution: the canonical scheduler's worker side.

``TaskExecutor`` turns the scheduler from a recovery-only loop into the live
execution engine:

    dispatch_once() claims a task + holds a provider slot (atomic)
      -> TaskExecutor claims next budgeted task
        -> runs AgentPipeline.solve_task() IN THIS PROCESS (logical agents as
           pipeline stages — planner/implementer/tester/reviewer roles, NOT
           one OS process per agent)
        -> real Workspace writes + language-aware QA + git-diff review
        -> heartbeats the lease from a side thread during model calls
        -> completion / retry-with-backoff / terminal failure persisted in
           the TaskStore (durable across server restarts)

Resource-gated: never more than ``max_concurrency`` tasks in flight, and the
scheduler's budget gate (RAM/CPU) bounds how many are claimed. On stop, tasks
are released (not abandoned): their leases expire and the scheduler re-dispatches
them on the next start — the workflow survives the process.
"""
from __future__ import annotations

import threading
import time

from .agents import AgentPipeline
from .config import Config
from .events import EventBus
from .providers import ProviderManager
from .scheduler import Scheduler
from .tasks import TaskStore


class TaskExecutor:
    def __init__(self, scheduler: Scheduler, workspace_root: str,
                 max_tasks: int = 2, run_tests: bool = True,
                 heartbeat_interval_s: float = 120.0,
                 poll_interval_s: float = 2.0,
                 retry_backoff_s: float | None = None,
                 capabilities: list[str] | None = None,
                 tools=None, memory=None, resources=None):
        self.sched = scheduler
        self.store: TaskStore = scheduler.store
        self.providers: ProviderManager = scheduler.providers
        self.events: EventBus = scheduler.events
        self.workspace_root = workspace_root
        self.max_tasks = max(1, int(max_tasks))
        self.run_tests = run_tests
        self.heartbeat_interval_s = heartbeat_interval_s
        self.poll_interval_s = poll_interval_s
        self.capabilities = capabilities or ["chat", "coding"]
        self.retry_backoff_s = retry_backoff_s   # None -> pipeline default (30s)
        # Permissioned tool layer shared by every pipeline this executor runs.
        self.tools = tools
        # Layered memory (Phase 9) and resource manager shared by every
        # pipeline — one store per process, never one per task.
        self.memory = memory
        self.resources = resources
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._inflight: set[int] = set()
        self._inflight_mu = threading.Lock()
        self.stats = {"executed": 0, "failed": 0, "retried": 0}

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> None:
        self._stop.clear()
        t = threading.Thread(target=self._loop, name="elysia-executor",
                             daemon=True)
        t.start()
        self._threads.append(t)
        self.events.emit("executor", status="started",
                         detail=f"max_tasks={self.max_tasks}")

    def stop(self, join_s: float = 5.0) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=join_s)
        self.events.emit("executor", status="stopped")

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def inflight(self) -> list[int]:
        with self._inflight_mu:
            return sorted(self._inflight)

    # -- main loop -----------------------------------------------------------
    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001 — executor must survive
                self.events.emit("executor", status="error",
                                 error=str(e)[:300])
            self._stop.wait(self.poll_interval_s)

    def tick(self) -> list[int]:
        """Claim up to the remaining budget and execute in parallel threads.

        Returns the task ids claimed this tick. Budget = max_tasks minus what
        is already in flight; the scheduler's own gates (global concurrency,
        provider slots, RAM budget) still apply underneath.
        """
        with self._inflight_mu:
            budget = self.max_tasks - len(self._inflight)
        if budget <= 0 or self._stop.is_set():
            return []
        claimed = self.sched.dispatch_once(capabilities=self.capabilities,
                                           max_tasks=budget)
        started = []
        for task in claimed:
            tid = task["id"]
            with self._inflight_mu:
                if tid in self._inflight:
                    continue
                self._inflight.add(tid)
            t = threading.Thread(target=self._run_one, args=(task,),
                                 name=f"exec-{tid}", daemon=True)
            t.start()
            started.append(tid)
        return started

    # -- single task ----------------------------------------------------------
    def _run_one(self, task: dict) -> None:
        tid = task["id"]
        worker = self.sched.worker_id
        hb_stop = threading.Event()
        hb = threading.Thread(target=self._heartbeat_loop,
                              args=(tid, worker, hb_stop), daemon=True)
        hb.start()
        try:
            pipeline = AgentPipeline(self.providers, self.store,
                                     events=self.events, cfg=self._cfg(),
                                     tools=self.tools, memory=self.memory,
                                     resources=self.resources)
            if self.retry_backoff_s is not None:
                pipeline._backoff_s = lambda: float(self.retry_backoff_s)
            outcome = pipeline.solve_task(task, self.workspace_root,
                                          reservation=self.sched.reservation_for(tid),
                                          run_tests=self.run_tests)
            ok = bool(outcome.get("ok"))
            result = outcome.get("result") or outcome.get("error") or ""
            if ok:
                # solve_task completes to "reviewing"; finish the lifecycle.
                # The task is ALREADY effectively done once the store records
                # it, so a failure while finalising (releasing the provider
                # slot, emitting the event) must not be reported as a task
                # failure — it is counted as executed and logged as such.
                try:
                    self.sched.finish(tid, worker, "completed", result)
                except Exception as e:  # noqa: BLE001
                    self.events.emit("executor", status="finalise_failed",
                                     task_id=tid, agent_id=worker,
                                     error=f"finish failed after completion: {e}"[:200])
                self.stats["executed"] += 1
                self.events.emit("task.completed", task_id=tid, status="completed",
                                 agent_id=worker)
            else:
                self._handle_failure(tid, worker, result)
            self.events.emit("executor", status="task_done", task_id=tid,
                             agent_id=worker, error=None if ok else result[:200])
        except Exception as e:  # noqa: BLE001 — a crash must not wedge the slot
            self._handle_failure(tid, worker, f"executor exception: {e}")
        finally:
            hb_stop.set()
            with self._inflight_mu:
                self._inflight.discard(tid)

    def _handle_failure(self, tid: int, worker: str, reason: str) -> None:
        """Resolve a failed task via the store's retry policy.

        ``AgentPipeline.solve_task`` already calls ``fail_attempt`` when a
        stage fails (ready + backoff, or terminal failed at the cap), so only
        resolve here if the pipeline crashed before doing so. Then report the
        outcome the store actually recorded.
        """
        t = self.store.get(tid)
        if t is None:
            return
        if t["status"] in ("completed", "done", "cancelled"):
            # Already resolved (e.g. a late exception after a successful
            # finalise): never rewrite a finished task or fake a retry.
            self.sched.release_reserved(tid)
            return
        self.stats["failed"] += 1
        if t["status"] not in ("ready", "failed"):
            # pipeline exception path: apply the retry policy now
            before = t["status"]
            try:
                self.store.fail_attempt(tid, reason[:500], backoff_s=30)
            except ValueError as e:
                # illegal edge (a race with recovery/cancel): report, never crash
                self.events.emit("executor", status="unresolvable_failure",
                                 task_id=tid, agent_id=worker,
                                 error=f"{before} -> retry refused: {e}"[:200])
            t = self.store.get(tid)
        if t["status"] == "ready":
            self.stats["retried"] += 1
            self.events.emit("task.retrying", task_id=tid, status="retrying",
                             agent_id=worker, error=reason[:200])
        else:
            self.events.emit("task.failed", task_id=tid, status="failed",
                             agent_id=worker, error=reason[:200])
        self.sched.release_reserved(tid)

    def _heartbeat_loop(self, tid: int, worker: str, stop: threading.Event) -> None:
        """Keep the lease alive while the pipeline runs (long model calls)."""
        lease = self.sched.lease_seconds
        while not stop.wait(self.heartbeat_interval_s):
            if not self.store.heartbeat(tid, worker, lease):
                return   # lease was taken away (recovery) — stop renewing

    def _cfg(self):
        """The scheduler's Config when real (AgentPipeline handles None)."""
        return self.sched.cfg if isinstance(self.sched.cfg, Config) else None
