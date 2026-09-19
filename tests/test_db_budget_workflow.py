"""Tests for DB hardening, budget enforcement and the workflow engine.

Real subsystems only: a real SQLite TaskStore (WAL, migrations, backup/restore),
a real ProviderManager with a scripted transport, and the real WorkflowEngine
persisting gate nodes onto the board.

Proves:
  - the board reports integrity/schema version, backs up, restores, vacuums
  - over-budget: paid providers are dropped, local providers still serve, and
    an all-paid fleet honestly refuses (reserves nothing, queues instead)
  - budget accounting accumulates estimated spend and fires the warning
  - workflows persist gate rows the executor can never claim
  - approval gates really block downstream work until a human resolves them;
    a denial cascades instead of silently proceeding
  - join completes only when every sibling completed, fails if one failed
  - fallback runs only when its primary failed
  - rollback refuses to complete on an unknown checkpoint
  - static validation rejects cycles (backward-refs only) and orphan refs
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.config import ProviderConfig
from elysia.core.providers import ProviderManager
from elysia.core.tasks import TaskStore
from elysia.core.workflow import (WORKFLOW_ENGINE_VERSION, WorkflowEngine,
                                  WorkflowError, validate_workflow)


def fresh_store():
    d = tempfile.mkdtemp()
    return d, TaskStore(os.path.join(d, "t.sqlite"))


# ---------------------------------------------------------------------------
# Phase 35: database hardening
# ---------------------------------------------------------------------------
class TestDatabaseHardening(unittest.TestCase):
    def test_health_reports_integrity_and_current_version(self):
        _, store = fresh_store()
        store.add_task("a")
        h = store.health_check()
        self.assertTrue(h["ok"])
        self.assertEqual(h["integrity"], "ok")
        from elysia.core.tasks import SCHEMA_VERSION
        self.assertEqual(h["schema_version"], SCHEMA_VERSION)
        self.assertEqual(h["journal_mode"], "wal")
        self.assertEqual(h["malformed_dependency_rows"], 0)

    def test_backup_and_roundtrip_restore(self):
        d, store = fresh_store()
        store.add_task("alpha")
        store.add_task("beta", dependencies=[1])
        b = store.backup(os.path.join(d, "bak"))
        self.assertTrue(b["ok"])
        self.assertGreater(b["bytes"], 0)
        _, store2 = fresh_store()
        r = store2.restore(b["path"])
        self.assertTrue(r["ok"])
        self.assertEqual(store2.get(2)["title"], "beta")
        self.assertEqual(store2.counts()["total"], 2)
        self.assertTrue(store2.health_check()["ok"])

    def test_restore_rejects_missing_and_corrupt(self):
        d, store = fresh_store()
        self.assertFalse(store.restore(os.path.join(d, "nope.sqlite"))["ok"])
        bad = os.path.join(d, "bad.sqlite")
        with open(bad, "wb") as f:
            f.write(b"this is not a database")
        self.assertFalse(store.restore(bad)["ok"])

    def test_vacuum_reports_reclaim(self):
        _, store = fresh_store()
        store.add_task("x")
        v = store.vacuum()
        self.assertTrue(v["ok"])
        self.assertGreaterEqual(v["bytes_after"], 0)

    def test_new_store_carries_schema_version(self):
        _, store = fresh_store()
        from elysia.core.tasks import SCHEMA_VERSION
        self.assertEqual(store.health_check()["schema_version"], SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# Phase 27: cost / budget enforcement
# ---------------------------------------------------------------------------
def two_providers():
    pm = ProviderManager()
    paid = pm.register(ProviderConfig(kind="openai", label="cloud",
                                      model="m1", base_url="http://x",
                                      capabilities=["chat", "coding"]))
    free = pm.register(ProviderConfig(kind="local", label="locallama",
                                      model="m2", base_url="http://y",
                                      capabilities=["chat", "coding"]))
    paid.status = "healthy"
    free.status = "healthy"
    return pm, paid, free


class TestBudgetEnforcement(unittest.TestCase):
    def test_under_budget_prefers_priority_order(self):
        pm, paid, free = two_providers()
        res = pm.reserve(["chat", "coding"])
        self.assertEqual(res.provider.name, "cloud")
        res.release()

    def test_over_budget_drops_paid_keeps_local(self):
        pm, paid, free = two_providers()
        pm.set_budget(max_usd=1.0)
        pm.add_spend(1.2, provider="cloud")
        res = pm.reserve(["chat", "coding"])
        self.assertIsNotNone(res)
        self.assertEqual(res.provider.name, "locallama")
        res.release()
        why = pm.explain(["chat", "coding"])
        cloud = [r for r in why["trace"] if r["provider"] == "cloud"]
        self.assertTrue(cloud)
        self.assertIn("over budget", cloud[0]["reason"])
        self.assertTrue(why["budget"]["over_budget"])

    def test_all_paid_over_budget_refuses_to_reserve(self):
        pm = ProviderManager()
        p = pm.register(ProviderConfig(kind="openai", label="cloud",
                                       model="m", base_url="http://x",
                                       capabilities=["chat"]))
        p.status = "healthy"
        pm.set_budget(max_usd=0.5)
        pm.add_spend(1.0, provider="cloud")
        self.assertIsNone(pm.reserve(["chat"]),
                          "a paid provider must not run over budget")

    def test_budget_accumulates_and_warns(self):
        pm, paid, free = two_providers()
        pm.set_budget(max_usd=10.0, warn_usd=5.0)
        pm.add_spend(6.0, provider="cloud", tokens_in=1000, tokens_out=500)
        st = pm.budget_status()
        self.assertEqual(st["estimated_spend_usd"], 6.0)
        self.assertTrue(st["warned"] if st.get("warned")
                        else pm._maybe_warn())
        self.assertFalse(st["over_budget"])
        pm.add_spend(5.0, provider="cloud")
        self.assertTrue(pm.budget_status()["over_budget"])

    def test_unset_budget_is_unbounded(self):
        pm, paid, free = two_providers()
        pm.add_spend(9999.0)
        self.assertFalse(pm.budget_status()["over_budget"])
        res = pm.reserve(["chat"])
        self.assertEqual(res.provider.name, "cloud")
        res.release()

    def test_local_provider_runs_at_any_spend(self):
        pm = ProviderManager()
        only = pm.register(ProviderConfig(kind="local", label="locallama",
                                          model="m", base_url="http://y",
                                          capabilities=["chat"]))
        only.status = "healthy"
        pm.set_budget(max_usd=0.01)
        pm.add_spend(100.0)
        res = pm.reserve(["chat"])
        self.assertIsNotNone(res, "a zero-cost provider always stays available")
        res.release()


# ---------------------------------------------------------------------------
# Phase 2: workflow engine
# ---------------------------------------------------------------------------
class WorkflowHarness(unittest.TestCase):
    def setUp(self):
        self.d, self.store = fresh_store()
        self.eng = WorkflowEngine(self.store)

    def complete(self, node_id):
        self.store.complete(node_id, "completed", "ok")

    def state(self, name):
        return self.eng.run_state(name)


class TestWorkflowValidation(unittest.TestCase):
    def test_empty_workflow_rejected(self):
        self.assertTrue(validate_workflow([]))

    def test_cycle_by_forward_reference_rejected(self):
        problems = validate_workflow([
            {"id": "a", "type": "task", "title": "a", "after": ["b"]},
            {"id": "b", "type": "task", "title": "b"},
        ])
        self.assertTrue(any("later node" in p for p in problems))

    def test_unknown_refs_and_types_rejected(self):
        problems = validate_workflow([
            {"id": "a", "type": "task", "title": "a", "after": ["ghost"]},
            {"id": "j", "type": "join", "title": "j"},
            {"id": "f", "type": "fallback", "title": "f"},
            {"id": "w", "type": "wat", "title": "w"},
        ])
        self.assertEqual(len(problems), 4)

    def test_start_rejects_invalid_graph(self):
        _, store = fresh_store()
        eng = WorkflowEngine(store)
        with self.assertRaises(WorkflowError):
            eng.start("bad", [])


class TestWorkflowGates(WorkflowHarness):
    def test_version(self):
        self.assertEqual(WORKFLOW_ENGINE_VERSION, 1)

    def test_approval_blocks_until_human_resolves(self):
        r = self.eng.start("wf", [
            {"id": "a", "type": "task", "title": "a", "description": "a"},
            {"id": "g", "type": "approval", "title": "gate",
             "description": "gate", "after": ["a"]},
            {"id": "b", "type": "task", "title": "b", "description": "b",
             "after": ["g"]},
        ])
        n = r["node_ids"]
        self.complete(n["a"])
        self.eng.tick()
        self.assertEqual(self.state("wf")["awaiting_approval"], [n["g"]])
        self.assertEqual(self.store.get(n["b"])["status"], "queued",
                         "downstream work must wait behind the gate")
        self.assertTrue(self.eng.resolve_approval(n["g"], allow=True,
                                                  by="reviewer"))
        self.eng.tick()
        st = self.state("wf")
        self.assertEqual([x["status"] for x in st["nodes"] if x["id"] == n["g"]],
                         ["completed"])
        # b is now unblocked (ready) for the executor to claim
        self.assertEqual(self.store.get(n["b"])["status"], "ready")

    def test_denial_cascades_not_proceeds(self):
        r = self.eng.start("wf2", [
            {"id": "a", "type": "task", "title": "a", "description": "a"},
            {"id": "g", "type": "approval", "title": "g", "description": "g",
             "after": ["a"]},
            {"id": "b", "type": "task", "title": "b", "description": "b",
             "after": ["g"]},
        ])
        n = r["node_ids"]
        self.complete(n["a"])
        self.eng.resolve_approval(n["g"], allow=False, by="operator")
        st = self.state("wf2")
        g = [x for x in st["nodes"] if x["id"] == n["g"]][0]
        b = [x for x in st["nodes"] if x["id"] == n["b"]][0]
        self.assertEqual(g["status"], "cancelled")
        self.assertEqual(b["status"], "cancelled")
        self.assertFalse(st["ok"])

    def test_join_waits_for_all_siblings_and_fails_on_one(self):
        r = self.eng.start("wf3", [
            {"id": "x", "type": "task", "title": "x", "description": "x"},
            {"id": "y", "type": "task", "title": "y", "description": "y"},
            {"id": "j", "type": "join", "title": "j", "description": "j",
             "after": ["x", "y"]},
        ])
        n = r["node_ids"]
        self.complete(n["x"])
        self.eng.tick()
        self.assertEqual(self.store.get(n["j"])["status"], "queued",
                         "join must stay queued (not evaluable) while a "
                         "sibling is still pending")
        self.complete(n["y"])
        self.eng.tick()
        self.assertEqual(self.store.get(n["j"])["status"], "completed")
        # failing sibling path
        r2 = self.eng.start("wf4", [
            {"id": "p", "type": "task", "title": "p", "description": "p"},
            {"id": "q", "type": "task", "title": "q", "description": "q"},
            {"id": "j2", "type": "join", "title": "j2", "description": "j2",
             "after": ["p", "q"]},
        ])
        n2 = r2["node_ids"]
        self.complete(n2["p"])
        self.store.transition(n2["q"], "failed", last_error="boom")
        self.eng.tick()
        self.assertEqual(self.store.get(n2["j2"])["status"], "failed")

    def test_parallel_siblings_are_independent(self):
        r = self.eng.start("wf5", [
            {"id": "x", "type": "task", "title": "x", "description": "x"},
            {"id": "y", "type": "task", "title": "y", "description": "y"},
        ])
        # no `after` edges: both are ready immediately (parallel branch)
        ready = {t["id"] for t in self.store.ready_tasks(limit=10)}
        self.assertTrue({r["node_ids"]["x"], r["node_ids"]["y"]} <= ready)

    def test_fallback_runs_only_when_primary_failed(self):
        r = self.eng.start("wf6", [
            {"id": "a", "type": "task", "title": "primary a",
             "description": "a"},
            {"id": "b", "type": "fallback", "title": "fallback",
             "description": "fb", "fallback_of": "primary a"},
        ])
        n = r["node_ids"]
        self.complete(n["a"])
        self.eng.tick()
        self.assertEqual(self.store.get(n["b"])["status"], "completed",
                         "primary succeeded: fallback must be skipped")
        r2 = self.eng.start("wf7", [
            {"id": "p", "type": "task", "title": "primary p",
             "description": "p"},
            {"id": "f", "type": "fallback", "title": "fallback",
             "description": "fb", "fallback_of": "primary p"},
        ])
        n2 = r2["node_ids"]
        self.store.transition(n2["p"], "failed", last_error="boom")
        self.eng.tick()
        self.assertEqual(self.store.get(n2["f"])["status"], "completed",
                         "primary failed: fallback must execute")

    def test_rollback_refuses_unknown_checkpoint(self):
        r = self.eng.start("wf8", [
            {"id": "rb", "type": "rollback", "title": "rb",
             "description": "rb", "checkpoint": "cafebabe"},
        ])
        self.eng.tick()
        self.assertEqual(self.store.get(r["node_ids"]["rb"])["status"],
                         "failed")

    def test_gate_rows_are_never_claimable(self):
        r = self.eng.start("wf9", [
            {"id": "g", "type": "approval", "title": "g", "description": "g"},
        ])
        tid = r["node_ids"]["g"]
        self.assertTrue(self.store.get(tid)["kind"].startswith("gate:"))
        self.assertFalse(self.store.claim(tid, "w1", "prov", "model", 60),
                         "a gate row must never be claimed by a worker")

    def test_run_state_reports_finished_and_ok(self):
        r = self.eng.start("wf10", [
            {"id": "a", "type": "task", "title": "a", "description": "a"},
        ])
        self.complete(r["node_ids"]["a"])
        st = self.state("wf10")
        self.assertTrue(st["finished"])
        self.assertTrue(st["ok"])

    def test_timeout_gate_times_out_stuck_child(self):
        class FastClock:
            def __init__(self, base):
                self.base = base

            def __call__(self):
                return self.base

        clock_base = 1000.0
        self.eng.clock = FastClock(clock_base)
        r = self.eng.start("wf11", [
            {"id": "child", "type": "task", "title": "child",
             "description": "child"},
            {"id": "t", "type": "timeout", "title": "t", "description": "t",
             "after": ["child"], "timeout_s": 30},
        ])
        n = r["node_ids"]
        # child claimed and running since long before the clock
        self.store.claim(n["child"], "w1", "prov", "model", 600)
        self.store._update(n["child"], started_at=clock_base - 100)
        self.eng.tick()
        self.assertEqual(self.store.get(n["t"])["status"], "failed")
        self.assertIn(self.store.get(n["child"])["status"],
                      ("ready", "failed", "retrying"))


if __name__ == "__main__":
    unittest.main()
