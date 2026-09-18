"""Layered memory (Phase 9), context planner (Phase 10), self-healing (Phase 21).

Real subsystems, no mocks: a real on-disk MemoryStore, a real SQLite TaskStore,
a real AgentPipeline driven by a scripted provider transport, and the real
Healer performing its recoveries against those real objects.

Proves:
  memory      importance/confidence/provenance are stored; identical content is
              deduplicated; retrieval is scored and counts recalls; TTL expiry;
              invalidation and correction keep an audit trail; compaction really
              compresses (summary record) instead of silently destroying;
              backup/restore round-trips and refuses a corrupt file
  context     the token budget is honoured, priorities decide order, truncation
              keeps the recent TAIL, every dropped layer is reported with a
              reason, the plan is cached until its inputs change, and roles get
              different priorities
  healing     every program failure class classifies from real evidence; retries
              are bounded per class (no infinite loop); backoff grows and is
              deterministic under jitter; recovery routines actually run and
              report honestly when they cannot; dangerous failures escalate
              instead of being auto-"fixed"; failures are recorded in memory
  live path   the pipeline's implementer prompt really carries the task, the
              files it owns, the classified previous failure and recalled
              memory; a QA failure lands in failure memory; a success lands in
              solution memory; a task.healing event is emitted
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.agents import AgentPipeline
from elysia.core.config import Config, ProviderConfig
from elysia.core.context import ContextPlanner, ROLE_CONTEXT_PRIORITY
from elysia.core.events import EventBus
from elysia.core.healing import (GIVE_UP, MAX_BACKOFF_S, POLICIES, Healer,
                                 classify, describe_policies)
from elysia.core.memory import Memory, MemoryStore, content_hash
from elysia.core.providers import ProviderManager
from elysia.core.resources import ResourceManager
from elysia.core.tasks import TaskStore
from elysia.core.workspace import Workspace


class _NoPressure(ResourceManager):
    def memory_pressure(self):
        return False


class RecordingBackend:
    """Scripted transport: returns whatever the test queued, records prompts."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []
        self.system_messages = []

    def __call__(self, messages, max_tokens=None, temperature=None, timeout=None):
        self.prompts.append(messages[-1].get("content", "") if messages else "")
        self.system_messages.append(messages[0].get("content", "")
                                    if messages else "")
        if not self.replies:
            return "```py out.py\nx = 1\n```\n", ""
        nxt = self.replies.pop(0)
        if isinstance(nxt, tuple):
            return nxt
        return nxt, ""


def fake_provider(pm, backend, label="p0", capabilities=None):
    p = pm.register(ProviderConfig(
        kind="openai", label=label, model=f"m-{label}",
        capabilities=capabilities or ["chat", "coding", "reasoning"],
        concurrency=2))
    p._chat_openai = backend
    p.status = "healthy"
    p.check_health = lambda: "healthy"
    return p


