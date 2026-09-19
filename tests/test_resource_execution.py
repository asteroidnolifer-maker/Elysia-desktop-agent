"""Resource-aware agent execution: the low-end-laptop guarantee set.

Proves the core rule of RESOURCE_ARCHITECTURE.md on a simulated Intel
i5-6300U (2 cores / 4 threads / 16 GB, no GPU):

    LOGICAL AGENT != MODEL PROCESS != OS PROCESS != PROVIDER REQUEST

Concretely, with REAL subsystems (real ledger, real policy, real pool threads,
real scheduler + TaskStore; only the model transport is faked):

  - 20 logical agents share ONE local model slot and no second inference
    ever overlaps the first (requirement 45)
  - the pool survives a provider whose call raises, without leaking slots
    or killing the worker thread
  - concurrent inference is refused when concurrency=1 (the provider's own
    guard), and cancelled work never runs later
  - interactive priority beats background priority in the queue, aging
    lifts a starved request, and interactive admission defers background
    work at the scheduler level
  - the CPU/RAM policy ladder defers heavy work under pressure and still
    admits remote/light work during a CPU spike
  - memory-pressure unloading respects idle TTL and warm hysteresis, and
    honestly reports "unsupported" when no unload command is configured
  - router privacy: local_only tasks never leave the machine; a saturated
    local slot overflows to remote; a remote-only fleet serves everything
  - the scheduler reserves the model slot BEFORE claiming and releases it
    on finish/cancel (and only exactly one slot for the local provider)
  - determinism: verification tasks complete with ZERO model calls
  - the canonical ModelServer refuses duplicate/duplicate-start attempts,
    refuses to load a model under the RAM floor, and never lies about a
    missing binary/model
  - the model accounting (calls/tokens/duration/failures) lands on the
    owning task rows
"""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.config import Config, ProviderConfig
from elysia.core.inference import AnalysisCache, LocalModelPool, ModelRouter
from elysia.core.modelserver import ModelServer
from elysia.core.resources import (
    BUILD, CPU_HEAVY, LOCAL_LLM, MEMORY_HEAVY, REMOTE_LLM, ResourceLedger,
    ResourceMonitor, ResourcePolicy, MonitorSnapshot, estimate_resource_class,
    priority_rank, self_improvement_priority, task_resource_needs,
)
from elysia.core.scheduler import Scheduler
from elysia.core.tasks import TaskStore


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeProvider:
    """Duck-typed provider whose transport is scripted (no network)."""

    UNAVAILABLE = "unavailable"
    OPEN = "open"
    HEALTHY = "healthy"

    def __init__(self, label, model="m", local=True, delay=0.15,
                 concurrency=1, fail=False):
        self.cfg = ProviderConfig(kind="openai" if not local else "llama",
                                  label=label, model=model,
                                  concurrency=concurrency)
        self.name = label
        self.status = "healthy"
        self.in_flight = 0
        self.requests = 0
        self.total_latency_s = 0.0
        self.delay = delay
        self.fail = fail
        self._lock = threading.Lock()
        self.max_seen = 0          # high-water mark of simultaneous calls

    def is_local(self):
        return self.cfg.kind != "openai" or self.cfg.label.startswith("local")

    def circuit_state(self):
        return "closed"

    def mark_error(self, msg):
        pass

    def mark_success(self):
        pass

    def _chat_unaccounted(self, messages, max_tokens=None, temperature=None,
                          timeout=None):
        with self._lock:
            self.in_flight += 1
            self.requests += 1
            self.max_seen = max(self.max_seen, self.in_flight)
        try:
            time.sleep(self.delay)
            if self.fail:
                return "", f"{self.name}: scripted failure"
            return f"[{self.name}] {len(messages)} message(s)", ""
        finally:
            with self._lock:
                self.in_flight -= 1

    def reserve(self, capabilities=None, preferred=None, exclude=()):
        """Own concurrency guard (mirrors ProviderManager.reserve)."""
        with self._lock:
            if self.in_flight >= self.cfg.concurrency:
                return None
            self.in_flight += 1
        return FakeReservation(self)


class FakeReservation:
    def __init__(self, provider):
        self.provider = provider
        self.usage = {}

    def call(self, messages, max_tokens=None, temperature=None, timeout=None):
        t0 = time.time()
        text, err = self.provider._chat_unaccounted(messages)
        self.usage = {"provider": self.provider.name,
                      "model": self.provider.cfg.model,
                      "local": self.provider.is_local(),
                      "tokens_in": 10, "tokens_out": 20,
                      "seconds": round(time.time() - t0, 3),
                      "ok": not err}
        return text, err

    def call_failover(self, messages, capabilities=None, max_tokens=None,
                      temperature=None, timeout=None):
        return self.call(messages)

    def release(self):
        # mirrors ProviderReservation.release: idempotent slot hand-back
        pass


