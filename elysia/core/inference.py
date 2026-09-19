"""Shared local model: one loaded model, many logical agents.

Dozens of logical agents do NOT each get a model process. They submit
*requests* to :class:`LocalModelPool`, which serializes them onto the single
local provider slot (``local_llm_concurrency``, default 1 on the target
machine) while keeping every request's prompt, context, memory and permissions
isolated.

The pool provides:

  - a priority queue (CRITICAL..IDLE) with aging, so a long background coding
    agent can never starve a short interactive request
  - cancellation, per-request timeouts and task/agent ownership
  - a hard cap on simultaneous local inference (default 1 — never "one model
    process per logical agent")
  - warm-state tracking plus idle unloading, with hysteresis so a model is not
    loaded/unloaded repeatedly

Batching is only attempted when the backend genuinely declares support
(``ProviderConfig.batch``); otherwise the pool says so plainly instead of
pretending to batch.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field

from .resources import (
    INTERACTIVE, LOCAL_LLM, NORMAL, REMOTE_LLM, ResourceLedger,
    ResourceMonitor, ResourcePolicy, priority_rank,
)


@dataclass
class InferenceRequest:
    id: int
    messages: list
    capabilities: set
    owner_task: int | None = None
    owner_agent: str = ""
    priority: str = NORMAL
    timeout_s: float | None = None
    cancel_event: threading.Event | None = None
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    text: str = ""
    error: str = ""
    status: str = "queued"      # queued | running | done | failed | cancelled | timeout
    provider: str = ""
    model: str = ""
    done: threading.Event = field(default_factory=threading.Event)

    def age(self) -> float:
        return max(0.0, time.time() - self.created_at)

    def sort_key(self) -> tuple:
        """Priority rank, lifted by age so nothing waits forever."""
        return (priority_rank(self.priority) - self.age() / 30.0,
                self.created_at)

    def as_dict(self) -> dict:
        return {"id": self.id, "owner_task": self.owner_task,
                "owner_agent": self.owner_agent, "priority": self.priority,
                "status": self.status, "age_s": round(self.age(), 1),
                "waiting_s": round((self.started_at or time.time())
                                   - self.created_at, 1),
                "provider": self.provider, "model": self.model,
                "error": self.error[:200] if self.error else ""}


class LocalModelPool:
    """One (or few) local model slot(s), shared by every logical agent."""

    def __init__(self, providers, ledger: ResourceLedger | None = None,
                 monitor: ResourceMonitor | None = None, events=None,
                 cfg=None, max_concurrent: int = 1,
                 default_timeout_s: float = 900.0,
                 poll_interval_s: float = 0.5,
                 warm=None):
        self.providers = providers
        self.ledger = ledger
        self.monitor = monitor
        self.events = events
        self.cfg = cfg
        self.max_concurrent = max(1, int(max_concurrent))
        self.default_timeout_s = float(default_timeout_s)
        self.poll_interval_s = poll_interval_s
        self.warm = warm or WarmModelRegistry.from_config(cfg)
        self._queue: list[InferenceRequest] = []
        self._running: dict[int, InferenceRequest] = {}
        self._cond = threading.Condition()
        self._next_id = 1
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self.stats = {"submitted": 0, "completed": 0, "failed": 0,
                      "cancelled": 0, "timed_out": 0, "deferred": 0,
                      "waited_s": 0.0, "inference_s": 0.0}
        self._defer_reasons: dict[int, str] = {}
        self._local_name_cache: str | None = None

    @classmethod
    def from_config(cls, providers, ledger=None, monitor=None, events=None,
                    cfg=None) -> "LocalModelPool":
        rc = getattr(cfg, "resources", cfg) or None

        def g(name, default):
            return getattr(rc, name, default) if rc is not None else default
        return cls(providers, ledger=ledger, monitor=monitor, events=events,
                   cfg=cfg, max_concurrent=int(g("local_llm_concurrency", 1)),
                   default_timeout_s=float(g("inference_timeout_s", 900.0)))

    # -- lifecycle -----------------------------------------------------------
    def start(self) -> "LocalModelPool":
        if self._threads and any(t.is_alive() for t in self._threads):
            return self
        self._stop.clear()
        for i in range(self.max_concurrent):
            t = threading.Thread(target=self._worker_loop, name=f"llm-slot-{i}",
                                 daemon=True)
            t.start()
            self._threads.append(t)
        self._emit("pool", status="started",
                   detail=f"{self.max_concurrent} local model slot(s)")
        return self

    def stop(self, join_s: float = 2.0) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        for t in self._threads:
            t.join(timeout=join_s)

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def _emit(self, event_type: str, **kw):
        if self.events is not None:
            try:
                self.events.emit(event_type, **kw)
            except Exception:  # noqa: BLE001 — observability must never break
                pass

    # -- submission ----------------------------------------------------------
    def submit(self, messages, capabilities=None, owner_task=None,
               owner_agent: str = "", priority: str = NORMAL,
               timeout_s: float | None = None,
               cancel_event: threading.Event | None = None) -> dict:
        """Queue one inference and block until it completes (or times out).

        The request carries its own messages/context — that is the context
        isolation: many logical agents share the model, never each other's
        state.
        """
        if self.providers is None:
            return {"ok": False, "error": "no provider manager", "status": "error"}
        timeout_s = self.default_timeout_s if timeout_s is None else timeout_s
        with self._cond:
            rid = self._next_id
            self._next_id += 1
            req = InferenceRequest(id=rid, messages=messages,
                                   capabilities=set(capabilities or []),
                                   owner_task=owner_task,
                                   owner_agent=owner_agent, priority=priority,
                                   timeout_s=timeout_s,
                                   cancel_event=cancel_event,
                                   created_at=time.time())
            self._queue.append(req)
            self.stats["submitted"] += 1
            self._cond.notify_all()
        self._emit("inference.queued", task_id=owner_task, agent_id=owner_agent,
                   status=priority, detail=f"request #{rid}")
        deadline = time.time() + timeout_s if timeout_s else None
        while not req.done.wait(self.poll_interval_s):
            if cancel_event is not None and cancel_event.is_set():
                break
            if deadline is not None and time.time() > deadline:
                break
        # a request that finished its wait but was never dispatched (timeout or
        # cancel) must be removed from the queue so it can never run later.
        requeue_removed = False
        with self._cond:
            if not req.done.is_set():
                if req in self._queue:
                    self._queue.remove(req)
                    requeue_removed = True
                if cancel_event is not None and cancel_event.is_set():
                    req.status = "cancelled"
                    self.stats["cancelled"] += 1
                elif req.status in ("queued", "running") and req.status != "running":
                    req.status = "timeout"
                    self.stats["timed_out"] += 1
                elif req.status == "queued":
                    req.status = "timeout"
                    self.stats["timed_out"] += 1
                req.done.set()
            text, err, status = req.text, req.error, req.status
        if requeue_removed:
            self._emit("inference.removed", task_id=owner_task,
                       status=status, detail="timeout/cancel before dispatch")
        ok = status == "done" and not err
        return {"ok": ok, "text": text, "error": err, "status": status,
                "provider": req.provider, "model": req.model,
                "request_id": req.id,
                "waited_s": round((req.started_at or req.finished_at or
                                   time.time()) - req.created_at, 2)}

    # -- worker --------------------------------------------------------------
    def _local_provider(self):
        """The local provider this pool serves (first healthy local one)."""
        try:
            locals_ = list(self.providers.local_providers())
        except (AttributeError, TypeError):
            locals_ = []
        if not locals_:
            return None
        unavailable = getattr(locals_[0], "UNAVAILABLE", "unavailable")
        open_state = getattr(locals_[0], "OPEN", "open")
        healthy = [p for p in locals_ if getattr(p, "status", None) != unavailable
                   and p.circuit_state() != open_state]
        return (healthy or locals_)[0]

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                req = self._next_ready()
            except Exception as e:  # noqa: BLE001 — a slot thread must not die
                self._emit("inference.error", status="error",
                           error=f"dequeue failed: {type(e).__name__}: {e}"[:200])
                req = None
            if req is None:
                with self._cond:
                    self._cond.wait(self.poll_interval_s)
                continue
            try:
                self._run(req)
            except Exception as e:  # noqa: BLE001
                # A broken request/provider must never kill the model slot
                # (every queued request would then wait out its full timeout).
                self.stats["failed"] += 1
                self._finish(req, "", f"pool error: {type(e).__name__}: {e}",
                             "failed")

    def _next_ready(self) -> InferenceRequest | None:
        with self._cond:
            ready = [r for r in self._queue
                     if not (r.cancel_event is not None
                             and r.cancel_event.is_set())]
            # drop cancelled requests
            for r in list(self._queue):
                if r.cancel_event is not None and r.cancel_event.is_set():
                    r.status, r.error = "cancelled", "cancelled before start"
                    self._queue.remove(r)
                    self.stats["cancelled"] += 1
                    r.done.set()
            if not ready:
                return None
            ready.sort(key=lambda r: r.sort_key())
            req = ready[0]
            self._queue.remove(req)
            self._running[req.id] = req
            return req

    def _requeue(self, req: InferenceRequest) -> None:
        with self._cond:
            self._running.pop(req.id, None)
            if req.cancel_event is not None and req.cancel_event.is_set():
                req.status, req.error = "cancelled", "cancelled while waiting"
                self.stats["cancelled"] += 1
                req.done.set()
                return
            self._queue.append(req)

    def _run(self, req: InferenceRequest) -> None:
        """Execute one queued request on the shared local slot.

        The slot is released in a single ``finally``, so no failure path can
        leak the heaviest resource on the machine.
        """
        res = None
        if self.ledger is not None:
            res = self.ledger.reserve(LOCAL_LLM, owner=f"infer-{req.id}",
                                      priority=req.priority,
                                      check_policy=True)
            if res is None:
                # admitted later, not failed: the machine has no capacity now
                self._requeue(req)
                self._defer(req, self._last_defer_reason())
                time.sleep(min(1.0, self.poll_interval_s))
                return
        try:
            prov = self._local_provider()
            if prov is None:
                self._finish(req, "", "no local provider configured", "failed")
                return
            # hold the provider's own concurrency slot (health/breaker/budget)
            prov_err = ""
            try:
                reservation = self.providers.reserve(
                    capabilities=req.capabilities, preferred=prov.name)
            except Exception as e:  # noqa: BLE001
                reservation = None
                prov_err = f"reserve failed: {type(e).__name__}: {e}"
            if reservation is None:
                self._finish(req, "", prov_err or "local provider unavailable",
                             "failed")
                return
            req.status = "running"
            req.started_at = time.time()
            req.provider = getattr(reservation.provider, "name", "") or prov.name
            req.model = getattr(reservation.provider.cfg, "model", "")
            if self.ledger is not None:
                self.ledger.snap_counters()
            self.warm.touch(req.provider)
            self._emit("inference.started", task_id=req.owner_task,
                       agent_id=req.owner_agent, provider=req.provider,
                       model=req.model, status=req.priority)
            t0 = time.time()
            try:
                text, err = reservation.call(req.messages)
            except Exception as e:  # noqa: BLE001
                text, err = "", f"{type(e).__name__}: {e}"
            finally:
                # a release that raises must not leak the slot or kill the thread
                try:
                    reservation.release()
                except Exception as e:  # noqa: BLE001
                    rel_err = f"release failed: {type(e).__name__}: {e}"[:200]
                    err = f"{err}; {rel_err}" if err else rel_err
            dur = time.time() - t0
            self.stats["inference_s"] += dur
            if req.cancel_event is not None and req.cancel_event.is_set():
                self._finish(req, text, err, "cancelled")
            elif err:
                self._finish(req, text, err, "failed")
            else:
                self.stats["completed"] += 1
                self._finish(req, text, "", "done")
        finally:
            if self.ledger is not None and res is not None:
                self.ledger.release(res)

    def _last_defer_reason(self) -> str:
        """Why the ledger refused the slot (for `elysia resources`)."""
        if self.ledger is None:
            return "no capacity"
        waits = self.ledger.waiting()
        if waits:
            return next(iter(waits.values()))
        return "local slot busy or machine under pressure"

    def _defer(self, req: InferenceRequest, reason: str) -> None:
        """Record a deferred request (it stays queued — never silently dropped)."""
        self.stats["deferred"] = self.stats.get("deferred", 0) + 1
        with self._cond:
            self._defer_reasons[req.id] = reason
        self._emit("inference.deferred", task_id=req.owner_task,
                   agent_id=req.owner_agent, status="deferred",
                   detail=reason[:200])

    def _finish(self, req: InferenceRequest, text: str, err: str,
                status: str) -> None:
        with self._cond:
            if req.done.is_set():
                return          # already resolved — never double-count
            self._running.pop(req.id, None)
            req.text, req.error, req.status = text, err, status
            req.finished_at = time.time()
            self.stats["waited_s"] += max(0.0, (req.started_at or
                                                req.finished_at)
                                          - req.created_at)
            if status == "failed":
                self.stats["failed"] += 1
            req.done.set()
            self._cond.notify_all()
        self._emit("inference.finished", task_id=req.owner_task,
                   agent_id=req.owner_agent, provider=req.provider,
                   model=req.model, status=status,
                   error=(err or "")[:200] or None,
                   duration=round(req.finished_at - req.created_at, 3),
                   detail=f"{status} in {req.finished_at - req.started_at:.1f}s"
                          if req.started_at else status)

    # -- introspection -------------------------------------------------------
    def status(self) -> dict:
        with self._cond:
            running = [r.as_dict() for r in self._running.values()]
            queued = [r.as_dict() for r in self._queue]
            defer = dict(self._defer_reasons)
        queued.sort(key=lambda r: (priority_rank(r["priority"]), r["age_s"]))
        for q in queued:
            q["why_waiting"] = defer.get(q["id"], "waiting for the local model slot")
        return {
            "slots": self.max_concurrent,
            "running": running,
            "queued": queued,
            "queued_count": len(queued),
            "stats": dict(self.stats),
            "batching": self.batching(),
            "warm": self.warm.status(),
        }

    def batching(self) -> dict:
        """Honest batching report — never pretend to batch."""

        def backend_supports() -> bool:
            try:
                return any(bool(getattr(p.cfg, "batch", False))
                           for p in self.providers.local_providers())
            except AttributeError:
                return False
        supported = backend_supports()
        return {"enabled": bool(supported),
                "supported_by_backend": supported,
                "note": ("batching on (backend declares support)"
                         if supported else
                         "disabled: the local backend does not declare "
                         "batching, and grouping chat requests would only add "
                         "latency on a 2-core CPU")}


class AnalysisCache:
    """Caches model-INDEPENDENT analysis, invalidated by its actual inputs.

    Deterministic work (repo indexing, test discovery, file hashing, static
    checks) is expensive to repeat and never needs a model. The cache key is a
    hash of the inputs, so a changed input can never return a stale result —
    requirement 27 is structural here, not a policy someone must remember.
    """

    def __init__(self, ttl_s: float = 300.0, max_entries: int = 256):
        self.ttl_s = float(ttl_s)
        self.max_entries = max(1, int(max_entries))
        self._entries: dict[str, tuple[float, object]] = {}
        self._mu = threading.Lock()
        self.stats = {"hits": 0, "misses": 0, "stores": 0, "expired": 0,
                      "evicted": 0}

    @staticmethod
    def key(kind: str, inputs) -> str:
        try:
            blob = json.dumps(inputs, sort_keys=True, default=str)
        except (TypeError, ValueError):
            blob = repr(inputs)
        return f"{kind}:{hashlib.sha1(blob.encode('utf-8','replace')).hexdigest()}"

    def get(self, kind: str, inputs):
        k = self.key(kind, inputs)
        now = time.time()
        with self._mu:
            item = self._entries.get(k)
            if item is None:
                self.stats["misses"] += 1
                return None
            stored_at, value = item
            if now - stored_at > self.ttl_s:
                self._entries.pop(k, None)
                self.stats["expired"] += 1
                self.stats["misses"] += 1
                return None
            self.stats["hits"] += 1
            return value

    def put(self, kind: str, inputs, value) -> None:
        k = self.key(kind, inputs)
        with self._mu:
            self._entries[k] = (time.time(), value)
            self.stats["stores"] += 1
            while len(self._entries) > self.max_entries:
                oldest = min(self._entries.items(), key=lambda kv: kv[1][0])[0]
                self._entries.pop(oldest, None)
                self.stats["evicted"] += 1

    def compute(self, kind: str, inputs, producer):
        """Return the cached value, or call ``producer()`` once and store it."""
        hit = self.get(kind, inputs)
        if hit is not None:
            return hit
        value = producer()
        if value is not None:
            self.put(kind, inputs, value)
        return value

    def invalidate(self, kind: str | None = None) -> int:
        with self._mu:
            if kind is None:
                n = len(self._entries)
                self._entries.clear()
                return n
            keys = [k for k in self._entries if k.startswith(f"{kind}:")]
            for k in keys:
                self._entries.pop(k, None)
            return len(keys)

    def status(self) -> dict:
        with self._mu:
            n = len(self._entries)
        return {"entries": n, "ttl_s": self.ttl_s, **self.stats}


class ModelRouter:
    """One place that decides WHERE a model request runs.

    It is a thin coordinator over the canonical ``ProviderManager`` and the
    ``LocalModelPool`` — it does not select or call providers itself beyond
    reserving a slot, and it never keeps its own model list.

    Decision order:

      1. a scheduler-held reservation is reused (exactly one slot per task);
      2. privacy: a ``local_only`` task may ONLY use the local slot;
      3. when local compute is saturated and a healthy remote/CLI provider is
         configured, route there (the laptop stays responsive);
      4. otherwise queue on the shared local slot.
    """

    def __init__(self, providers, pool=None, ledger=None, monitor=None,
                 policy=None, events=None, cfg=None, cache=None):
        self.providers = providers
        self.pool = pool
        self.ledger = ledger
        self.monitor = monitor
        self.policy = policy
        self.events = events
        self.cfg = cfg
        rc = getattr(cfg, "resources", cfg) or None
        priv = getattr(cfg, "privacy", cfg) or None

        def rg(name, default):
            return getattr(rc, name, default) if rc is not None else default
        self.prefer_remote_when_saturated = bool(
            rg("prefer_remote_when_saturated", True))
        self.local_only_global = bool(getattr(priv, "local_only", False))
        self.cache = cache or AnalysisCache(
            ttl_s=float(rg("analysis_cache_ttl_s", 300)))
        self.stats = {"calls": 0, "local": 0, "remote": 0, "held": 0,
                      "failed": 0, "queued": 0, "cache_hits": 0,
                      "tokens_in": 0, "tokens_out": 0, "local_seconds": 0.0,
                      "remote_seconds": 0.0}

    @classmethod
    def from_config(cls, providers, pool=None, ledger=None, monitor=None,
                    policy=None, events=None, cfg=None, cache=None):
        return cls(providers, pool=pool, ledger=ledger, monitor=monitor,
                   policy=policy, events=events, cfg=cfg, cache=cache)

    # -- policy --------------------------------------------------------------
    @staticmethod
    def _local_only(task, privacy=None, global_local_only=False) -> bool:
        if privacy == "local_only":
            return True
        own = ((task or {}).get("privacy") or "").strip().lower()
        return own == "local_only" or bool(global_local_only)

    def saturation(self) -> dict:
        """Live view of why the local slot may be a bad place to send work."""
        snap = self.monitor.snapshot() if self.monitor is not None else None
        pool_status = self.pool.status() if self.pool is not None else {}
        queued = int(pool_status.get("queued_count") or 0)
        running = len(pool_status.get("running") or [])
        cpu = getattr(snap, "cpu_pct", None)
        ram = getattr(snap, "mem_available_mb", -1)
        busy_local = running >= max(1, int(pool_status.get("slots") or 1))
        dec = None
        if self.policy is not None and snap is not None:
            dec = self.policy.decide(LOCAL_LLM, snap, NORMAL)
        return {"local_running": running, "local_queued": queued,
                "local_busy": busy_local, "cpu_pct": cpu,
                "mem_available_mb": ram,
                "local_admitted": None if dec is None else dec.allowed,
                "local_reason": "" if dec is None else dec.reason}

    def decide(self, task=None, role: str = "", capabilities=None) -> dict:
        """Explain the routing choice for one request (never calls a model)."""
        local_only = self._local_only(task, global_local_only=self.local_only_global)
        sat = self.saturation()
        have_local = bool(self.providers.local_providers())
        remotes = [p for p in self.providers.remote_providers()
                   if p.status != p.UNAVAILABLE and p.circuit_state() != p.OPEN]
        if local_only:
            return {"target": "local", "provider": None, "local_only": True,
                    "why": "task is local_only: this content must not leave "
                           "the machine", "saturation": sat}
        if not have_local:
            if remotes:
                return {"target": "remote", "provider": remotes[0].name,
                        "local_only": False,
                        "why": "no local provider configured", "saturation": sat}
            return {"target": "none", "provider": None, "local_only": False,
                    "why": "no provider available", "saturation": sat}
        if self.prefer_remote_when_saturated and remotes:
            if sat["local_busy"] or sat["local_admitted"] is False \
                    or sat["local_queued"] >= 2:
                why = []
                if sat["local_busy"]:
                    why.append("local model slot is occupied")
                if sat["local_admitted"] is False:
                    why.append(sat["local_reason"] or "local work deferred")
                if sat["local_queued"] >= 2:
                    why.append(f"{sat['local_queued']} local request(s) already "
                               "queued")
                return {"target": "remote", "provider": remotes[0].name,
                        "local_only": False,
                        "why": "local compute saturated — using remote "
                               f"provider ({'; '.join(why)})",
                        "saturation": sat}
        return {"target": "local", "provider": None, "local_only": False,
                "why": "local model slot has capacity", "saturation": sat}

    # -- execution -----------------------------------------------------------
    def call(self, messages, capabilities=None, task=None, role: str = "",
             priority: str = NORMAL, reservation=None, max_tokens=None,
             temperature=None) -> dict:
        """Run one model request and return text + honest usage metadata."""
        tid = (task or {}).get("id")
        caps = set(capabilities or [])
        self.stats["calls"] += 1
        if reservation is not None:
            t0 = time.time()
            text, err = reservation.call_failover(messages, capabilities=caps,
                                                  max_tokens=max_tokens,
                                                  temperature=temperature)
            usage = dict(getattr(reservation, "usage", {}) or {})
            if not usage:
                usage = self._usage_from(messages, text or "", time.time() - t0,
                                         "", "")
            self.stats["held"] += 1
            if err:
                self.stats["failed"] += 1
            self._account(usage)
            return {"ok": not err, "text": text or "", "error": err or "",
                    "usage": usage,
                    "route": {"target": "held", "provider": usage.get("provider", ""),
                              "why": "scheduler-held provider slot"}}

        route = self.decide(task, role=role, capabilities=caps)
        if route["target"] == "local" and self.pool is not None:
            if self.pool.status().get("queued_count"):
                self.stats["queued"] += 1
            res = self.pool.submit(messages, capabilities=caps, owner_task=tid,
                                   owner_agent=role, priority=priority)
            usage = self._usage_from(messages, res.get("text") or "",
                                     res.get("waited_s") or 0.0,
                                     res.get("provider") or "",
                                     res.get("model") or "", local=True)
            usage["ok"] = bool(res.get("ok"))
            if not res.get("ok"):
                self.stats["failed"] += 1
                # a local_only task must NEVER be sent to a remote provider —
                # failing honestly is the correct behaviour.
                return {"ok": False, "text": "",
                        "error": res.get("error") or "local model unavailable",
                        "usage": usage, "route": route}
            self.stats["local"] += 1
            self._account(usage)
            return {"ok": True, "text": res.get("text") or "", "error": "",
                    "usage": usage, "route": route}

        # remote / CLI path (or no local pool configured)
        target = route.get("provider")
        res = self.providers.reserve(capabilities=caps or None, preferred=target)
        if res is None:
            text, err = self.providers.execute(messages, capabilities=caps or None,
                                               max_tokens=max_tokens,
                                               temperature=temperature)
            usage = self._usage_from(messages, text or "", 0.0, "", "")
            ok = not err
            if not ok:
                self.stats["failed"] += 1
            else:
                self.stats["remote"] += 1
            self._account(usage)
            return {"ok": ok, "text": text or "", "error": err or "",
                    "usage": usage, "route": route}
        t0 = time.time()
        text, err = res.call_failover(messages, capabilities=caps,
                                      max_tokens=max_tokens,
                                      temperature=temperature)
        usage = dict(getattr(res, "usage", {}) or {})
        if not usage:
            usage = self._usage_from(messages, text or "", time.time() - t0,
                                     "", "")
        try:
            res.release()
        except Exception:  # noqa: BLE001 — release is idempotent
            pass
        if err:
            self.stats["failed"] += 1
        else:
            self.stats["remote"] += 1
        self._account(usage)
        return {"ok": not err, "text": text or "", "error": err or "",
                "usage": usage, "route": route}

    def _usage_from(self, messages, text, seconds, provider, model,
                    local: bool = False) -> dict:
        from .providers import estimate_tokens
        payload = "\n".join(str(m.get("content", "")) for m in (messages or []))
        return {"provider": provider, "model": model, "local": local,
                "tokens_in": estimate_tokens(payload),
                "tokens_out": estimate_tokens(text or ""),
                "seconds": round(seconds, 3), "ok": True, "estimated": True}

    def _account(self, usage: dict) -> None:
        self.stats["tokens_in"] += int(usage.get("tokens_in") or 0)
        self.stats["tokens_out"] += int(usage.get("tokens_out") or 0)
        if usage.get("local"):
            self.stats["local_seconds"] += float(usage.get("seconds") or 0.0)
        else:
            self.stats["remote_seconds"] += float(usage.get("seconds") or 0.0)

    def status(self) -> dict:
        return {"stats": dict(self.stats),
                "saturation": self.saturation(),
                "cache": self.cache.status(),
                "prefer_remote_when_saturated": self.prefer_remote_when_saturated,
                "local_only": self.local_only_global}


class WarmModelRegistry:
    """Tracks which local models are warm, and unloads idle ones under pressure.

    Hysteresis prevents thrash: a model is only unloaded when memory pressure
    has persisted, the model is idle past its TTL, and it has been warm for at
    least ``warm_min_s`` (so a burst of requests does not reload it every time).
    """

    def __init__(self, idle_ttl_s: float = 900.0, warm_min_s: float = 300.0,
                 pressure_hold_s: float = 20.0, unload_command: list | None = None):
        self.idle_ttl_s = idle_ttl_s
        self.warm_min_s = warm_min_s
        self.pressure_hold_s = pressure_hold_s
        self.unload_command = unload_command or []
        self._models: dict[str, dict] = {}
        self._pressure_since: float | None = None
        self._mu = threading.Lock()

    @classmethod
    def from_config(cls, cfg=None) -> "WarmModelRegistry":
        rc = getattr(cfg, "resources", cfg) or None

        def g(name, default):
            return getattr(rc, name, default) if rc is not None else default
        cmd = g("model_unload_command", None)
        if isinstance(cmd, str):
            cmd = cmd.split() if cmd.strip() else []
        return cls(idle_ttl_s=float(g("model_idle_ttl_s", 900.0)),
                   warm_min_s=float(g("model_warm_min_s", 300.0)),
                   pressure_hold_s=float(g("pressure_hold_s", 20.0)),
                   unload_command=list(cmd or []))

    def touch(self, name: str) -> None:
        now = time.time()
        with self._mu:
            m = self._models.setdefault(name, {"loaded_at": now, "loaded": True,
                                               "loads": 0, "unloads": 0})
            if not m.get("loaded"):
                m["loaded"] = True
                m["loaded_at"] = now
                m["loads"] += 1
            m["last_used"] = now

    def mark_loaded(self, name: str) -> None:
        now = time.time()
        with self._mu:
            m = self._models.setdefault(name, {})
            m.update({"loaded": True, "loaded_at": now, "last_used": now,
                      "loads": m.get("loads", 0) + 1,
                      "unloads": m.get("unloads", 0)})

    def is_warm(self, name: str) -> bool:
        with self._mu:
            return bool(self._models.get(name, {}).get("loaded"))

    def idle_for(self, name: str) -> float:
        with self._mu:
            m = self._models.get(name) or {}
            if not m.get("loaded"):
                return 0.0
            return time.time() - (m.get("last_used") or m.get("loaded_at")
                                  or time.time())

    def maybe_unload(self, monitor: ResourceMonitor,
                     policy: ResourcePolicy) -> list[dict]:
        """Unload idle warm models when memory pressure warrants it."""
        if monitor is None or policy is None:
            return []
        snap = monitor.snapshot()
        ram = snap.mem_available_mb
        pressure = bool(ram and ram >= 0 and ram < policy.ram_min_free_mb)
        now = time.time()
        actions: list[dict] = []
        with self._mu:
            if not pressure:
                self._pressure_since = None
                return []
            if self._pressure_since is None:
                self._pressure_since = now
            held_for = now - self._pressure_since
            models = dict(self._models)
        if held_for < self.pressure_hold_s:
            return [{"action": "hold", "reason": f"memory pressure for "
                     f"{held_for:.0f}s < {self.pressure_hold_s:.0f}s "
                     f"(avoid unload thrash)"}]
        for name, m in models.items():
            if not m.get("loaded"):
                continue
            idle = now - (m.get("last_used") or m.get("loaded_at") or now)
            if idle < self.idle_ttl_s:
                actions.append({"action": "keep", "model": name,
                                "reason": f"idle {idle:.0f}s < ttl "
                                          f"{self.idle_ttl_s:.0f}s"})
                continue
            warm_for = now - (m.get("loaded_at") or now)
            if warm_for < self.warm_min_s:
                actions.append({"action": "keep", "model": name,
                                "reason": f"warm only {warm_for:.0f}s < "
                                          f"{self.warm_min_s:.0f}s (hysteresis)"})
                continue
            if not self.unload_command:
                actions.append({"action": "unsupported", "model": name,
                                "reason": "no model_unload_command configured; "
                                          "cannot unload this backend safely"})
                continue
            import shlex
            import subprocess
            cmd = [str(c).replace("{model}", name) for c in self.unload_command]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=30)
                ok = r.returncode == 0
                err = (r.stderr or r.stdout or "").strip()[:200]
            except (OSError, subprocess.TimeoutExpired) as e:
                ok, err = False, f"{type(e).__name__}: {e}"[:200]
            if ok:
                with self._mu:
                    m["loaded"] = False
                    m["unloads"] = m.get("unloads", 0) + 1
                actions.append({"action": "unloaded", "model": name,
                                "reason": f"idle {idle:.0f}s under RAM pressure"})
            else:
                actions.append({"action": "unload_failed", "model": name,
                                "reason": err or "command failed"})
        return actions

    def status(self) -> dict:
        with self._mu:
            now = time.time()
            return {name: {
                "loaded": bool(m.get("loaded")),
                "idle_s": round(now - (m.get("last_used") or now), 1)
                if m.get("loaded") else None,
                "loads": m.get("loads", 0), "unloads": m.get("unloads", 0),
            } for name, m in self._models.items()}
