import os
import sys
import tempfile
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
        ready = store.ready_tasks()
        # only A (no deps) is ready; B waits for A
        self.assertEqual([t["id"] for t in ready], [a])

        store.complete(a, "done", "ok")
        ready = store.ready_tasks()
        self.assertEqual([t["id"] for t in ready], [b])

    def test_claim_and_expiry(self):
        store = self._store()
        tid = store.add_task("T", owned_files=["t.py"])
        pm = ProviderManager()
        pm.register(ProviderConfig(kind="openai", label="p", model="m", concurrency=2))
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
        time.sleep(1.2)
        released = store.release_expired(max_attempts=2)
        self.assertEqual(released, [tid])
        self.assertEqual(store.get(tid)["status"], "open")

    def test_lease_retries_then_fails(self):
        store = self._store()
        # pre-seed attempts = max so release fails it
        tid = store.add_task("T", owned_files=["t.py"], max_attempts=1)
        store.claim(tid, "w", "p", "m", 1)
        import time
        time.sleep(1.2)
        released = store.release_expired(max_attempts=1)
        self.assertEqual(released, [])
        self.assertEqual(store.get(tid)["status"], "failed")

    def test_event_emission(self):
        ev = EventBus()
        ev.emit("test", task_id=1, status="ok")
        ev.emit("test", task_id=2, status="ok")
        self.assertEqual(len(ev.recent()), 2)
        self.assertEqual(ev.recent(event_type="test")[0]["task_id"], 1)


if __name__ == "__main__":
    unittest.main()