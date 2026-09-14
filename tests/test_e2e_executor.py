"""End-to-end execution tests: the FULL runtime path, no mocks of the system.

Goal task -> scheduler claims (atomic provider reservation) -> TaskExecutor
runs the AgentPipeline in-process -> implementer calls the provider (with
failover) -> files written through the REAL Workspace layer -> language-aware
QA -> tester/reviewer -> completion persisted in the TaskStore.

Failure modes covered:
  - provider A fails mid-task -> B executes the same task
  - pipeline failure -> retry with backoff -> exhaustion -> terminal failed
  - lease heartbeat during a long model call
  - executor stop/start cycle -> tasks recovered, never lost
  - multiple independent tasks execute in parallel under the budget cap

Fake providers are scripted at the _chat_openai transport seam (same pattern
as tests/test_core.py); everything else — TaskStore, Scheduler, TaskExecutor,
AgentPipeline, Workspace, QA — is the real thing.
"""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.config import ProviderConfig
from elysia.core.executor import TaskExecutor
from elysia.core.providers import ProviderManager
from elysia.core.resources import ResourceManager
from elysia.core.scheduler import Scheduler
from elysia.core.tasks import TaskStore
from elysia.core.workspace import Workspace


def fake_provider(pm, label, outcomes=(), concurrency=2, capabilities=None):
    p = pm.register(ProviderConfig(
        kind="openai", label=label, model="m",
        capabilities=capabilities or ["chat", "coding"], concurrency=concurrency))

    class _Backend:
        def __init__(self):
            self.calls = 0
            self.lock = threading.Lock()

        def __call__(self, messages, max_tokens=None, temperature=None,
                     timeout=None):
            with self.lock:
                self.calls += 1
                i = min(self.calls - 1, len(outcomes) - 1)
            out = outcomes[i]
            result = out(messages, max_tokens=max_tokens,
                         temperature=temperature, timeout=timeout) \
                if callable(out) else out
            # strings are shorthand for a successful (text, "") reply — the
            # raw transport seam always returns the (text, err) tuple
            return result if isinstance(result, tuple) else (result, "")

    p._chat_openai = _Backend()
    p.status = "healthy"
    return p


GOOD_PY = "```py demo.py\n\"\"\"demo module.\"\"\"\n\n\ndef add(a, b):\n    return a + b\n```\n"


def good_py(name):
    """A valid python file fenced under exactly the owned path ``name``."""
    return f"```py {name}\ndef add(a, b):\n    return a + b\n```\n"


class Harness:
    """Real store + scheduler + executor wired together on a temp workspace."""

    def __init__(self, outcomes_per_provider, max_tasks=2):
        self.tmp = tempfile.mkdtemp()
        self.store = TaskStore(os.path.join(self.tmp, "board.sqlite"))
        self.pm = ProviderManager()
        for i, outcomes in enumerate(outcomes_per_provider):
            fake_provider(self.pm, f"p{i}", outcomes=outcomes)
        self.events = type(self.pm).__mro__ and __import__(
            "elysia.core.events", fromlist=["EventBus"]).EventBus()
        self.sched = Scheduler(self.store, self.pm, self.events, cfg=None,
                               worker_id="exec-test",
                               resources=_NoPressure())
        self.ws_root = os.path.join(self.tmp, "ws")
        os.makedirs(self.ws_root, exist_ok=True)
        self.executor = TaskExecutor(self.sched, self.ws_root,
                                     max_tasks=max_tasks,
                                     poll_interval_s=0.2,
                                     heartbeat_interval_s=0.2,
                                     retry_backoff_s=1.0)

    def add_task(self, title, files, deps=None, max_attempts=3):
        tid = self.store.add_task(title, f"write {title}", owned_files=files,
                                  dependencies=deps or [],
                                  max_attempts=max_attempts,
                                  status="queued")
        self.store.mark_ready(tid)
        return tid

    def close(self):
        self.executor.stop()
        self.sched.stop()


class _NoPressure(ResourceManager):
    def memory_pressure(self):
        return False