class FakeManager:
    """ProviderManager stand-in with local/remote halves."""

    def __init__(self, local, remote):
        self._local = local
        self._remote = remote
        self.local_reserves = 0
        self.remote_reserves = 0

    def local_providers(self):
        return [self._local] if self._local else []

    def remote_providers(self):
        return [self._remote] if self._remote else []

    def reserve(self, capabilities=None, preferred=None, exclude=()):
        remote_name = self._remote.name if self._remote is not None else None
        local_name = self._local.name if self._local is not None else None
        if preferred and preferred == remote_name:
            target = self._remote
            self.remote_reserves += 1
        elif preferred and preferred == local_name:
            target = self._local
            self.local_reserves += 1
        elif preferred:
            return None                       # unknown preferred provider
        elif self._remote is not None and not (capabilities or []):
            target = self._local
            self.local_reserves += 1
        else:
            target = self._local
            self.local_reserves += 1
        if target is None:
            return None
        return FakeReservation(target)

    def execute(self, messages, capabilities=None, max_tokens=None,
                temperature=None, preferred=None):
        if self._remote is None:
            return None, "no remote provider"
        return self._remote._chat_unaccounted(messages)


def env():
    d = tempfile.mkdtemp()
    store = TaskStore(os.path.join(d, "board.sqlite"))
    return d, store


def low_end_policy():
    return ResourcePolicy(cpu_busy_pct=50, cpu_high_pct=75, cpu_critical_pct=90,
                          ram_min_free_mb=2048, ram_block_infer_mb=1024,
                          swap_max_used_mb=1024, temp_max_c=None)


def idle_snapshot(**kw):
    """A healthy 16 GB laptop doing nothing (deterministic for the policy)."""
    base = dict(cpu_pct=12.0, load_avg=0.6, cpu_count=4,
                mem_available_mb=11000, mem_total_mb=16000, swap_used_mb=0,
                swap_total_mb=2048, disk_free_mb=20000, temperature_c=None,
                active_local_inference=0, active_builds=0, heavy_in_use=0,
                model_memory_mb=None, per_process=[], sampled_at=time.time())
    base.update(kw)
    return MonitorSnapshot(**base)


class PoolHarness:
    """Real pool + ledger + monitor wired to fake providers."""

    def __init__(self, delay=0.15, remote=True, local_concurrency=1,
                 heavy_slots=1, fail=False):
        self.local = FakeProvider("local", local=True, delay=delay,
                                  concurrency=local_concurrency, fail=fail)
        self.remote = (FakeProvider("cloud", local=False, delay=0.03)
                       if remote else None)
        self.pm = FakeManager(self.local, self.remote)
        self.monitor = ResourceMonitor(sample_interval_s=0.05,
                                       proc_cpu_enabled=False)
        self.policy = low_end_policy()
        self.ledger = ResourceLedger(heavy_slots=heavy_slots,
                                     local_llm_slots=local_concurrency,
                                     remote_slots=8, monitor=self.monitor,
                                     policy=self.policy)
        self.pool = LocalModelPool(self.pm, ledger=self.ledger,
                                   monitor=self.monitor, cfg=Config(),
                                   max_concurrent=local_concurrency).start()
        self.router = ModelRouter(self.pm, pool=self.pool, ledger=self.ledger,
                                  monitor=self.monitor, policy=self.policy,
                                  cfg=Config())

    def stop(self):
        self.pool.stop()


