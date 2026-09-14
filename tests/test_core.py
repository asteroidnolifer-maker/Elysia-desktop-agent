import os
import sys
import tempfile
import threading
import time
import types
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.events import EventBus
from elysia.core.providers import Provider, ProviderManager
from elysia.core.config import ProviderConfig
from elysia.core.qa import validate_file, validate_json, validate_python
from elysia.core.tasks import TaskStore
from elysia.core.scheduler import Scheduler


def fake_cfg(**kw):
    from elysia.core.config import Config, SchedulerConfig
    c = Config()
    for k, v in kw.items():
        setattr(c.scheduler, k, v)
    return c


class FakeBackend:
    """Scripted provider transport. Attach as provider._chat_unaccounted.

    Outcomes: list of callables or (text, err) tuples; the last one repeats.
    """

    def __init__(self, outcomes, on_call=None):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.lock = threading.Lock()
        self.on_call = on_call

    def __call__(self, messages, max_tokens=None, temperature=None,
                 timeout=None):
        with self.lock:
            self.calls += 1
            i = min(self.calls - 1, len(self.outcomes) - 1)
            out = self.outcomes[i]
            if self.on_call:
                self.on_call(self.calls)
            return out() if callable(out) else out


def fake_provider(pm, label, model="m", outcomes=(), capabilities=None,
                  concurrency=1, status="healthy"):
    """Register a provider with a scripted FakeBackend at the transport seam.

    The transport (``_chat_openai``) is replaced, so the real accounting path
    (``_chat_unaccounted``: requests, failures, status transitions) runs.
    """
    p = pm.register(ProviderConfig(
        kind="openai", label=label, model=model,
        capabilities=capabilities or ["chat"], concurrency=concurrency))
    p._chat_openai = FakeBackend(outcomes if outcomes else [("", "no script")])
    p.status = status
    return p