# ===========================================================================
# Phase 9 — memory
# ===========================================================================
class TestLayeredMemory(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.m = Memory(self.dir)

    def test_metadata_dedup_and_scored_recall(self):
        m = self.m
        task = {"id": 7, "title": "add subtract helper",
                "agent_role": "implementer"}
        cls = {"kind": "provider_timeout", "action": "failover",
               "severity_score": 0.6}
        first = m.remember_failure(task, cls, "provider timed out after 30s")
        second = m.remember_failure(task, cls, "provider timed out after 30s")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"], "identical content must dedup")
        self.assertEqual(second["key"], first["key"])
        self.assertEqual(m.stats()["namespaces"], {"failure": 1})

        rec = m.store.record("failure", first["key"])
        self.assertEqual(rec["kind"], "failure")
        self.assertIn("provider_timeout", rec["tags"])
        self.assertGreater(rec["importance"], 0.5)
        self.assertEqual(rec["provenance"], "task:7")
        self.assertEqual(rec["confidence"], 0.7)
        self.assertEqual(rec["hash"], content_hash(
            m.store.get("failure", first["key"])))

        hits = m.recall("subtract provider timeout")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["namespace"], "failure")
        self.assertIn("keyword=", hits[0]["why"])
        # recall is counted, so a useful memory ranks higher over time
        self.assertEqual(m.store.record("failure", first["key"])["recalls"], 1)

    def test_scoring_prefers_important_recent_relevant(self):
        m = self.m
        m.store.set("project", "low", "alpha beta gamma", importance=0.2)
        m.store.set("project", "high", "alpha beta gamma", importance=0.95)
        hits = m.store.search("alpha beta gamma", ns="project", limit=2)
        self.assertEqual(hits[0]["key"], "high")
        self.assertGreater(hits[0]["score"], hits[1]["score"])

    def test_ttl_expiry_and_forget(self):
        m = self.m
        m.store.set("session", "short", {"x": 1}, ttl=-1)
        self.assertIsNone(m.store.get("session", "short"))
        m.store.set("session", "live", {"x": 2}, ttl=3600)
        self.assertEqual(m.store.get("session", "live"), {"x": 2})
        self.assertTrue(m.forget("session", "live"))
        self.assertFalse(m.forget("session", "live"))

    def test_invalidate_and_correct_keep_an_audit_trail(self):
        m = self.m
        m.store.set("decision", "d1", "use sqlite", importance=0.8)
        self.assertTrue(m.invalidate("decision", "d1", "superseded by postgres"))
        rec = m.store.record("decision", "d1")
        self.assertTrue(rec["invalidated"])
        self.assertEqual(rec["confidence"], 0.0)
        self.assertEqual(rec["invalid_reason"], "superseded by postgres")

        self.assertTrue(m.correct("decision", "d1", "use postgres",
                                  reason="scaling"))
        rec = m.store.record("decision", "d1")
        self.assertEqual(rec["value"], "use postgres")
        self.assertNotIn("invalidated", rec)
        self.assertEqual(rec["corrections"][0]["old"], "use sqlite")
        self.assertGreaterEqual(rec["confidence"], 0.8)

    def test_compaction_compresses_instead_of_destroying(self):
        # a large cap so the per-write auto-compaction does not fire first
        store = MemoryStore(tempfile.mkdtemp(), max_entries=1000)
        for i in range(12):
            store.set("history", f"e{i}", f"event {i}", importance=0.1 + i / 100)
        store.set("history", "expired", "gone", ttl=-1)
        report = store.compact(keep_per_ns=4)
        self.assertGreaterEqual(report["expired_removed"], 1)
        self.assertEqual(report["compressed"], 8)
        self.assertIn("history", report["summaries"])
        # the compressed record keeps the keys it replaced
        self.assertEqual(len(report["summaries"]["history"]["keys"]), 8)
        summary = store.get("project", "memory_summary")
        self.assertIn("history", summary)
        # the highest-importance records survived verbatim
        self.assertIsNotNone(store.get("history", "e11"))

    def test_backup_restore_round_trip_and_corrupt_refusal(self):
        m = self.m
        m.remember_decision("ship it", "tests pass")
        m.remember_solution({"id": 1, "title": "t"}, "wrote a.py", ["a.py"])
        path = os.path.join(self.dir, "bk.json")
        out = m.store.backup(path)
        self.assertTrue(out["ok"])
        fresh = Memory(tempfile.mkdtemp())
        back = fresh.store.restore(path)
        self.assertTrue(back["ok"])
        self.assertEqual(back["restored"], 2)
        self.assertTrue(fresh.store.search("ship it"))

        bad = os.path.join(self.dir, "corrupt.json")
        with open(bad, "w") as f:
            f.write("{not json")
        refused = fresh.store.restore(bad)
        self.assertFalse(refused["ok"])
        self.assertIn("unreadable", refused["error"])
        missing = fresh.store.restore(os.path.join(self.dir, "nope.json"))
        self.assertFalse(missing["ok"])

    def test_timeline_reports_provenance(self):
        m = self.m
        m.remember_decision("a", "because", actor="agent:planner")
        rows = m.timeline(limit=3)
        self.assertEqual(rows[0]["namespace"], "decision")
        self.assertEqual(rows[0]["provenance"], "agent:planner")