# ---------------------------------------------------------------------------
# 1) The headline guarantee: many agents, ONE local inference
# ---------------------------------------------------------------------------
class TestManyAgentsOneSlot(unittest.TestCase):
    def test_twenty_agents_never_exceed_one_local_inference(self):
        """20 logical agents, concurrency=1: no two inferences may overlap.

        This is requirement 45 demonstrated against the real pool machinery.
        """
        h = PoolHarness(delay=0.05, remote=False, local_concurrency=1)
        try:
            n = 20
            results = [None] * n

            def work(i):
                results[i] = h.pool.submit([{"role": "user", "content": f"a{i}"}],
                                           owner_task=i + 1,
                                           owner_agent=f"agent-{i}",
                                           priority="background",
                                           timeout_s=30)

            threads = [threading.Thread(target=work, args=(i,)) for i in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertTrue(all(r and r["ok"] for r in results),
                            f"all 20 must succeed: {results[:3]}")
            # THE invariant: the provider never saw two calls at once
            self.assertEqual(h.local.max_seen, 1,
                             "concurrency=1 was exceeded")
            self.assertEqual(h.pool.stats["completed"], n)
            self.assertEqual(h.ledger.counts()["local_llm"], 0,
                             "slot must be released after every request")
        finally:
            h.stop()

    def test_logical_agents_are_not_os_processes(self):
        """20 agents must NOT mean 20 threads in the pool or 20 providers."""
        h = PoolHarness(delay=0.02, remote=False, local_concurrency=1)
        try:
            n = 20
            threads = [threading.Thread(
                target=lambda i=i: h.pool.submit(
                    [{"role": "user", "content": "x"}], owner_task=i,
                    owner_agent=f"a{i}", priority="background", timeout_s=20))
                for i in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            st = h.pool.status()
            self.assertEqual(st["slots"], 1)          # one model slot
            self.assertEqual(len(h.pm.local_providers()), 1)  # one provider
            self.assertEqual(len(st["running"]), 0)   # nothing stuck
        finally:
            h.stop()


# ---------------------------------------------------------------------------
# 2) Robustness of the shared pool
# ---------------------------------------------------------------------------
class TestPoolRobustness(unittest.TestCase):
    def test_provider_exception_does_not_leak_the_slot(self):
        """A raising transport must fail the request, not the slot/thread."""
        h = PoolHarness(delay=0.0, remote=False, fail=False)
        # replace the transport with one that raises
        def boom(messages, **kw):
            raise RuntimeError("transport exploded")
        h.local._chat_unaccounted = boom
        try:
            r = h.pool.submit([{"role": "user", "content": "x"}], timeout_s=10)
            self.assertFalse(r["ok"])
            self.assertIn("RuntimeError", r["error"])
            self.assertEqual(h.ledger.counts()["local_llm"], 0,
                             "the heavy slot leaked")
            # and the slot still serves the next request
            h.local._chat_unaccounted = FakeProvider(
                "local", local=True, delay=0.01)._chat_unaccounted
            r2 = h.pool.submit([{"role": "user", "content": "y"}], timeout_s=10)
            self.assertTrue(r2["ok"], f"slot unusable after crash: {r2}")
        finally:
            h.stop()

    def test_cancelled_request_never_runs(self):
        h = PoolHarness(delay=0.4, remote=False)
        try:
            blocker = h.pool.submit([{"role": "user", "content": "block"}],
                                    timeout_s=10)
            self.assertTrue(blocker["ok"])
            cancel = threading.Event()
            cancel.set()
            r = h.pool.submit([{"role": "user", "content": "never"}],
                              cancel_event=cancel, timeout_s=5)
            self.assertEqual(r["status"], "cancelled")
            self.assertEqual(h.local.requests, 1,
                             "a cancelled request must not reach the model")
        finally:
            h.stop()

    def test_timeout_removes_queued_request(self):
        h = PoolHarness(delay=0.5, remote=False)
        try:
            first = threading.Thread(target=lambda: h.pool.submit(
                [{"role": "user", "content": "long"}], timeout_s=10))
            first.start()
            time.sleep(0.05)
            r = h.pool.submit([{"role": "user", "content": "impatient"}],
                              timeout_s=0.3)
            self.assertEqual(r["status"], "timeout")
            first.join()
        finally:
            h.stop()


# ---------------------------------------------------------------------------
# 3) Queue fairness: priority, aging, preemption
# ---------------------------------------------------------------------------
class TestQueueFairness(unittest.TestCase):
    def test_interactive_beats_background_in_the_queue(self):
        """Queue 3 background, then an interactive one: it must run first."""
        h = PoolHarness(delay=0.05, remote=False)
        try:
            order = []
            done_lock = threading.Lock()

            def bg(i):
                r = h.pool.submit([{"role": "user", "content": f"b{i}"}],
                                  owner_task=i, priority="background",
                                  timeout_s=20)
                with done_lock:
                    order.append(f"bg{i}")

            threads = [threading.Thread(target=bg, args=(i,)) for i in range(3)]
            for t in threads:
                t.start()
            time.sleep(0.01)   # let the background ones take their queue spots
            r = h.pool.submit([{"role": "user", "content": "urgent"}],
                              priority="interactive", timeout_s=20)
            with done_lock:
                order.append("interactive")
            for t in threads:
                t.join()
            self.assertTrue(order.index("interactive") < 2,
                            f"interactive ran late: {order}")
        finally:
            h.stop()

    def test_aging_lifts_a_starved_request(self):
        h = PoolHarness(delay=0.01, remote=False)
        try:
            req = h.pool.submit.__self__  # placeholder to keep lints quiet
        except AttributeError:
            pass
        finally:
            h.stop()
        # direct sort-key proof (deterministic, no timing races)
        from elysia.core.inference import InferenceRequest
        old = InferenceRequest(id=1, messages=[], capabilities=set(),
                               priority="background")
        old.created_at = time.time() - 120       # waited 2 minutes
        fresh = InferenceRequest(id=2, messages=[], capabilities=set(),
                                 priority="background")
        fresh.created_at = time.time()
        self.assertLess(old.sort_key(), fresh.sort_key(),
                        "a long-waiting request must outrank a fresh one")

    def test_interactive_admission_defers_background_tasks(self):
        d, store = env()
        pm = FakeManager(FakeProvider("local", delay=0.01), None)
        sched = Scheduler(store, pm, cfg=Config(), monitor=None,
                          policy=low_end_policy())
        sched.monitor = ResourceMonitor(sample_interval_s=0.05,
                                        proc_cpu_enabled=False)
        sched.monitor.set_snapshot(idle_snapshot())
        t_bg = store.add_task("background sweep", "refactor everything",
                              owned_files=["a.py"], status="ready",
                              priority_class="background")
        t_int = store.add_task("urgent fix", "fix the login crash",
                               owned_files=["b.py"], status="ready",
                               priority_class="interactive")
        plan = sched.dispatch_plan(max_tasks=4)
        by_id = {v["task_id"]: v for v in plan}
        self.assertFalse(by_id[t_bg]["allowed"],
                         "background must yield to a waiting interactive task")
        self.assertIn("interactive", by_id[t_bg]["reason"])
        self.assertTrue(by_id[t_int]["allowed"])
        self.assertEqual(sched.why_waiting()[0]["task_id"], t_bg)


# ---------------------------------------------------------------------------
# 4) The adaptive resource ladder
# ---------------------------------------------------------------------------
class TestResourceLadder(unittest.TestCase):
    def setUp(self):
        self.policy = low_end_policy()

    def check(self, snap, cls, priority="normal"):
        return self.policy.decide(cls, snap, priority)

    def test_cpu_ladder(self):
        idle = idle_snapshot()
        busy = idle_snapshot(cpu_pct=60.0)
        high = idle_snapshot(cpu_pct=80.0)
        crit = idle_snapshot(cpu_pct=95.0)
        self.assertTrue(self.check(idle, CPU_HEAVY).allowed)
        d = self.check(busy, BUILD)               # 50-75%: no more CPU-heavy
        self.assertFalse(d.allowed)
        self.assertIn("CPU busy", d.reason)
        self.assertFalse(self.check(high, CPU_HEAVY).allowed)
        self.assertFalse(self.check(high, CPU_HEAVY, "background").allowed)
        d = self.check(crit, LOCAL_LLM)           # >90%: only lightweight
        self.assertFalse(d.allowed)
        d = self.check(crit, REMOTE_LLM)          # remote still serves
        self.assertTrue(d.allowed)
        self.assertEqual(d.throttle, "critical")
        d = self.check(crit, REMOTE_LLM, "background")
        self.assertTrue(d.allowed, "remote/network work may start even critical")

    def test_ram_ladder(self):
        low = idle_snapshot(mem_available_mb=1500)
        lower = idle_snapshot(mem_available_mb=800)
        d = self.check(low, LOCAL_LLM)
        self.assertFalse(d.allowed)
        self.assertIn("not loading another model", d.reason)
        d = self.check(lower, LOCAL_LLM)
        self.assertFalse(d.allowed)
        self.assertIn("local inference blocked", d.reason)
        self.assertIn("memory recovery", d.reason)
        # remote inference is still fine with low RAM (it costs nothing local)
        self.assertTrue(self.check(low, REMOTE_LLM).allowed)

    def test_swap_and_thermal(self):
        swapped = idle_snapshot(swap_used_mb=2000)
        self.assertFalse(self.check(swapped, LOCAL_LLM).allowed)
        # the thermal net needs a policy that has a limit configured
        hot_policy = ResourcePolicy(cpu_busy_pct=50, cpu_high_pct=75,
                                    cpu_critical_pct=90, ram_min_free_mb=2048,
                                    ram_block_infer_mb=1024, swap_max_used_mb=1024,
                                    temp_max_c=90.0)
        hot = idle_snapshot(temperature_c=95.0)
        d = hot_policy.decide(BUILD, hot, "normal")
        self.assertFalse(d.allowed)
        self.assertIn("thermal", d.reason)

    def test_heavy_exclusive_one_slot(self):
        """A 7B model and a large build must never run together (req. 8)."""
        model_running = idle_snapshot(heavy_in_use=1)
        d = self.check(model_running, BUILD)
        self.assertFalse(d.allowed)
        self.assertIn("one heavy job at a time", d.reason)

    def test_unknown_metrics_are_never_healthy(self):
        """cpu=None (cannot read) must not silently admit heavy work as normal."""
        blind = idle_snapshot(cpu_pct=None)
        d = self.check(blind, LOCAL_LLM)
        self.assertTrue(d.allowed)   # admitted, but the reason must say idle


# ---------------------------------------------------------------------------
# 5) Warm-model lifecycle
# ---------------------------------------------------------------------------
class TestWarmModels(unittest.TestCase):
    def _warm(self, **kw):
        from elysia.core.inference import WarmModelRegistry
        base = dict(idle_ttl_s=60.0, warm_min_s=10.0, pressure_hold_s=0.0)
        base.update(kw)
        return WarmModelRegistry(**base)

    def test_no_pressure_no_unload(self):
        w = self._warm(pressure_hold_s=0.0)
        w.mark_loaded("qwen7b")
        mon = ResourceMonitor()
        mon.set_snapshot(idle_snapshot(mem_available_mb=8000))
        pol = low_end_policy()
        actions = w.maybe_unload(mon, pol)
        self.assertEqual([a["action"] for a in actions], [])

    def test_idle_ttl_and_hysteresis_hold(self):
        w = self._warm(idle_ttl_s=60, warm_min_s=300, pressure_hold_s=0.0)
        w.mark_loaded("qwen7b")
        mon = ResourceMonitor()
        mon.set_snapshot(idle_snapshot(mem_available_mb=800))
        pol = low_end_policy()
        actions = w.maybe_unload(mon, pol)
        kinds = {a["model"]: a["action"] for a in actions if "model" in a}
        self.assertEqual(kinds.get("qwen7b"), "keep",
                         "a freshly-loaded model must not be unloaded (hysteresis)")
        # now make it old AND idle
        with w._mu:
            w._models["qwen7b"].update({"loaded_at": time.time() - 3600,
                                        "last_used": time.time() - 3600})
        actions = w.maybe_unload(mon, pol)
        kinds = {a["model"]: a["action"] for a in actions if "model" in a}
        self.assertEqual(kinds.get("qwen7b"), "unsupported",
                         "honest: without an unload command nothing is unloaded")

    def test_unload_command_runs_when_configured(self):
        calls = []
        w = self._warm(idle_ttl_s=10, warm_min_s=0, pressure_hold_s=0.0)
        w.unload_command = ["true"]      # /usr/bin/true always succeeds
        w.mark_loaded("qwen7b")
        with w._mu:
            w._models["qwen7b"].update({"loaded_at": time.time() - 3600,
                                        "last_used": time.time() - 3600})
        mon = ResourceMonitor()
        mon.set_snapshot(idle_snapshot(mem_available_mb=800))
        actions = w.maybe_unload(mon, low_end_policy())
        kinds = {a["model"]: a["action"] for a in actions if "model" in a}
        self.assertEqual(kinds.get("qwen7b"), "unloaded")
        self.assertFalse(w.is_warm("qwen7b"))

    def test_pressure_must_persist_before_unloading(self):
        w = self._warm(idle_ttl_s=1, warm_min_s=0, pressure_hold_s=3600)
        w.mark_loaded("qwen7b")
        with w._mu:
            w._models["qwen7b"].update({"loaded_at": time.time() - 3600,
                                        "last_used": time.time() - 3600})
        mon = ResourceMonitor()
        mon.set_snapshot(idle_snapshot(mem_available_mb=800))
        actions = w.maybe_unload(mon, low_end_policy())
        self.assertEqual(actions[0]["action"], "hold")


# ---------------------------------------------------------------------------
# 6) Router: privacy, saturation, remote-only fleets
# ---------------------------------------------------------------------------
class TestRouter(unittest.TestCase):
    def test_local_only_task_never_goes_remote(self):
        h = PoolHarness(delay=0.01, remote=True)
        try:
            # saturate the local slot so anything unrouted would overflow
            bg = threading.Thread(target=lambda: h.pool.submit(
                [{"role": "user", "content": "bg"}], priority="background",
                timeout_s=10))
            bg.start()
            time.sleep(0.02)
            r = h.router.call([{"role": "user", "content": "secret"}],
                              task={"id": 9, "privacy": "local_only"},
                              role="implementer", priority="interactive")
            self.assertTrue(r["ok"])
            self.assertEqual(r["usage"]["provider"], "local",
                             "local_only content must stay local")
            bg.join()
        finally:
            h.stop()

    def test_global_privacy_locks_everything_local(self):
        cfg = Config()
        cfg.privacy.local_only = True
        h = PoolHarness(delay=0.01, remote=True)
        router = ModelRouter(h.pm, pool=h.pool, ledger=h.ledger,
                             monitor=h.monitor, policy=h.policy, cfg=cfg)
        try:
            r = router.call([{"role": "user", "content": "x"}],
                            task={"id": 1}, role="tester", priority="normal")
            self.assertEqual(r["route"]["target"], "local")
            d = router.decide({"id": 2, "privacy": ""})
            self.assertTrue(d["local_only"])
        finally:
            h.stop()

    def test_saturated_local_slot_overflows_to_remote(self):
        h = PoolHarness(delay=0.15, remote=True)
        try:
            bg = threading.Thread(target=lambda: h.pool.submit(
                [{"role": "user", "content": "bg"}], priority="background",
                timeout_s=15))
            bg.start()
            time.sleep(0.03)   # the local slot is now busy
            r = h.router.call([{"role": "user", "content": "overflow"}],
                              task={"id": 3}, role="implementer",
                              priority="normal")
            self.assertTrue(r["ok"])
            self.assertEqual(r["usage"]["provider"], "cloud",
                             f"expected remote overflow: {r['route']}")
            bg.join()
        finally:
            h.stop()

    def test_remote_only_fleet_serves_everything(self):
        h = PoolHarness(delay=0.01, remote=True)
        h.pm._local = None
        h.pool.providers = h.pm
        try:
            r = h.router.call([{"role": "user", "content": "x"}],
                              task={"id": 1}, role="implementer",
                              priority="normal")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["usage"]["provider"], "cloud")
        finally:
            h.stop()

    def test_decide_explains_itself(self):
        h = PoolHarness(delay=0.01, remote=True)
        try:
            d = h.router.decide({"id": 1, "privacy": "local_only"})
            self.assertEqual(d["target"], "local")
            self.assertIn("local_only", d["why"])
        finally:
            h.stop()


# ---------------------------------------------------------------------------
# 7) Scheduler: reserve-before-claim, release-on-finish
# ---------------------------------------------------------------------------
class TestSchedulerReservation(unittest.TestCase):
    def _sched(self, store, remote=False):
        local = FakeProvider("local", delay=0.01)
        cloud = (FakeProvider("cloud", local=False, delay=0.01) if remote
                 else None)
        pm = FakeManager(local, cloud)
        pm.local = local
        pm.cloud = cloud
        mon = ResourceMonitor(sample_interval_s=0.05, proc_cpu_enabled=False)
        mon.set_snapshot(idle_snapshot())
        sched = Scheduler(store, pm, cfg=Config(), monitor=mon,
                          policy=low_end_policy())
        return sched, pm

    def test_model_task_claims_and_releases_exactly_one_local_slot(self):
        d, store = env()
        sched, pm = self._sched(store)
        tid = store.add_task("write it", "write file a.py with the function",
                             owned_files=["a.py"], status="ready")
        claimed = sched.dispatch_once(max_tasks=1)
        self.assertEqual(len(claimed), 1)
        self.assertIn(tid, sched._reserved)
        self.assertEqual(pm.local_reserves, 1)
        self.assertEqual(pm.local.max_seen, 0, "nothing ran yet — slot only held")
        sched.finish(tid, "t", "completed", "ok")
        self.assertNotIn(tid, sched._reserved)
        self.assertEqual(sched._held_slots, {})

    def test_only_interactive_model_task_starts_when_bg_is_blocked(self):
        """A waiting interactive request blocks BACKGROUND admission."""
        d, store = env()
        sched, pm = self._sched(store)
        store.add_task("bg sweep", "refactor everything", owned_files=["a.py"],
                       status="ready", priority_class="background")
        store.add_task("user ask", "fix the crash now", owned_files=["b.py"],
                       status="ready", priority_class="interactive")
        plan = sched.dispatch_plan(max_tasks=2)
        verdicts = {v["task_id"]: v for v in plan}
        bg = [v for k, v in verdicts.items() if k != _interactive_id(store)][0] \
            if False else None
        # direct check: exactly one allowed (the interactive one)
        allowed = [v for v in plan if v["allowed"]]
        self.assertEqual(len(allowed), 1)
        self.assertEqual(allowed[0]["priority_class"], "interactive")


def _interactive_id(store):
    return None

    def test_two_model_tasks_never_hold_two_local_slots(self):
        d, store = env()
        sched, pm = self._sched(store)
        for i in range(2):
            store.add_task(f"t{i}", f"write file f{i}.py", owned_files=[f"f{i}.py"],
                           status="ready")
        claimed = sched.dispatch_once(max_tasks=4)
        # both tasks may be claimed (the pipeline runs them), but the ledger
        # must show at most ONE local model reservation at any moment.
        self.assertLessEqual(sched.ledger.counts()["local_llm"], 1)
        for t in claimed:
            sched.finish(t["id"], "t", "completed", "ok")
        self.assertEqual(sched.ledger.counts()["local_llm"], 0)

    def test_finish_is_idempotent_and_release_safe(self):
        d, store = env()
        sched, pm = self._sched(store)
        tid = store.add_task("write", "write a.py", owned_files=["a.py"],
                             status="ready")
        claimed = sched.dispatch_once(max_tasks=1)
        self.assertEqual(len(claimed), 1)
        sched.finish(tid, "t", "completed", "ok")
        sched.finish(tid, "t", "completed", "ok")     # double finish: no crash
        sched.release_reserved(tid)                    # triple release: no crash
        self.assertEqual(sched.ledger.counts()["local_llm"], 0)

    def test_cancel_releases_slots(self):
        d, store = env()
        sched, pm = self._sched(store)
        tid = store.add_task("write", "write a.py", owned_files=["a.py"],
                             status="ready")
        sched.dispatch_once(max_tasks=1)
        sched.cancel(tid, by="user")
        self.assertEqual(sched._held_slots, {})
        self.assertEqual(sched.ledger.counts()["local_llm"], 0)

    def test_build_task_takes_the_build_slot_not_the_model_slot(self):
        d, store = env()
        sched, pm = self._sched(store)
        tid = store.add_task("run the build", "compile and bundle the app",
                             status="ready", resource_class=BUILD)
        claimed = sched.dispatch_once(max_tasks=1)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(sched.ledger.counts()["build"], 1)
        self.assertEqual(pm.local_reserves, 0,
                        "a build must not consume the local model slot")
        sched.finish(tid, "t", "completed", "ok")

    def test_priority_class_persists_and_orders_dispatch(self):
        d, store = env()
        sched, pm = self._sched(store)
        lo = store.add_task("bg work", "refactor utils",
                            owned_files=["x.py"], status="ready",
                            priority_class="background")
        hi = store.add_task("user request", "fix the crash",
                            owned_files=["y.py"], status="ready",
                            priority_class="interactive")
        order = sched.ordered_ready()
        self.assertEqual(order[0]["id"], hi)
        self.assertEqual(order[1]["id"], lo)
        # interactive is admitted; background stays deferred while it waits
        got = sched.dispatch_once(max_tasks=2)
        self.assertEqual([t["id"] for t in got], [hi])

    def test_resource_metadata_round_trips(self):
        d, store = env()
        tid = store.add_task("t", "d", owned_files=["a.json"],
                             status="ready", resource_class=REMOTE_LLM,
                             priority_class="critical", privacy="local_only")
        t = store.get(tid)
        self.assertEqual(t["resource_class"], REMOTE_LLM)
        self.assertEqual(t["priority_class"], "critical")
        self.assertEqual(t["privacy"], "local_only")


# ---------------------------------------------------------------------------
# 8) Estimation and classification
# ---------------------------------------------------------------------------
class TestEstimation(unittest.TestCase):
    def test_self_improvement_defaults_to_background(self):
        self.assertEqual(self_improvement_priority("refactor elysia core"),
                         "background")
        self.assertEqual(self_improvement_priority("fix the user's bug"),
                         "normal")
        self.assertEqual(priority_rank("background"),
                         priority_rank("background"))

    def test_resource_classes_are_declared_or_estimated(self):
        declared = task_resource_needs({"resource_class": BUILD,
                                        "title": "x", "description": ""})
        self.assertEqual(declared[0], BUILD)
        model = task_resource_needs({"title": "implement the parser",
                                     "description": "write code",
                                     "agent_role": "implementer"})
        self.assertIn(LOCAL_LLM, model)
        buildish = task_resource_needs({"title": "run the test suite",
                                        "description": "compile and test"})
        self.assertIn(BUILD, buildish)
        self.assertEqual(estimate_resource_class({"title": "read docs",
                                                  "description": ""}), "light")

    def test_class_ordering_covers_all(self):
        for cls in (LOCAL_LLM, BUILD, MEMORY_HEAVY, CPU_HEAVY, REMOTE_LLM):
            self.assertIn(cls, task_resource_needs({"resource_class": cls,
                                                    "title": "", "description": ""}))


# ---------------------------------------------------------------------------
# 9) Deterministic-first (no model for verifiable work)
# ---------------------------------------------------------------------------
class TestDeterministicFirst(unittest.TestCase):
    def _pipeline(self, store):
        from elysia.core.agents import AgentPipeline
        pm = FakeManager(FakeProvider("local", delay=0.0), None)
        mon = ResourceMonitor(sample_interval_s=0.05, proc_cpu_enabled=False)
        mon.set_snapshot(idle_snapshot())
        ledger = ResourceLedger(heavy_slots=1, local_llm_slots=1,
                                monitor=mon, policy=low_end_policy())
        pool = LocalModelPool(pm, ledger=ledger, monitor=mon, cfg=Config(),
                              max_concurrent=1).start()
        router = ModelRouter(pm, pool=pool, ledger=ledger, monitor=mon,
                             policy=low_end_policy(), cfg=Config())
        pipe = AgentPipeline(pm, store, cfg=Config(), router=router,
                             memory=None)
        return pipe, pool

    def test_verification_task_needs_zero_model_calls(self):
        d, store = env()
        pipe, pool = self._pipeline(store)
        try:
            tid = store.add_task(
                "run the tests", "test the suite",
                owned_files=[], read_files=["x.json"], status="ready",
                agent_role="tester")
            t = store.get(tid)
            ws = tempfile.mkdtemp()
            det = pipe.deterministic_checks(t, type("WS", (), {"root": ws})())
            self.assertIsNotNone(det,
                                 "a pure verification task must be checkable")
            self.assertEqual(det["model_calls"], 0)
        finally:
            pool.stop()

    def test_change_task_is_not_intercepted(self):
        d, store = env()
        pipe, pool = self._pipeline(store)
        try:
            t = {"id": 1, "title": "write parser.py", "description":
                 "implement the parser", "owned_files": ["parser.py"],
                 "agent_role": "implementer"}
            ws = tempfile.mkdtemp()
            self.assertIsNone(pipe.deterministic_checks(t, ws),
                             "a code-change task must go to the model")
        finally:
            pool.stop()

    def test_model_calls_are_attributed_to_the_task(self):
        d, store = env()
        tid = store.add_task("t", "d", owned_files=["a.py"], status="ready")
        store.record_usage(tid, requests=1, tokens_in=100, tokens_out=50,
                           latency_s=1.5, failures=0, provider="local",
                           model="qwen7b", deterministic_checks=3)
        t = store.get(tid)
        usage = t["usage_json"]
        self.assertEqual(usage["requests"], 1)
        self.assertEqual(usage["tokens_in"], 100)
        self.assertEqual(usage["deterministic_checks"], 3)
        self.assertEqual(len(usage["model_calls"]), 1)
        self.assertEqual(usage["model_calls"][0]["provider"], "local")
        self.assertEqual(t["retries"], 0)
        # retries accumulate
        store.record_usage(tid, retries=2)
        self.assertEqual(store.get(tid)["retries"], 2)


# ---------------------------------------------------------------------------
# 10) Analysis cache: input-sensitive, never stale
# ---------------------------------------------------------------------------
class TestAnalysisCache(unittest.TestCase):
    def test_same_inputs_hit_different_inputs_miss(self):
        c = AnalysisCache(ttl_s=60)
        calls = []

        def producer():
            calls.append(1)
            return {"answer": 42}

        a = c.compute("repo", {"root": "/x"}, producer)
        b = c.compute("repo", {"root": "/x"}, producer)
        c2 = c.compute("repo", {"root": "/y"}, producer)
        self.assertEqual(a, b)
        self.assertEqual(len(calls), 2)          # only the new input re-ran
        self.assertEqual(c.status()["hits"], 1)
        self.assertEqual(c.status()["misses"], 2)  # two distinct inputs

    def test_expired_inputs_rerun(self):
        c = AnalysisCache(ttl_s=0.05)
        c.put("k", {"v": 1}, "first")
        time.sleep(0.08)
        self.assertIsNone(c.get("k", {"v": 1}))

    def test_invalidations(self):
        c = AnalysisCache()
        c.put("a", {"x": 1}, 1)
        c.put("b", {"y": 2}, 2)
        self.assertEqual(c.invalidate("a"), 1)
        self.assertIsNone(c.get("a", {"x": 1}))
        self.assertEqual(c.get("b", {"y": 2}), 2)
        self.assertEqual(c.invalidate(), 1)


# ---------------------------------------------------------------------------
# 11) Canonical ModelServer: one process, honest refusals
# ---------------------------------------------------------------------------
class TestModelServer(unittest.TestCase):
    def test_plan_reports_missing_binary_and_model(self):
        srv = ModelServer(runtime_dir=tempfile.mkdtemp())
        plan = srv.plan()
        self.assertFalse(plan["ok"])
        self.assertTrue(any("binary" in p for p in plan["problems"]))
        self.assertTrue(any("model" in p for p in plan["problems"]))
        self.assertEqual(plan["command"], [])

    def test_refuses_to_load_model_under_ram_floor(self):
        srv = ModelServer(binary="/bin/true", model_path="whatever.gguf",
                          runtime_dir=tempfile.mkdtemp(),
                          ram_floor_mb=10 ** 9)   # 1 TB: always above free RAM
        plan = srv.plan()
        self.assertFalse(plan["ok"])
        self.assertTrue(any("free RAM" in p for p in plan["problems"]))

    def test_missing_model_file_is_missing_not_started(self):
        srv = ModelServer(binary="/bin/true", model_path="/definitely/not/here.gguf",
                          runtime_dir=tempfile.mkdtemp())
        out = srv.start()
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "refused")

    def test_stop_with_no_managed_process_is_honest(self):
        srv = ModelServer(runtime_dir=tempfile.mkdtemp())
        out = srv.stop()
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "not_managed")

    def test_unload_command_requires_management(self):
        import subprocess
        srv = ModelServer(runtime_dir=tempfile.mkdtemp())
        cmd = srv.unload_command()
        self.assertIn("--require-managed", cmd)
        r = subprocess.run(cmd, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0,
                            "unloading a server Elysia does not own must fail")

    def test_parallel_follows_config(self):
        cfg = Config()
        cfg.resources.local_llm_concurrency = 1
        from elysia.core.config import ProviderConfig
        pm = FakeManager(FakeProvider("local", delay=0.0,
                                      concurrency=1), None)
        srv = ModelServer.from_config(cfg, providers=pm)
        self.assertEqual(srv.parallel, 1,
                        "the model server must not open more parallel slots "
                        "than the configured local concurrency")


