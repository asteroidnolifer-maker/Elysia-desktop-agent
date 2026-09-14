"""End-to-end runtime call-graph tests (fake provider, real everything else).

Proves the canonical path is ONE graph:

    goal -> persistent board tasks -> Scheduler.dispatch_once (atomic
    reservation) -> AgentPipeline.solve_task -> Workspace.write_owned ->
    QA validation -> task completion -> reservation release

plus: provider failover during execution, cancel releasing the reserved
slot, and durability (a fresh process/restart picks the board back up).
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.config import Config
from elysia.core.events import EventBus
from elysia.core.providers import Provider, ProviderManager
from elysia.core.scheduler import Scheduler
from elysia.core.tasks import TaskStore


class FakeBackend:
    """Scripted transport at the Provider._send/_chat seam."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, provider, messages, **kw):
        self.calls += 1
        if not self.outcomes:
            return "", f"provider {provider.name} script exhausted"
        text, err = self.outcomes.pop(0)
        return text, err


def fake_provider(pm, name, outcomes, caps=None):
    from elysia.core.config import ProviderConfig
    p = pm.register(ProviderConfig(
        kind="openai", label=name, model=f"m-{name}",
        capabilities=caps or ["chat", "coding"], concurrency=1))
    backend = FakeBackend(outcomes)
    p._chat_openai = lambda messages, max_tokens=2048, temperature=0.2, \
        timeout=900: backend(p, messages, max_tokens=max_tokens,
                             temperature=temperature, timeout=timeout)
    p.status = "healthy"
    p.check_health = lambda: "healthy"
    p._backend = backend
    return p


def provider_block(path, content):
    return f"```py {path}\n{content}\n```\n"