# ===========================================================================
# Phase 10 — context planner
# ===========================================================================
class TestContextPlanner(unittest.TestCase):
    def test_budget_is_honoured_and_layers_are_prioritised(self):
        p = ContextPlanner(budget_tokens=200, role="implementer")
        p.add("system", "S" * 400, required=True)
        p.add("provider", "P" * 4000)      # lowest priority, must be dropped
        p.add("task", "T" * 300)
        plan = p.plan()
        self.assertLessEqual(plan["report"]["used_chars"],
                             plan["report"]["budget_tokens"] * 4 + 60)
        included = [l["layer"] for l in plan["report"]["layers"]]
        self.assertEqual(included[:2], ["system", "task"])
        dropped = {d["layer"]: d["reason"] for d in plan["report"]["dropped"]}
        self.assertIn("provider", dropped)
        self.assertIn("budget", dropped["provider"])
        self.assertIn("## task", plan["prompt"])

    def test_truncation_keeps_the_tail_and_says_so(self):
        p = ContextPlanner(budget_tokens=300)
        original = "OLD-" * 300 + "NEWEST-END"
        p.add("task", original)
        plan = p.plan()
        layer = plan["report"]["layers"][0]
        self.assertTrue(layer["truncated"])
        # the reported omission is exactly what was cut: omitted + kept == all
        notice_end = plan["prompt"].index("]\n") + 2
        kept = plan["prompt"][notice_end:]
        self.assertEqual(len(original) - layer["omitted_chars"], len(kept))
        self.assertGreater(layer["omitted_chars"], 0)
        self.assertIn("NEWEST-END", plan["prompt"])
        self.assertIn("chars omitted", plan["prompt"])
        # the head really was cut: the kept slice is shorter than the input
        self.assertLess(len(kept), len(original))

    def test_plan_is_cached_until_its_inputs_change(self):
        p = ContextPlanner(budget_tokens=500)
        p.add("task", "hello")
        first = p.plan(cache_key="k")
        self.assertFalse(first["cached"])
        self.assertTrue(p.plan(cache_key="k")["cached"])
        p.add("tests", "rc=1")
        third = p.plan(cache_key="k")
        self.assertFalse(third["cached"])
        self.assertIn("rc=1", third["prompt"])
        p.invalidate("tests")
        self.assertNotIn("rc=1", p.plan()["prompt"])

    def test_roles_have_different_priorities(self):
        impl = ContextPlanner(role="implementer")
        rev = ContextPlanner(role="code_reviewer")
        self.assertGreater(impl.priority["failures"], impl.priority["provider"])
        self.assertGreater(rev.priority["diff"], rev.priority["memory"])
        self.assertIn("implementer", ROLE_CONTEXT_PRIORITY)

    def test_explain_makes_no_prompt_and_reports_provenance(self):
        p = ContextPlanner(budget_tokens=100)
        p.add("task", "x" * 10, source="memory.recall")
        rep = p.explain()
        self.assertEqual(rep["layers"][0]["source"], "memory.recall")
        self.assertIn("fingerprint", rep)

    def test_layer_builders(self):
        self.assertIn("owned files", ContextPlanner.task_layer(
            {"title": "t", "owned_files": ["a.py"], "attempts": 2}))
        self.assertIn("provider_timeout", ContextPlanner.failure_layer(
            [], {"kind": "provider_timeout", "retryable": True,
                 "action": "failover", "hint": "retry shorter"}))
        self.assertIn("### a.py", ContextPlanner.file_layer({"a.py": "x = 1\n"}))
        self.assertIn("rc=1", ContextPlanner.test_layer({"rc": 1, "tail": "rc=1"}))
        self.assertIn("selected provider", ContextPlanner.provider_layer(
            {"selected": "p0", "rejected": [{"name": "p1", "reason": "full"}]}))