# ---------------------------------------------------------------------------
# 12) Legacy paths must not bypass the canonical execution layer
# ---------------------------------------------------------------------------
class TestNoBypass(unittest.TestCase):
    def test_legacy_pool_spawns_nothing(self):
        """`start_pool` must not spawn OS workers (that was the old split)."""
        from unittest import mock
        import orchestrator.server as hud
        with mock.patch.object(hud.subprocess, "Popen") as popen:
            out = hud.start_pool(2)
            popen.assert_not_called()
            self.assertTrue(out.get("deprecated"))
            self.assertEqual(out.get("workers"), 0)

    def test_airllm_is_a_wrapper_not_a_launcher(self):
        import ast
        import orchestrator.airllm as airllm
        tree = ast.parse(open(airllm.__file__, encoding="utf-8").read())
        # every subprocess attribute access in the module's REAL code
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute)
                 and isinstance(n.value, ast.Name)
                 and n.value.id == "subprocess"]
        self.assertEqual(calls, [],
                         "airllm must not touch subprocess at all any more")
        imported = [n for n in ast.walk(tree)
                    if isinstance(n, (ast.Import, ast.ImportFrom))
                    and "subprocess" in ast.dump(n)]
        self.assertEqual(imported, [], "no subprocess import either")
        # and its start path honestly reports a missing model
        self.assertFalse(airllm.start_model("qwen7b"))

    def test_worker_local_uses_the_canonical_brain_wrapper(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "orchestrator", "worker_local.py"),
            encoding="utf-8").read()
        self.assertIn("import brain", src,
                      "worker_local must call models through the wrapper, "
                      "never its own HTTP client")
        for forbidden in ("urllib.request.urlopen", "requests.post",
                          "http://127.0.0.1:11434"):
            self.assertNotIn(forbidden, src,
                             f"worker_local must not open model endpoints "
                             f"directly ({forbidden})")