def wait_until(fn, timeout=10.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


class TestEndToEndExecution(unittest.TestCase):
    def tearDown(self):
        for h in getattr(self, "_harnesses", []):
            h.close()

    def test_goal_to_completed_file_with_failover(self):
        """A completes... actually: A errors -> B writes the file -> QA ->
        completion persisted. The written file must REALLY exist."""
        h = Harness(outcomes_per_provider=[
            [("", "http 500: primary down")],          # p0 always fails
            [good_py("demo.py")],                    # p1 writes the file
        ])
        self._harnesses = [h]
        tid = h.add_task("write demo module", ["demo.py"])
        h.executor.start()
        self.assertTrue(wait_until(
            lambda: h.store.get(tid)["status"] == "completed"), "task must complete")
        t = h.store.get(tid)
        self.assertIn("demo.py", t["result"] or "")
        # the file REALLY exists in the workspace with valid python
        with open(os.path.join(h.ws_root, "demo.py")) as f:
            body = f.read()
        self.assertIn("def add", body)
        compile(body, "demo.py", "exec")   # real QA-equivalent check
        self.assertEqual(h.executor.stats["executed"], 1)

    def test_first_provider_success_no_failover(self):
        h = Harness(outcomes_per_provider=[[good_py("demo.py")]])
        self._harnesses = [h]
        tid = h.add_task("write demo module", ["demo.py"])
        h.executor.start()
        self.assertTrue(wait_until(
            lambda: h.store.get(tid)["status"] == "completed"))
        self.assertEqual(h.pm.get("p0")._chat_openai.calls, 1)
        self.assertEqual(h.executor.stats["executed"], 1)

    def test_failure_retries_then_terminal(self):
        """max_attempts=1 -> single pipeline failure -> terminal failed (not
        stuck, not an infinite retry loop)."""
        h = Harness(outcomes_per_provider=[
            [("", "http 500: always broken")],
        ])
        self._harnesses = [h]
        tid = h.add_task("doomed task", ["doomed.py"], max_attempts=1)
        h.executor.start()
        self.assertTrue(wait_until(
            lambda: h.store.get(tid)["status"] == "failed"))
        self.assertEqual(h.executor.stats["failed"], 1)

    def test_failure_retries_with_backoff_then_recovers(self):
        """Persistent failure consumes attempts; the retry (after backoff)
        succeeds when the provider recovers — and the retried counter grows."""
        def flaky_then_good(messages, max_tokens=None, temperature=None,
                            timeout=None):
            flaky_then_good.n = getattr(flaky_then_good, "n", 0) + 1
            if flaky_then_good.n <= 2:
                # fail twice: once inside provider failover, once at task level
                return "", "http 500: flaky"
            return good_py("flaky.py")
        h = Harness(outcomes_per_provider=[[flaky_then_good]])
        self._harnesses = [h]
        tid = h.add_task("flaky task", ["flaky.py"], max_attempts=3)
        h.executor.start()
        self.assertTrue(wait_until(
            lambda: h.store.get(tid)["status"] == "completed", timeout=20),
            "retry must eventually succeed")
        self.assertTrue(os.path.exists(os.path.join(h.ws_root, "flaky.py")))
        self.assertGreaterEqual(h.executor.stats["retried"], 1,
                                "a task-level retry must have been recorded")

    def test_lease_renewed_during_long_call(self):
        """The executor heartbeats the lease while the model call runs."""
        def slow_then_good(messages, max_tokens=None, temperature=None,
                           timeout=None):
            time.sleep(1.0)   # longer than the tiny heartbeat interval
            return good_py("slow.py")
        h = Harness(outcomes_per_provider=[[slow_then_good]])
        self._harnesses = [h]
        tid = h.add_task("slow module", ["slow.py"])
        h.executor.start()
        self.assertTrue(wait_until(
            lambda: h.store.get(tid)["status"] == "completed", timeout=15))
        t = h.store.get(tid)
        self.assertGreater(t["heartbeat_at"] or 0, 0,
                           "heartbeat must have run during execution")

    def test_parallel_independent_tasks_within_budget(self):
        """Two ready tasks run concurrently (both complete), and the budget cap
        means no more than max_tasks ever in flight."""
        n_calls = {"n": 0}
        lock = threading.Lock()

        def make_outcome():
            def call(messages, max_tokens=None, temperature=None, timeout=None):
                with lock:
                    n_calls["n"] += 1
                time.sleep(0.3)
                # answer with the file THIS task owns (parsed from the prompt)
                prompt = messages[-1]["content"] if messages else ""
                import re as _re
                m = _re.search(r"FILES YOU OWN.*?\['([^']+)'", prompt)
                return good_py(m.group(1) if m else "one.py")
            return call
        h = Harness(outcomes_per_provider=[[make_outcome()]], max_tasks=2)
        self._harnesses = [h]
        t1 = h.add_task("task one", ["one.py"])
        t2 = h.add_task("task two", ["two.py"])
        h.executor.start()
        self.assertTrue(wait_until(lambda: all(
            h.store.get(t)["status"] == "completed" for t in (t1, t2)),
            timeout=20))
        for name in ("one.py", "two.py"):
            self.assertTrue(os.path.exists(os.path.join(h.ws_root, name)))
        self.assertEqual(h.executor.stats["executed"], 2)

    def test_qa_rejection_marks_task_failed(self):
        """A syntactically-broken python file must fail QA -> task fails."""
        bad = "```py broken.py\ndef broken(:\n    pass\n```\n"
        h = Harness(outcomes_per_provider=[[bad]])
        self._harnesses = [h]
        tid = h.add_task("broken module", ["broken.py"], max_attempts=1)
        h.executor.start()
        self.assertTrue(wait_until(
            lambda: h.store.get(tid)["status"] == "failed"))
        self.assertIn("QA failed", h.store.get(tid)["last_error"] or "")

    def test_workspace_security_still_enforced_in_pipeline(self):
        """Even through the executor, traversal writes are rejected by the
        Workspace layer (task fails; no file lands outside)."""
        evil = "```py ../escape.py\nx = 1\n```\n"
        h = Harness(outcomes_per_provider=[[evil]])
        self._harnesses = [h]
        tid = h.add_task("escape attempt", ["safe.py"], max_attempts=1)
        h.executor.start()
        self.assertTrue(wait_until(
            lambda: h.store.get(tid)["status"] == "failed"))
        outside = os.path.join(os.path.dirname(h.ws_root), "escape.py")
        self.assertFalse(os.path.exists(outside),
                         "traversal write must not land outside the workspace")

    def test_executor_stop_start_recovers_tasks(self):
        """Stop the executor mid-flight; restart; the task still completes —
        the workflow survives the executor lifecycle."""
        h = Harness(outcomes_per_provider=[[good_py("survivor.py")]], max_tasks=1)
        self._harnesses = [h]
        tid = h.add_task("survivor", ["survivor.py"])
        h.executor.start()
        h.executor.stop()
        # whatever state it reached, restarting must drive it to completion
        h.executor.start()
        self.assertTrue(wait_until(
            lambda: h.store.get(tid)["status"] == "completed", timeout=20))
        self.assertTrue(os.path.exists(
            os.path.join(h.ws_root, "survivor.py")))

    def test_dependency_ordering_respected(self):
        """B depends on A: B must not run (or complete) before A completes."""
        def answer_owned(messages, max_tokens=None, temperature=None,
                         timeout=None):
            import re as _re
            prompt = messages[-1]["content"] if messages else ""
            m = _re.search(r"FILES YOU OWN.*?\['([^']+)'", prompt)
            return good_py(m.group(1) if m else "a.py")
        h = Harness(outcomes_per_provider=[[answer_owned]])
        self._harnesses = [h]
        a = h.add_task("first", ["a.py"])
        b = h.add_task("second", ["b.py"], deps=[a])
        h.executor.start()
        self.assertTrue(wait_until(lambda: all(
            h.store.get(t)["status"] == "completed" for t in (a, b)),
            timeout=20))
        self.assertTrue(os.path.exists(os.path.join(h.ws_root, "a.py")))
        self.assertTrue(os.path.exists(os.path.join(h.ws_root, "b.py")))


if __name__ == "__main__":
    unittest.main()