class TestProviderManager(unittest.TestCase):
    def test_register_and_select(self):
        pm = ProviderManager()
        pm.register(ProviderConfig(kind="openai", label="a",
                                   model="m1", capabilities=["chat"], concurrency=1))
        pm.register(ProviderConfig(kind="openai", label="b",
                                   model="m2", capabilities=["coding"], concurrency=1))
        self.assertEqual(len(pm.list()), 2)
        p = pm.select(["chat"])
        self.assertEqual(p.name, "a")
        p2 = pm.select(["coding"])
        self.assertEqual(p2.name, "b")

    def test_execute_succeeds_with_concurrency_one(self):
        # REGRESSION: ProviderManager.execute used to acquire a slot and then
        # Provider.chat acquired AGAIN, so concurrency=1 always reported busy.
        pm = ProviderManager()
        fake_provider(pm, "a", outcomes=[("hello", "")], concurrency=1)
        text, err = pm.execute([{"role": "user", "content": "hi"}])
        self.assertEqual(text, "hello")
        self.assertEqual(err, "")
        self.assertEqual(pm.get("a").in_flight, 0)  # slot released

    def test_execute_never_exceeds_concurrency(self):
        pm = ProviderManager()
        p = fake_provider(pm, "a", outcomes=[("r", "")] * 50, concurrency=2)

        def slow_call(messages, max_tokens=None, temperature=None, timeout=None):
            time.sleep(0.05)  # hold the slot long enough to force contention
            return "r", ""

        p._chat_openai = slow_call
        barrier = threading.Barrier(3)
        outcomes = []
        lock = threading.Lock()

        def run():
            barrier.wait(timeout=2)  # all 3 threads launch simultaneously
            r = pm.execute([{"role": "user", "content": "x"}])
            with lock:
                outcomes.append(r)

        ts = [threading.Thread(target=run) for _ in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=5)
        ok = [r for r in outcomes if r[1] == ""]
        busy = [r for r in outcomes if r[1]]
        # exactly 2 slots succeeded concurrently; the 3rd saw the provider busy
        self.assertEqual(len(ok), 2)
        self.assertEqual(len(busy), 1)
        self.assertLessEqual(p.in_flight, 2)  # accounting never exceeded slots

    def test_failover_a_errors_b_takes_over(self):
        pm = ProviderManager()
        fake_provider(pm, "a", outcomes=[("", "http 500: boom")])
        fake_provider(pm, "b", outcomes=[("from B", "")])
        text, err = pm.execute([{"role": "user", "content": "x"}])
        self.assertEqual(text, "from B")
        self.assertEqual(err, "")
        self.assertEqual(pm.get("a").failures, 1)

    def test_failover_a_rate_limits_b_takes_over(self):
        pm = ProviderManager()
        fake_provider(pm, "a", outcomes=[("", "http 429: rate limited")])
        fake_provider(pm, "b", outcomes=[("from B", "")])
        text, err = pm.execute([{"role": "user", "content": "x"}])
        self.assertEqual(text, "from B")
        self.assertEqual(pm.get("a").status, "rate_limited")

    def test_failover_a_crashes_b_executes_same_task(self):
        pm = ProviderManager()

        def explode(messages, max_tokens=None, temperature=None, timeout=None):
            raise RuntimeError("connection reset")
        p_a = fake_provider(pm, "a", outcomes=["unused"])
        p_a._chat_openai = explode
        fake_provider(pm, "b", outcomes=[("RECOVERED", "")])
        text, err = pm.execute([{"role": "user", "content": "x"}])
        self.assertEqual(text, "RECOVERED")
        self.assertEqual(err, "")

    def test_reservation_holds_slot(self):
        pm = ProviderManager()
        p = fake_provider(pm, "a", outcomes=[("ok", "")], concurrency=1)
        r1 = pm.reserve()
        self.assertIsNotNone(r1)
        # second reservation on concurrency=1 must fail while r1 held
        r2 = pm.reserve()
        self.assertIsNone(r2)
        r1.release()
        r3 = pm.reserve()
        self.assertIsNotNone(r3)
        r3.release()

    def test_selection_by_capability_and_priority(self):
        pm = ProviderManager()
        fake_provider(pm, "slow", outcomes=[("s", "")], capabilities=["chat"])
        fake_provider(pm, "coder", outcomes=[("c", "")],
                      capabilities=["chat", "coding"])
        # coding work must land on the provider that supports it
        text, _ = pm.execute([{"role": "user", "content": "code"}],
                             capabilities=["coding"])
        self.assertEqual(text, "c")


class TestHealthStatus(unittest.TestCase):
    def test_unavailable_when_connection_refused(self):
        p = Provider(ProviderConfig(kind="openai", label="x", model="m",
                                    base_url="http://127.0.0.1:1/v1", timeout_s=2))
        self.assertIn(p.check_health(), ("degraded", "unavailable"))


class TestQA(unittest.TestCase):
    def test_python_syntax(self):
        ok, _ = validate_python("x.py", "def f():\n    return 1\n")
        self.assertTrue(ok)
        ok, reason = validate_python("x.py", "def f(:\n")
        self.assertFalse(ok)
        self.assertIn("syntax", reason)

    def test_json(self):
        ok, _ = validate_json('{"a": 1}')
        self.assertTrue(ok)
        ok, _ = validate_json('{"a": ')
        self.assertFalse(ok)

    def test_markdown(self):
        ok, _ = validate_file("docs/a.md", "# Heading\n\nBody text here\n")
        self.assertTrue(ok)
        ok, _ = validate_file("docs/a.md", "no heading")
        self.assertFalse(ok)

    def test_json_file(self):
        ok, _ = validate_file("config.json", '{"k": "v"}')
        self.assertTrue(ok)