# ===========================================================================
# Phase 21 — self-healing
# ===========================================================================
class TestFailureClassification(unittest.TestCase):
    CASES = [
        ("provider timed out after 30s", "provider_timeout"),
        ("HTTP 429 Too Many Requests", "provider_rate_limit"),
        ("http 500 internal server error", "provider_http_error"),
        ("no usable provider answered", "provider_unavailable"),
        ("401 unauthorized: bad api key", "provider_auth"),
        ("spend budget exhausted", "provider_budget"),
        ("connection refused", "network_error"),
        ("sqlite3.OperationalError: database is locked", "sqlite_busy"),
        ("lease expired; released", "stale_lease"),
        ("worker crashed during call", "worker_crash"),
        ("executor died", "executor_crash"),
        ("no space left on device", "disk_pressure"),
        ("Cannot allocate memory", "memory_pressure"),
        ("QA failed: a.py: syntax error", "qa_failure"),
        ("tests (python): rc=1", "test_failure"),
        ("go build failed", "build_failure"),
        ("BLOCKER: a.py:1: unsafe", "review_blocker"),
        ("../escaped.py: not in owned files", "path_outside_workspace"),
        ("tool fs.write refused: denied", "tool_denied"),
        ("permission denied: /etc/shadow", "permission_denied"),
        ("merge conflict in a.py", "git_conflict"),
        ("could not parse model output", "malformed_model_output"),
        ("npm ERR! dependency resolution failed", "dependency_failure"),
    ]

    def test_every_program_failure_class_is_detected(self):
        for message, expected in self.CASES:
            with self.subTest(message=message):
                got = classify(message)
                self.assertEqual(got["kind"], expected)
                self.assertTrue(got["evidence"],
                                "a classification must carry its evidence")

    def test_exception_types_classify(self):
        self.assertEqual(classify(TimeoutError("x"))["kind"], "provider_timeout")
        self.assertEqual(classify(PermissionError("x"))["kind"],
                         "permission_denied")
        self.assertEqual(classify(FileNotFoundError("x"))["kind"],
                         "filesystem_error")

    def test_retries_are_bounded_per_class(self):
        for kind in ("provider_timeout", "qa_failure", "test_failure",
                     "sqlite_busy", "malformed_model_output"):
            cap = POLICIES[kind].max_retries
            last = classify("bogus", attempt=cap + 1,
                            task_id=1, max_retries=None)
            # a message that classifies as the kind under test
            sample = {"provider_timeout": "timed out", "qa_failure": "QA failed",
                      "test_failure": "tests (python): rc=1",
                      "sqlite_busy": "database is locked",
                      "malformed_model_output": "could not parse output"}[kind]
            stopped = classify(sample, attempt=cap + 1)
            self.assertEqual(stopped["kind"], kind)
            self.assertFalse(stopped["retryable"], kind)
            self.assertEqual(stopped["action"], GIVE_UP, kind)
            self.assertEqual(stopped["backoff_s"], 0.0)
            self.assertIsNotNone(last)

    def test_backoff_grows_and_is_deterministic_under_jitter(self):
        a1 = classify("timed out", attempt=1, task_id=42)
        a2 = classify("timed out", attempt=2, task_id=42)
        a3 = classify("timed out", attempt=3, task_id=42)
        self.assertLess(a1["backoff_s"], a2["backoff_s"])
        self.assertLess(a2["backoff_s"], a3["backoff_s"])
        self.assertEqual(a2["backoff_s"],
                         classify("timed out", attempt=2, task_id=42)["backoff_s"])
        self.assertNotEqual(a2["backoff_s"],
                            classify("timed out", attempt=2, task_id=43)["backoff_s"])
        self.assertLessEqual(a3["backoff_s"], MAX_BACKOFF_S * 1.2)

    def test_dangerous_failures_are_not_retried(self):
        for message in ("merge conflict in a.py", "permission denied",
                        "401 unauthorized", "tool fs.write refused: denied"):
            got = classify(message)
            self.assertFalse(got["retryable"], message)
            self.assertIn(got["action"], ("escalate", "replan"))
            self.assertEqual(got["backoff_s"], 0.0)

    def test_policy_table_is_describable(self):
        rows = describe_policies()
        self.assertEqual(len(rows), len(POLICIES))
        self.assertTrue(all({"kind", "action", "retryable"} <= set(r)
                            for r in rows))


class TestHealerRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = TaskStore(os.path.join(self.tmp, "board.sqlite"))
        self.memory = Memory(os.path.join(self.tmp, "mem"))
        self.events = EventBus()
        self.healer = Healer(store=self.store, memory=self.memory,
                             events=self.events)

    def test_stale_lease_recovery_really_releases_it(self):
        tid = self.store.add_task("t", "d", owned_files=["a.py"])
        self.store.mark_ready(tid)
        self.store.claim(tid, "w1", "p0", "m", lease_seconds=60)
        # simulate a crashed worker: expire the lease
        self.store._update(tid, lease_expires_at=time.time() - 5)
        out = self.healer.handle("lease expired; released",
                                 {"id": tid, "attempts": 1})
        self.assertEqual(out["kind"], "stale_lease")
        self.assertTrue(out["recovery_result"]["performed"], out)
        self.assertEqual(out["recovery_result"]["routine"], "release_lease")
        self.assertEqual(self.store.get(tid)["status"], "ready")
        self.assertIsNone(self.store.get(tid)["worker"])
        self.assertIs(out["verified"], True)

    def test_disk_pressure_recovery_reclaims_runtime_space(self):
        self.memory.store.set("history", "expired", "x", ttl=-1)
        out = self.healer.handle("no space left on device", {"id": 1})
        self.assertEqual(out["kind"], "disk_pressure")
        self.assertTrue(out["recovery_result"]["performed"])
        self.assertIn("memory expired=", out["recovery_result"]["detail"])

    def test_sqlite_busy_recovery_rechecks_the_store(self):
        out = self.healer.handle("database is locked", {"id": 1})
        self.assertTrue(out["recovery_result"]["performed"])
        self.assertEqual(out["recovery_result"]["routine"], "recheck_store")
        self.assertIn("integrity", out["recovery_result"]["detail"])

    def test_recovery_reports_honestly_when_it_cannot_run(self):
        bare = Healer()          # nothing attached
        out = bare.handle("lease expired; released", {"id": 1})
        self.assertFalse(out["recovery_result"]["performed"])
        self.assertIn("no task store", out["recovery_result"]["detail"])
        self.assertIsNone(out["verified"])

    def test_no_recovery_for_a_class_that_has_none(self):
        out = self.healer.handle("could not parse model output", {"id": 1})
        self.assertFalse(out["recovery_result"]["performed"])
        self.assertIn("no recovery routine", out["recovery_result"]["detail"])

    def test_git_conflict_escalates_and_touches_nothing(self):
        tid = self.store.add_task("t", "d", owned_files=["a.py"])
        self.store.mark_ready(tid)
        self.store.claim(tid, "w1", None, None, lease_seconds=60)
        out = self.healer.handle("merge conflict in a.py", {"id": tid})
        self.assertEqual(out["action"], "escalate")
        self.assertFalse(out["recovery_result"]["performed"])
        # the runtime must NOT have guessed a resolution or moved the task
        self.assertEqual(self.store.get(tid)["status"], "claimed")
        self.assertIsNone(self.store.get(tid)["last_error"])

    def test_failure_is_recorded_in_memory_with_its_classification(self):
        out = self.healer.handle("timed out", {"id": 4, "title": "add subtract",
                                               "agent_role": "implementer"})
        self.assertTrue(out["recorded"])
        hits = self.memory.recall("add subtract timed out")
        self.assertTrue(hits)
        tags = [t for h in hits for t in (h["tags"] or [])]
        self.assertIn("provider_timeout", tags)
        self.assertIn("role:implementer", tags)

    def test_healing_event_is_emitted(self):
        self.healer.handle("timed out", {"id": 5})
        rows = self.events.recent(50, event_type="task.healing")
        self.assertTrue(rows)
        self.assertEqual(rows[-1]["task_id"], 5)

    def test_report_lists_terminal_and_auto_recovered_classes(self):
        rep = self.healer.report()
        self.assertGreater(rep["classes"], 20)
        self.assertIn("git_conflict", rep["terminal"])
        self.assertTrue(rep["auto_recovered"])


# ===========================================================================
# live pipeline integration
# ===========================================================================
BAD_PY = "def broken(:\n    pass\n"
GOOD_PY = "def add(a, b):\n    return a + b\n"