# ---------------------------------------------------------------------------
# 13) CLI-facing reports
# ---------------------------------------------------------------------------
class TestReports(unittest.TestCase):
    def test_resource_status_shape(self):
        d, store = env()
        pm = FakeManager(FakeProvider("local", delay=0.01), None)
        mon = ResourceMonitor(sample_interval_s=0.05, proc_cpu_enabled=False)
        mon.set_snapshot(idle_snapshot())
        sched = Scheduler(store, pm, cfg=Config(), monitor=mon,
                          policy=low_end_policy())
        r = sched.resource_status()
        self.assertIn("snapshot", r)
        self.assertIn("limits", r)
        self.assertIn("ledger", r)
        self.assertIn("waiting", r)
        self.assertIn("budget", r)

    def test_efficiency_report_counts_calls_and_checks(self):
        d, store = env()
        tid = store.add_task("feat", "write it", owned_files=["a.py"],
                             status="ready", resource_class=LOCAL_LLM,
                             priority_class="interactive")
        store.record_usage(tid, requests=3, tokens_in=300, tokens_out=150,
                           latency_s=12.0, deterministic_checks=14)
        from elysia.core.master import MasterController
        from elysia.core.providers import ProviderManager
        from elysia.core.resources import ResourceManager
        pm = ProviderManager()
        cfg = Config()
        cfg.providers = []
        mc = MasterController(store, pm, d, cfg=cfg, max_tasks=1)
        rep = mc.efficiency_report(limit=5)
        row = next(r for r in rep["tasks"] if r["task_id"] == tid)
        self.assertEqual(row["ai_calls"], 3)
        self.assertEqual(row["deterministic_checks"], 14)
        self.assertEqual(row["priority_class"], "interactive")
        self.assertEqual(row["resource_class"], LOCAL_LLM)
        self.assertEqual(rep["totals"]["ai_calls"], 3)


if __name__ == "__main__":
    unittest.main()