class TestScheduler(unittest.TestCase):
    def _store(self):
        d = tempfile.mkdtemp()
        return TaskStore(os.path.join(d, "tasks.sqlite"))

    def test_dependencies_block(self):
        store = self._store()
        a = store.add_task("A", owned_files=["a.py"])
        b = store.add_task("B", owned_files=["b.py"], dependencies=[a])
        # tasks default to queued; mark ready to be dispatchable
        store.mark_ready(a)
        store.mark_ready(b)
        ready = store.ready_tasks()
        self.assertEqual([t["id"] for t in ready], [a])

        store.complete(a, "done", "ok")
        ready = store.ready_tasks()
        self.assertEqual([t["id"] for t in ready], [b])

    def test_claim_and_expiry(self):
        store = self._store()
        tid = store.add_task("T", owned_files=["t.py"])
        store.mark_ready(tid)
        pm = ProviderManager()
        pm.register(ProviderConfig(kind="openai", label="p", model="m",
                                   concurrency=2))
        ev = EventBus()
        s = Scheduler(store, pm, ev, cfg=fake_cfg(lease_seconds=1, max_attempts=2))
        claimed = s.dispatch_once()
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["id"], tid)
        t = store.get(tid)
        self.assertEqual(t["status"], "claimed")
        self.assertEqual(t["provider"], "p")

        # second dispatch must NOT re-claim (lease not expired)
        self.assertEqual(len(s.dispatch_once()), 0)

        # simulate crash: wait until lease expires, release_expired reopens
        import time
        time.sleep(1.2 if "CI" not in os.environ else 1.5)
        released = store.release_expired(max_attempts=2)
        self.assertEqual(released, [tid])
        self.assertEqual(store.get(tid)["status"], "ready")

    def test_lease_retries_then_fails(self):
        store = self._store()
        tid = store.add_task("T", owned_files=["t.py"], max_attempts=1)
        store.mark_ready(tid)
        store.claim(tid, "w", "p", "m", 1)
        import time
        time.sleep(1.2 if "CI" not in os.environ else 1.5)
        released = store.release_expired(max_attempts=1)
        self.assertEqual(released, [])
        self.assertEqual(store.get(tid)["status"], "failed")

    def test_dependency_failure_propagates(self):
        store = self._store()
        a = store.add_task("A", owned_files=["a.py"])
        b = store.add_task("B", owned_files=["b.py"], dependencies=[a])
        store.mark_ready(a)
        store.mark_ready(b)
        store.complete(a, "failed", "boom")
        affected = store.failed_after_dependency(a)
        self.assertEqual(affected, [b])
        self.assertEqual(store.get(b)["status"], "dependency_failed")

    def test_cancel_pause_resume(self):
        store = self._store()
        a = store.add_task("A")
        store.mark_ready(a)
        self.assertEqual(store.pause(a), True)
        self.assertEqual(store.get(a)["status"], "queued")
        self.assertEqual(store.resume(a), True)
        self.assertEqual(store.get(a)["status"], "ready")
        affected = store.cancel(a, by="cli")
        self.assertIn(a, affected)
        self.assertEqual(store.get(a)["status"], "cancelled")

    def test_event_emission(self):
        ev = EventBus()
        ev.emit("test", task_id=1, status="ok")
        ev.emit("test", task_id=2, status="ok")
        self.assertEqual(len(ev.recent()), 2)
        self.assertEqual(ev.recent(event_type="test")[0]["task_id"], 1)