class TestPipelineUsesMemoryContextAndHealing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws_root = os.path.join(self.tmp, "ws")
        os.makedirs(self.ws_root)
        self.store = TaskStore(os.path.join(self.tmp, "board.sqlite"))
        self.memory = Memory(os.path.join(self.tmp, "mem"))
        self.events = EventBus()
        self.pm = ProviderManager()
        self.backend = RecordingBackend(
            [f"```py calc.py\n{BAD_PY}```\n",       # attempt 1: fails QA
             f"```py calc.py\n{GOOD_PY}```\n"])     # attempt 2: succeeds
        fake_provider(self.pm, self.backend)
        self.pipeline = AgentPipeline(
            self.pm, self.store, resources=_NoPressure(), events=self.events,
            cfg=Config(), memory=self.memory, tools=None)
        self.ws = Workspace(self.ws_root)

    def _task(self, title="write calc.py"):
        tid = self.store.add_task(title, "create calc.py with add()",
                                 owned_files=["calc.py"])
        self.store.mark_ready(tid)
        self.assertTrue(self.store.claim(tid, "w1", None, None, 60))
        return self.store.get(tid)

    def test_failure_classified_recorded_and_hint_reaches_the_next_prompt(self):
        task = self._task()
        out = self.pipeline.solve_task(task, self.ws_root)
        self.assertFalse(out["ok"])
        self.assertIn("QA failed", out["error"])

        stored = self.store.get(task["id"])
        self.assertIn("qa_failure", stored["last_error"])
        self.assertIn("healing:", stored["last_error"])
        self.assertIn(stored["status"], ("ready", "failed"))

        healing = self.events.recent(50, event_type="task.healing")
        self.assertTrue(healing)
        self.assertEqual(healing[-1]["task_id"], task["id"])

        hits = self.memory.recall("calc.py created with add")
        self.assertTrue(hits, "the failure must be remembered")

        # second attempt: the prompt now carries the classified failure and
        # the hint telling the agent what to do differently
        self.store._update(task["id"], backoff_until=time.time() - 1,
                           worker=None, lease_expires_at=None)
        self.store.transition(task["id"], "ready")
        self.assertTrue(self.store.claim(task["id"], "w1", None, None, 60))
        task2 = self.store.get(task["id"])
        out2 = self.pipeline.solve_task(task2, self.ws_root)
        self.assertTrue(out2["ok"], out2)
        prompt = self.backend.prompts[-1]
        self.assertIn("## failures", prompt)
        self.assertIn("qa_failure", prompt)
        self.assertIn("DO THIS DIFFERENTLY", prompt)
        self.assertIn("calc.py", prompt)
        # the context report is real and bounded
        self.assertLessEqual(out2["context"]["used_tokens_est"],
                             self.pipeline.IMPLEMENTER_BUDGET_TOKENS)
        with open(os.path.join(self.ws_root, "calc.py")) as f:
            self.assertIn("def add", f.read())

    def test_success_is_remembered_as_a_solution(self):
        tid = self.store.add_task("write good.py", "create good.py",
                                  owned_files=["good.py"])
        self.store.mark_ready(tid)
        self.assertTrue(self.store.claim(tid, "w1", None, None, 60))
        self.backend.replies = ["```py good.py\nx = 1\n```\n"]
        out = self.pipeline.solve_task(self.store.get(tid), self.ws_root)
        self.assertTrue(out["ok"], out)
        hits = self.memory.store.search("good.py", ns="solution")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["tags"][0], "solution")
        self.assertIn("file:good.py", hits[0]["tags"])
        # the memory KIND must be stored, not just used in the key
        self.assertEqual(hits[0]["kind"], "solution")
        # task memory keeps the test/context report for later retrieval
        rec = self.memory.store.record("task", f"task_{tid}")
        self.assertIsNotNone(rec)
        self.assertIn("context_report", rec["value"])

    def test_empty_model_output_is_a_failure_not_a_silent_success(self):
        tid = self.store.add_task("write nothing.py", "create nothing.py",
                                  owned_files=["nothing.py"])
        self.store.mark_ready(tid)
        self.assertTrue(self.store.claim(tid, "w1", None, None, 60))
        self.backend.replies = ["I could not do that.", ""]
        out = self.pipeline.solve_task(self.store.get(tid), self.ws_root)
        self.assertFalse(out["ok"])
        self.assertIn("no file blocks", out["error"])
        self.assertFalse(os.path.exists(os.path.join(self.ws_root,
                                                    "nothing.py")))
        self.assertIn("malformed_model_output",
                      self.store.get(tid)["last_error"])

    def test_pipeline_shares_one_healer_and_memory(self):
        self.assertIs(self.pipeline.healer.memory, self.pipeline.memory)
        self.assertIs(self.pipeline.healer.store, self.store)


class TestMemoryHealthDimension(unittest.TestCase):
    """The health dimension must agree with the store (no phantom memory)."""

    def test_memory_dimension_uses_the_canonical_store(self):
        from elysia.core.health import dimensions
        state = tempfile.mkdtemp()
        m = Memory(os.path.join(state, "memory"))
        m.remember_decision("ship it", "tests pass")
        m.remember_failure({"id": 1, "title": "t"},
                           {"kind": "qa_failure", "action": "retry",
                            "severity_score": 0.5}, "boom")
        dim = dimensions(memory_dir=os.path.join(state, "memory"))["memory"]
        self.assertEqual(dim["status"], "ok", dim)
        self.assertEqual(dim["metrics"]["entries"], 2)
        self.assertEqual(dim["metrics"]["namespaces"], 2)
        # the dedup index is not data
        self.assertNotIn("_", "".join(dim["metrics"]["namespaces_detail"]))

    def test_memory_dimension_is_honest_when_empty_or_missing(self):
        from elysia.core.health import dimensions
        empty = tempfile.mkdtemp()
        dim = dimensions(memory_dir=empty)["memory"]
        self.assertEqual(dim["status"], "warn")
        self.assertIn("empty", dim["detail"])
        missing = dimensions(memory_dir=os.path.join(empty, "nope"))["memory"]
        self.assertEqual(missing["status"], "warn")
        self.assertIn("not created yet", missing["detail"])
        # a genuinely unconfigured store (no dir at all) is "unknown", not "ok"
        from elysia.core.health import _memory
        self.assertEqual(_memory(None)["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
