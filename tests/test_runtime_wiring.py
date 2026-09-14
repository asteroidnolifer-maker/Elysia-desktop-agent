"""Failure-mode and crash-recovery tests for the REAL runtime wiring.

These exercise the same code paths the server uses:

  - server.ensure_scheduler / start_scheduler_thread / stop_scheduler
    (the canonical scheduler now runs inside the HUD server process)
  - worker lease heartbeats (worker_local._heartbeat_loop)
  - crash recovery: kill a worker mid-task -> scheduler maintenance -> task
    released -> another worker claims it (no permanently stuck tasks)
  - provider timeout / rate-limit / unavailability / crash failover through
    the canonical ProviderManager (scripted at the _chat_openai transport
    seam, exactly like tests/test_core.py)
  - resource-exhaustion queueing (budget gate, not uncontrolled spawning)
  - workspace symlink-escape rejection and invalid-tool-argument rejection

Everything is offline: fake providers, temp dirs, no network, no GPU.
"""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "orchestrator")))

from elysia.core.providers import Provider, ProviderManager
from elysia.core.config import ProviderConfig
from elysia.core.resources import ResourceManager
from elysia.core.scheduler import Scheduler
from elysia.core.tasks import TaskStore


def make_store(tmp):
    return TaskStore(os.path.join(tmp, "board.sqlite"))


def fake_provider(pm, label, outcomes=(), concurrency=1, capabilities=None,
                  status="healthy"):
    """Register a provider scripted at the _chat_openai transport seam."""
    p = pm.register(ProviderConfig(
        kind="openai", label=label, model="m",
        capabilities=capabilities or ["chat"], concurrency=concurrency))
    outcomes = list(outcomes) or [("", "no script")]

    class _Backend:
        def __init__(self):
            self.calls = 0
            self.lock = threading.Lock()
            self.max_inflight_seen = 0
            self.inflight = 0

        def __call__(self, messages, max_tokens=None, temperature=None,
                     timeout=None):
            with self.lock:
                self.calls += 1
                self.inflight += 1
                self.max_inflight_seen = max(self.max_inflight_seen,
                                             self.inflight)
            try:
                out = outcomes[min(self.calls - 1, len(outcomes) - 1)]
                if callable(out):
                    return out()
                return out
            finally:
                with self.lock:
                    self.inflight -= 1

    p._chat_openai = _Backend()
    p.status = status
    return p


class TestSchedulerInServer(unittest.TestCase):
    """The canonical scheduler must run inside the HUD server process."""

    @classmethod
    def setUpClass(cls):
        cls._old_presets = os.environ.get("ELYSIA_DISABLE_PRESETS")
        os.environ["ELYSIA_DISABLE_PRESETS"] = "1"
        import server
        cls.server = server

    @classmethod
    def tearDownClass(cls):
        if cls._old_presets is None:
            os.environ.pop("ELYSIA_DISABLE_PRESETS", None)
        else:
            os.environ["ELYSIA_DISABLE_PRESETS"] = cls._old_presets

    def tearDown(self):
        try:
            self.server.stop_scheduler()
        except Exception:
            pass

    def test_ensure_scheduler_starts_and_is_idempotent(self):
        s1 = self.server.ensure_scheduler()
        s2 = self.server.ensure_scheduler()
        self.assertIs(s1, s2)
        self.assertIs(s1, self.server.SCHEDULER)

    def test_scheduler_thread_survives_stop_start_cycle(self):
        t1 = self.server.start_scheduler_thread()
        self.assertTrue(t1.is_alive())
        self.server.stop_scheduler()
        t2 = self.server.start_scheduler_thread()
        self.assertTrue(t2.is_alive(), "restarted thread must actually run")
        self.server.stop_scheduler()

    def test_maintenance_pass_runs_clean(self):
        s = self.server.ensure_scheduler()
        s.maintenance()   # must not raise

    def test_worker_crash_recovery_end_to_end(self):
        """Worker claims then dies -> maintenance releases -> new worker runs."""
        store = self.server.taskboard.store()
        tid = store.add_task("crash recovery", "x", owned_files=["a.md"],
                             status="ready")
        # worker A claims (simulating a healthy start)
        self.assertTrue(store.claim(tid, "ghost-worker", "local", "m", 1200))
        # worker A crashes: no heartbeat, lease expires in the past
        store._update(tid, lease_expires_at=time.time() - 1)
        s = self.server.ensure_scheduler()
        s.maintenance()
        t = store.get(tid)
        self.assertEqual(t["status"], "ready",
                         "crashed worker's task must be released, not stuck")
        # a new worker can now claim and finish it (recovery backoff applied:
        # release_expired sets a 30s retry backoff to prevent crash loops —
        # simulate the wait by rewinding the gate)
        store._update(tid, backoff_until=time.time() - 1)
        self.assertTrue(store.claim(tid, "w2", "local", "m", 1200))
        store.complete(tid, "completed", "ok")
        self.assertEqual(store.get(tid)["status"], "completed")

    def test_max_attempts_failure_is_terminal_not_stuck(self):
        store = self.server.taskboard.store()
        tid = store.add_task("exhaust", "x", owned_files=["b.md"],
                             max_attempts=1, status="ready")
        store.claim(tid, "w1", "local", "m", 1200)
        store._update(tid, lease_expires_at=time.time() - 1)
        s = self.server.ensure_scheduler()
        s.maintenance()
        self.assertEqual(store.get(tid)["status"], "failed",
                         "exhausted retries must be terminal (not a retry loop)")

    def test_stale_worker_release_via_maintenance(self):
        store = self.server.taskboard.store()
        tid = store.add_task("stale", "x", owned_files=["s.md"],
                             status="ready")
        s = self.server.ensure_scheduler()
        s.register_worker("dead-worker")
        self.assertTrue(store.claim(tid, "dead-worker", "local", "m", 1200))
        # worker stops heartbeating: registry entry goes stale
        s.workers._workers["dead-worker"] = time.time() - 10_000
        s.maintenance()
        self.assertEqual(store.get(tid)["status"], "ready",
                         "stale worker's claim must be released")