class TestTaskStateMachine(unittest.TestCase):
    """The task lifecycle is an explicit edge table — illegal moves raise."""

    def _store(self):
        d = tempfile.mkdtemp()
        return TaskStore(os.path.join(d, "tasks.sqlite"))

    def test_happy_path_transitions(self):
        s = self._store()
        tid = s.add_task("T", owned_files=["t.py"])
        s.mark_ready(tid)                     # queued -> ready
        self.assertEqual(s.get(tid)["status"], "ready")
        self.assertTrue(s.claim(tid, "w", "p", "m", 60))  # ready -> claimed
        s.transition(tid, "running")
        s.transition(tid, "testing")
        s.transition(tid, "reviewing")
        s.transition(tid, "completed")        # reviewing -> completed
        self.assertEqual(s.get(tid)["status"], "completed")
        self.assertIsNotNone(s.get(tid)["completed_at"])

    def test_queued_to_completed_rejected(self):
        s = self._store()
        tid = s.add_task("T")
        with self.assertRaises(ValueError):
            s.transition(tid, "completed")

    def test_running_to_queued_rejected(self):
        s = self._store()
        tid = s.add_task("T")
        s.mark_ready(tid)
        s.claim(tid, "w", "p", "m", 60)
        s.transition(tid, "running")
        with self.assertRaises(ValueError):
            s.transition(tid, "queued")
        with self.assertRaises(ValueError):
            s.set_status(tid, "queued")       # set_status routes through table

    def test_skipped_stages_rejected(self):
        # queued -> running skips the ready/claimed steps: illegal
        s = self._store()
        tid = s.add_task("T")
        s.mark_ready(tid)
        with self.assertRaises(ValueError):
            s.transition(tid, "running")      # ready->running is not an edge
        # claimed -> done is legal (a worker may finish directly); queued -> done is not
        s.claim(tid, "w", "p", "m", 60)
        s.transition(tid, "done")
        self.assertEqual(s.get(tid)["status"], "done")

    def test_complete_routes_through_table(self):
        s = self._store()
        tid = s.add_task("T")
        # ready -> done is a legal force-complete; queued -> done is not
        with self.assertRaises(ValueError):
            s.complete(tid, "done", "ok")

    def test_mark_ready_rejects_illegal_state(self):
        s = self._store()
        tid = s.add_task("T")
        s.mark_ready(tid)
        s.claim(tid, "w", "p", "m", 60)
        with self.assertRaises(ValueError):
            s.mark_queued(tid)                # claimed -> queued is not legal

    def test_retry_only_from_failed(self):
        s = self._store()
        tid = s.add_task("T")
        s.mark_ready(tid)
        self.assertFalse(s.retry(tid))        # ready is not terminal
        s.transition(tid, "failed")           # ready -> failed (force)
        self.assertTrue(s.retry(tid))
        self.assertEqual(s.get(tid)["status"], "ready")

    def test_lease_expiry_transitions_are_table_legal(self):
        s = self._store()
        tid = s.add_task("T")
        s.mark_ready(tid)
        s.claim(tid, "w", "p", "m", 1)
        time.sleep(1.1)
        released = s.release_expired(max_attempts=3)
        self.assertEqual(released, [tid])
        self.assertEqual(s.get(tid)["status"], "ready")  # claimed -> ready

    def test_dependency_failed_edge(self):
        s = self._store()
        a = s.add_task("A")
        b = s.add_task("B", dependencies=[a])
        s.mark_ready(a)
        s.mark_ready(b)
        s.complete(a, "failed", "boom")
        affected = s.failed_after_dependency(a)
        self.assertEqual(affected, [b])
        self.assertEqual(s.get(b)["status"], "dependency_failed")


class TestBrainDelegation(unittest.TestCase):
    """brain.py must route through ProviderManager, not cfg.providers[0]."""

    def test_brain_chat_fails_over_to_second_provider(self):
        from unittest import mock
        import orchestrator.brain as brain
        pm = ProviderManager()
        fake_provider(pm, "a", outcomes=[("", "http 500: nope")])
        fake_provider(pm, "b", outcomes=[("answer from B", "")])
        with mock.patch.object(brain, "_manager", return_value=pm):
            text, err = brain.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(text, "answer from B")
        self.assertEqual(err, "")
        self.assertEqual(pm.get("a").failures, 1)

    def test_brain_health_is_any_provider(self):
        from unittest import mock
        import orchestrator.brain as brain
        pm = ProviderManager()
        fake_provider(pm, "a", outcomes=[("", "err")], status="unavailable")
        with mock.patch.object(brain, "_manager", return_value=pm):
            for p in pm.list():
                p.check_health = lambda p=p: p.status
            self.assertFalse(brain.health())   # all unhealthy
            fake_provider(pm, "b", outcomes=[("ok", "")], status="healthy")
            p_b = pm.get("b")
            p_b.check_health = lambda: "healthy"
            self.assertTrue(brain.health())    # one healthy is enough


if __name__ == "__main__":
    unittest.main()