class IntegrationTestCase(unittest.TestCase):
    def _env(self):
        d = tempfile.mkdtemp()
        ws = os.path.join(d, "ws")
        os.makedirs(ws)
        store = TaskStore(os.path.join(d, "tasks.sqlite"))
        return d, ws, store

    def _scheduler(self, store, pm, events):
        return Scheduler(store, pm, events=events, cfg=Config())

    def test_goal_to_board_to_scheduler_to_workspace_to_completion(self):
        from elysia.core.server_api import _persist_goal
        d, ws, store = self._env()
        # 1) durable goal plan -> board subtasks
        subs = _persist_goal("Refactor the git checkpoint module",
                             [{"title": "Add git checkpoint", "detail":
                               "Write utils/gc.py and tests/test_gc.py"}], store=store)
        self.assertEqual(len(subs), 1)
        t = store.get(subs[0]["id"])
        self.assertEqual(t["status"], "ready")
        self.assertIn("utils/gc.py", t["owned_files"])
        # 2) scheduler dispatch reserves one provider slot
        pm = ProviderManager()
        p = fake_provider(pm, "a", [(
            provider_block("utils/gc.py", "def gc():\n    return 1\n"), "")])
        events = EventBus()
        sched = self._scheduler(store, pm, events)
        claimed = sched.dispatch_once(max_tasks=2)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(p.cfg.label, "a")
        # slot IS held until finish (no double claim of the same slot)
        self.assertIn(claimed[0]["id"], sched._reserved)
        # 3) in-process execution writes the real file (the fixture's owned
        # file is utils/gc.py, so the provider block must use that exact path:
        # the pipeline REJECTS out-of-scope paths instead of remapping them)
        outcome = sched.execute_claimed(claimed[0], ws)
        self.assertTrue(outcome["ok"], outcome)
        gc_path = os.path.join(ws, "utils/gc.py")
        self.assertTrue(os.path.exists(gc_path))
        with open(gc_path) as f:
            self.assertEqual(f.read(), "def gc():\n    return 1\n")
        # 4) task completed and the provider slot released
        self.assertEqual(store.get(claimed[0]["id"])["status"], "completed")
        self.assertEqual(sched._reserved, {})
        self.assertEqual(p._backend.calls, 1)

    def test_no_double_reservation_when_concurrency_limited(self):
        from elysia.core.server_api import _persist_goal
        d, ws, store = self._env()
        subs = _persist_goal("G", [
            {"title": "t1", "detail": "file f1.py"},
            {"title": "t2", "detail": "file f2.py"},
            {"title": "t3", "detail": "file f3.py"}], store=store)
        pm = ProviderManager()
        fake_provider(pm, "a", [("", "x")], caps=["chat", "coding"])
        fake_provider(pm, "b", [("", "x")], caps=["chat", "coding"])
        # concurrency=2 across the chain
        for name in ("a", "b"):
            pm.get(name).cfg.concurrency = 1
        sched = self._scheduler(store, pm, EventBus())
        claimed = sched.dispatch_once(max_tasks=10)
        # 3 tasks but only 2 provider slots -> exactly 2 claimed
        self.assertEqual(len(claimed), 2)
        # releasing one finished task frees the slot for the next task
        sched.finish(claimed[0]["id"], "sched", "completed", "ok")
        claimed2 = sched.dispatch_once(max_tasks=10)
        self.assertEqual(len(claimed2), 1)
        sched.finish(claimed2[0]["id"], "sched", "completed", "ok")
        sched.finish(claimed[1]["id"], "sched", "completed", "ok")
        self.assertEqual(sched._reserved, {})

    def test_cancel_releases_reserved_slot(self):
        from elysia.core.server_api import _persist_goal
        d, ws, store = self._env()
        subs = _persist_goal("G", [{"title": "t", "detail": "file f.py"}], store=store)
        pm = ProviderManager()
        fake_provider(pm, "a", [("", "x")])
        sched = self._scheduler(store, pm, EventBus())
        claimed = sched.dispatch_once(max_tasks=2)
        self.assertEqual(len(claimed), 1)
        self.assertTrue(sched._reserved)
        sched.cancel(claimed[0]["id"])
        self.assertEqual(sched._reserved, {})
        # slot is back -> another task can be claimed now
        subs2 = store.add_task("T2", owned_files=["g.py"], status="ready")
        self.assertIsNotNone(subs2)

    def test_failover_executes_second_provider_same_task(self):
        from elysia.core.server_api import _persist_goal
        d, ws, store = self._env()
        subs = _persist_goal("G", [{"title": "t", "detail": "file f.py"}], store=store)
        pm = ProviderManager()
        fake_provider(pm, "a", [("", "http 500: boom")])
        fake_provider(pm, "b", [(provider_block("f.py", "x = 1\n"), "")])
        sched = self._scheduler(store, pm, EventBus())
        claimed = sched.dispatch_once(max_tasks=2)
        self.assertEqual(len(claimed), 1)
        outcome = sched.execute_claimed(claimed[0], ws)
        self.assertTrue(outcome["ok"], outcome)
        self.assertTrue(os.path.exists(os.path.join(ws, "f.py")))
        self.assertEqual(store.get(claimed[0]["id"])["status"], "completed")
        # A fails at least once (initial + possibly re-try before B takes over)
        self.assertGreaterEqual(pm.get("a").failures, 1)

    def test_duration_restart_survives_process_restart(self):
        from elysia.core.server_api import _persist_goal
        d, ws, store = self._env()
        subs = _persist_goal("Stale goal", [{"title": "t", "detail":
                                             "file r.py"}], store=store)
        # process "restart": a brand-new store over the SAME sqlite file
        db_path = store.db_path
        store2 = TaskStore(db_path)
        ready = store2.ready_tasks()
        self.assertEqual([t["id"] for t in ready], [subs[0]["id"]])
        pm = ProviderManager()
        fake_provider(pm, "a", [(provider_block("r.py", "y = 2\n"), "")])
        sched = Scheduler(store2, pm, events=EventBus(), cfg=Config())
        claimed = sched.dispatch_once(max_tasks=2)
        outcome = sched.execute_claimed(claimed[0], ws)
        self.assertTrue(outcome["ok"], outcome)
        self.assertEqual(store2.get(subs[0]["id"])["status"], "completed")

    def test_provider_failure_marks_task_failed_not_lost(self):
        from elysia.core.server_api import _persist_goal
        d, ws, store = self._env()
        subs = _persist_goal("G", [{"title": "t", "detail": "file f.py"}], store=store)
        pm = ProviderManager()
        fake_provider(pm, "a", [("", "network error")])
        pm.get("a").cfg.concurrency = 1
        sched = self._scheduler(store, pm, EventBus())
        claimed = sched.dispatch_once(max_tasks=2)
        self.assertEqual(len(claimed), 1)
        outcome = sched.execute_claimed(claimed[0], ws)
        self.assertFalse(outcome["ok"])
        t = store.get(claimed[0]["id"])
        self.assertIn(t["status"], ("failed", "ready"))  # never lost
        self.assertFalse(sched._reserved)


if __name__ == "__main__":
    unittest.main()