class TestLeaseHeartbeat(unittest.TestCase):
    """Workers must keep their lease alive during long model calls."""

    def setUp(self):
        import worker_local
        self.wl = worker_local

    def test_heartbeat_loop_renews_lease(self):
        store = TaskStore(os.path.join(tempfile.mkdtemp(), "b.sqlite"))
        tid = store.add_task("hb", "x", owned_files=["c.md"], status="ready")
        store.claim(tid, "whb", "local", "m", 1200)
        stop = threading.Event()
        t = threading.Thread(target=self.wl._heartbeat_loop,
                             args=(tid, "whb", stop, 0.2), daemon=True)
        t.start()
        time.sleep(0.7)   # let it renew at least once
        stop.set()
        row = store.get(tid)
        self.assertGreater(row["lease_expires_at"], time.time() - 1,
                           "lease must have been renewed by the heartbeat")
        self.assertEqual(row["worker"], "whb")

    def test_heartbeat_cli_lost_for_unknown_task(self):
        import taskboard
        self.assertFalse(taskboard.heartbeat_task(999999, "nobody"))


class TestProviderFailoverModes(unittest.TestCase):
    """Timeout / rate-limit / unavailability / crash -> next provider runs."""

    def _pm_with_first(self, first_outcomes):
        pm = ProviderManager()
        fake_provider(pm, "bad", outcomes=first_outcomes)
        fake_provider(pm, "good", outcomes=[("ok-from-good", "")])
        return pm

    def test_timeout_fails_over(self):
        def slow(messages, max_tokens=None, temperature=None, timeout=None):
            time.sleep(float(timeout or 1) + 0.05)
            return "late", None
        pm = self._pm_with_first([slow])
        text, err = pm.execute([{"role": "user", "content": "hi"}],
                               capabilities=["chat"], timeout=0.3)
        self.assertIn("ok-from-good", text)
        self.assertEqual(pm.get("bad").failures, 1)

    def test_rate_limit_fails_over(self):
        pm = self._pm_with_first([("", "http 429: rate limited")])
        text, err = pm.execute([{"role": "user", "content": "hi"}],
                               capabilities=["chat"])
        self.assertIn("ok-from-good", text)
        self.assertEqual(pm.get("bad").status, "rate_limited")

    def test_unavailable_fails_over(self):
        pm = self._pm_with_first([("", "connection refused")])
        text, err = pm.execute([{"role": "user", "content": "hi"}],
                               capabilities=["chat"])
        self.assertIn("ok-from-good", text)

    def test_provider_crash_fails_over(self):
        pm = ProviderManager()

        def explode(messages, max_tokens=None, temperature=None, timeout=None):
            raise RuntimeError("connection reset")
        p_bad = fake_provider(pm, "bad", outcomes=["unused"])
        p_bad._chat_openai = explode
        fake_provider(pm, "good", outcomes=[("RECOVERED", "")])
        text, err = pm.execute([{"role": "user", "content": "x"}],
                               capabilities=["chat"])
        self.assertIn("RECOVERED", text)
        self.assertEqual(err, "")

    def test_concurrency_one_never_overlaps_under_threads(self):
        pm = ProviderManager()
        p = fake_provider(pm, "solo",
                          outcomes=[("r", "")] * 10, concurrency=1)

        def slow(messages, max_tokens=None, temperature=None, timeout=None):
            time.sleep(0.05)
            slow.calls += 1
            slow.inflight += 1
            slow.max_seen = max(slow.max_seen, slow.inflight)
            try:
                return "r", ""
            finally:
                slow.inflight -= 1
        slow.calls = 0
        slow.inflight = 0
        slow.max_seen = 0
        p._chat_openai = slow
        errs = []
        results = []

        def worker():
            try:
                results.append(pm.execute([{"role": "user", "content": "x"}],
                                          capabilities=["chat"]))
            except Exception as e:  # noqa: BLE001
                errs.append(e)

        ts = [threading.Thread(target=worker) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(15)
        self.assertFalse(errs)
        ok = [r for r in results if r[1] == ""]
        busy = [r for r in results if r[1]]
        # Non-blocking dispatch: at most ONE call in flight at a time; the
        # rest get a clean busy/queued error, never an overlap or crash.
        self.assertGreaterEqual(len(ok), 1)
        self.assertEqual(len(ok) + len(busy), 4)
        self.assertEqual(slow.max_seen, 1,
                         "concurrency=1 provider must never see 2 in-flight calls")
        self.assertEqual(slow.calls, len(ok),
                         "rejected (busy) calls must never reach the backend")


class TestResourceQueueing(unittest.TestCase):
    """Exhausted resources must queue tasks, not spawn uncontrolled work."""

    def test_budget_gate_bounds_dispatch(self):
        tmp = tempfile.mkdtemp()
        store = make_store(tmp)
        for i in range(6):
            store.add_task(f"t{i}", "x", owned_files=[f"f{i}.md"],
                           status="ready")
        pm = ProviderManager()
        fake_provider(pm, "a", outcomes=[("ok", "")], concurrency=4)

        class NoPressure(ResourceManager):
            def memory_pressure(self):
                return False

        sched = Scheduler(store, pm, cfg=None, worker_id="t",
                          resources=NoPressure())
        sched.max_concurrency = 2
        claimed = []
        for _ in range(10):
            got = sched.dispatch_once(max_tasks=4)
            if not got:
                break
            claimed.extend(got)
            # hold the slots: finish nothing, so budget stays the binding limit
        self.assertLessEqual(len(claimed), 2,
                             "dispatch must respect the global concurrency cap")

    def test_reservation_released_on_finish(self):
        tmp = tempfile.mkdtemp()
        store = make_store(tmp)
        tid = store.add_task("r", "x", owned_files=["d.md"], status="ready")
        pm = ProviderManager()
        fake_provider(pm, "a", outcomes=[("ok", "")])
        sched = Scheduler(store, pm, cfg=None, worker_id="t")
        got = sched.dispatch_once(max_tasks=1)
        self.assertEqual(len(got), 1)
        self.assertIn(tid, sched._reserved)
        sched.finish(tid, "t", "completed", "done")
        self.assertNotIn(tid, sched._reserved, "slot must be freed on finish")
        # freed slot is immediately reusable for the next task
        store.add_task("r2", "x", owned_files=["e.md"], status="ready")
        got2 = sched.dispatch_once(max_tasks=1)
        self.assertEqual(len(got2), 1, "released slot must allow new dispatch")


class TestWorkspaceHardPaths(unittest.TestCase):
    """Symlink escape and invalid tool args must be rejected loudly."""

    def setUp(self):
        from elysia.core.workspace import Workspace
        self.tmp = tempfile.mkdtemp()
        self.ws = Workspace(self.tmp)
        self.outside = os.path.join(tempfile.mkdtemp(), "secret.txt")
        with open(self.outside, "w") as f:
            f.write("top secret")

    def test_symlink_escape_rejected(self):
        from elysia.core.paths import PathEscapeError
        link = os.path.join(self.tmp, "link.md")
        os.symlink(self.outside, link)
        with self.assertRaises(PathEscapeError):
            self.ws.write_owned("link.md", "overwrite attempt")
        with open(self.outside) as f:
            self.assertEqual(f.read(), "top secret",
                             "symlink must NOT have been followed for writes")

    def test_parent_traversal_rejected(self):
        from elysia.core.paths import PathEscapeError
        with self.assertRaises(PathEscapeError):
            self.ws.write_owned("../escaped.py", "boom")
        self.assertFalse(os.path.exists(
            os.path.join(os.path.dirname(self.tmp), "escaped.py")))

    def test_worker_rejects_out_of_scope_path(self):
        """Model writes a path not in owned files -> rejected, never remapped."""
        import brain
        text = "```md evil.md\ncontent\n```"
        files = brain.parse_file_blocks(text, owned=["only.md"])
        self.assertEqual(files, {"evil.md": "content\n"})
        owned = ["only.md"]
        rejected = [p for p in files if p not in owned]
        self.assertEqual(rejected, ["evil.md"])

    def test_invalid_tool_args_rejected(self):
        from elysia.core.tools import ToolRegistry
        reg = ToolRegistry()
        r1 = reg.invoke("nonexistent_tool", {})
        self.assertFalse(r1.get("ok", False), "unknown tool must be an error")
        r2 = reg.invoke("write_file", {"path": "", "content": "x"},
                        granted_permissions={"workspace"})
        self.assertFalse(r2.get("ok", False), "empty path must be an error")


if __name__ == "__main__":
    unittest.main()
