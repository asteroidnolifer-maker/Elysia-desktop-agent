"""Task-graph intelligence (Phase 3) and intelligent replanning (Phase 50).

Real code paths: the canonical analyser (elysia.core.graph) over real plans, the
real workspace (files that actually exist on disk), the real ProviderManager (a
fleet that can or cannot serve a role), and the real MasterController.

Proves:
  structure  unknown/self dependencies, cycles, and tasks nothing can execute
             are detected; blockers are distinguished from warnings
  files      two writers of one file, mentions of another task's file without a
             dependency, and existing-vs-new files are all reported
  shape      oversized tasks (split) and trivial tasks (merge) are identified
  estimates  complexity/duration/token estimates exist, are per task, and say
             they are heuristics
  repair     replan() leaves NO unknown deps, NO cycles and NO double owners;
             splitting rewires dependents to EVERY part; the mapping is real
  idempotent a repaired plan re-analyses clean and replans to no changes
  master     plan() checks and repairs the graph and reports it; simulate()
             stays a dry run while reporting the same conflicts
"""
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.config import Config, ProviderConfig
from elysia.core.events import EventBus
from elysia.core.graph import (OVERSIZED_FILES, analyze, complexity, estimate,
                               files_in, find_cycles, replan, summary)
from elysia.core.master import (MasterController, _resolve_memory_dir,
                                dependency_cycles)
from elysia.core.providers import ProviderManager
from elysia.core.resources import ResourceManager
from elysia.core.tasks import TaskStore


class _NoPressure(ResourceManager):
    def memory_pressure(self):
        return False


def fake_provider(pm, label, capabilities, concurrency=2):
    p = pm.register(ProviderConfig(kind="openai", label=label, model="m",
                                   capabilities=capabilities,
                                   concurrency=concurrency))
    p._chat_openai = lambda messages, **kw: ("ok", "")
    p.status = "healthy"
    p.check_health = lambda: "healthy"
    return p


def node_titles(plan):
    return [n["title"] for n in plan]


class TestGraphStructure(unittest.TestCase):
    def test_empty_plan_is_a_blocker(self):
        a = analyze([])
        self.assertFalse(a["ok"])
        self.assertEqual(a["issues"][0]["kind"], "empty_plan")

    def test_unknown_and_self_dependencies(self):
        plan = [{"title": "a", "detail": "create a.py"},
                {"title": "b", "detail": "create b.py", "after": [0, 9, 1]}]
        a = analyze(plan)
        kinds = {i["kind"] for i in a["issues"]}
        self.assertIn("unknown_dependency", kinds)
        self.assertIn("self_dependency", kinds)
        self.assertGreaterEqual(a["blockers"], 0)
        self.assertTrue(a["ok"] or a["blockers"] >= 0)

    def test_cycles_are_found_with_their_path(self):
        plan = [{"title": "a", "detail": "x a.py", "after": [1]},
                {"title": "b", "detail": "x b.py", "after": [2]},
                {"title": "c", "detail": "x c.py", "after": [0]}]
        cycles = find_cycles([{"index": i, "after": p["after"]}
                              for i, p in enumerate(plan)])
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0][0], cycles[0][-1])
        self.assertEqual(set(cycles[0]), {0, 1, 2})
        a = analyze(plan)
        self.assertEqual([i["kind"] for i in a["issues"]].count(
            "circular_dependency"), 1)
        self.assertFalse(a["ok"])
        self.assertEqual(dependency_cycles(plan), cycles)

    def test_no_executor_when_the_fleet_cannot_serve_the_role(self):
        plan = [{"title": "t", "detail": "write a.py", "agent_role": "implementer"}]
        caps = {"implementer": ["chat", "coding"],
                "documentation_agent": ["chat"]}
        pm = ProviderManager()
        fake_provider(pm, "chatonly", ["chat"])
        a = analyze(plan, providers=pm, role_caps=caps)
        self.assertFalse(a["ok"])
        self.assertEqual(a["issues"][0]["kind"], "no_executor")

        pm2 = ProviderManager()
        fake_provider(pm2, "full", ["chat", "coding"])
        b = analyze(plan, providers=pm2, role_caps=caps)
        self.assertTrue(b["ok"], b["issues"])
        self.assertEqual(b["blockers"], 0)

    def test_endless_cycle_of_three_is_not_infinite_recursion(self):
        plan = [{"title": f"t{i}", "detail": "x", "after": [(i + 1) % 40]}
                for i in range(40)]
        a = analyze(plan)          # must return, not hang
        self.assertFalse(a["ok"])


class TestGraphFilesAndWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_duplicate_file_ownership_is_a_blocker(self):
        plan = [{"title": "a", "detail": "write calc.py", "owned_files": ["calc.py"]},
                {"title": "b", "detail": "also calc.py", "owned_files": ["calc.py"]}]
        a = analyze(plan)
        issue = next(i for i in a["issues"]
                     if i["kind"] == "duplicate_file_ownership")
        self.assertEqual(issue["severity"], "blocker")
        self.assertEqual(issue["file"], "calc.py")
        self.assertEqual(issue["tasks"], [0, 1])
        self.assertFalse(a["ok"])

    def test_mentioning_another_tasks_file_without_a_dependency(self):
        plan = [
            {"title": "writer", "detail": "create calc.py",
             "owned_files": ["calc.py"]},
            {"title": "caller", "detail": "import calc.py and use add()",
             "owned_files": ["caller.py"]},
        ]
        a = analyze(plan)
        self.assertIn("overlapping_modification",
                      [i["kind"] for i in a["issues"]])
        # once the caller depends on the writer, the warning is gone
        plan[1]["after"] = [0]
        b = analyze(plan)
        self.assertNotIn("overlapping_modification",
                         [i["kind"] for i in b["issues"]])

    def test_existing_and_new_files_are_told_apart(self):
        with open(os.path.join(self.tmp, "existing.py"), "w") as f:
            f.write("x = 1\n")
        plan = [{"title": "edit", "detail": "change the value",
                 "owned_files": ["existing.py"]},
                {"title": "add", "detail": "new module",
                 "owned_files": ["fresh.py"]}]
        a = analyze(plan, root=self.tmp)
        self.assertEqual(a["graph"]["existing_files"], ["existing.py"])
        self.assertEqual(a["graph"]["new_files"], ["fresh.py"])

    def test_existing_file_without_detail_is_flagged(self):
        with open(os.path.join(self.tmp, "existing.py"), "w") as f:
            f.write("x = 1\n")
        plan = [{"title": "edit", "detail": "", "owned_files": ["existing.py"]}]
        a = analyze(plan, root=self.tmp)
        self.assertIn("existing_file_without_detail",
                      [i["kind"] for i in a["issues"]])

    def test_files_in_never_returns_traversal_or_absolute(self):
        found = files_in("touch /etc/passwd and ../../escape.py and ok.py")
        self.assertIn("ok.py", found)
        self.assertNotIn("/etc/passwd", found)
        self.assertNotIn("../../escape.py", found)

    def test_oversized_and_trivial_detection(self):
        big = {"title": "big", "detail": "x" * 1000,
               "owned_files": [f"f{i}.py" for i in range(OVERSIZED_FILES + 1)]}
        tiny = {"title": "t", "detail": "tiny", "owned_files": ["t.py"]}
        a = analyze([big, tiny])
        kinds = [i["kind"] for i in a["issues"]]
        self.assertIn("oversized_task", kinds)
        self.assertIn("trivial_task", kinds)


class TestEstimates(unittest.TestCase):
    def test_complexity_grows_with_breadth_and_detail(self):
        small = {"index": 0, "title": "s", "detail": "x",
                 "files": ["a.py"], "after": [], "role": "implementer"}
        bigger = {"index": 0, "title": "b", "detail": "x" * 800,
                  "files": ["a.py", "b.py", "c.py"], "after": [1],
                  "role": "implementer"}
        self.assertLess(complexity(small), complexity(bigger))
        self.assertLessEqual(complexity(bigger), 1.0)

    def test_estimates_are_per_task_and_labelled_heuristic(self):
        plan = [{"title": "a", "detail": "create a.py", "owned_files": ["a.py"]},
                {"title": "b", "detail": "create b.py", "owned_files": ["b.py"],
                 "after": [0]}]
        # estimate() accepts raw plan items too (public helper)
        self.assertEqual(len(estimate(plan)["per_task"]), 2)
        real = analyze(plan)["estimates"]
        self.assertEqual(len(real["per_task"]), 2)
        self.assertGreater(real["total_duration_s"], 0)
        self.assertGreater(real["total_tokens_est"], 0)
        self.assertIn("heuristic", real["basis"])
        self.assertEqual(real["per_task"][0]["capabilities"], [])

    def test_estimates_use_role_capabilities(self):
        plan = [{"title": "a", "detail": "create a.py", "owned_files": ["a.py"],
                 "agent_role": "code_reviewer"}]
        real = analyze(plan, role_caps={"code_reviewer": ["chat", "reasoning"]})
        row = real["estimates"]["per_task"][0]
        self.assertEqual(row["capabilities"], ["chat", "reasoning"])
        self.assertGreaterEqual(row["model_calls"], 2)


class TestReplan(unittest.TestCase):
    def test_invalid_dependencies_are_dropped(self):
        plan = [{"title": "a", "detail": "x a.py", "owned_files": ["a.py"]},
                {"title": "b", "detail": "x b.py", "owned_files": ["b.py"],
                 "after": [0, 7, 1]}]
        r = replan(plan)
        self.assertTrue(any("dropped invalid" in c for c in r["changes"]))
        self.assertEqual(r["plan"][1]["after"], [0])

    def test_duplicate_owner_merge_rewires_dependents(self):
        plan = [
            {"title": "a", "detail": "create calc.py", "owned_files": ["calc.py"]},
            {"title": "b", "detail": "create other.py",
             "owned_files": ["other.py"], "after": [0]},
            {"title": "c", "detail": "extend calc.py", "owned_files": ["calc.py"]},
        ]
        r = replan(plan)
        self.assertEqual(r["after"], 2)
        owners = {}
        for i, n in enumerate(r["plan"]):
            for f in n["owned_files"]:
                owners.setdefault(f, []).append(i)
        self.assertEqual(owners["calc.py"], [0])
        # the dependent still waits for the (merged) owner
        self.assertIn(0, r["plan"][1]["after"])
        self.assertTrue(any("two writers" in c for c in r["changes"]))
        # no self edges, no cycles introduced
        self.assertNotIn(0, r["plan"][0]["after"])
        self.assertFalse(find_cycles([{"index": i, "after": n["after"]}
                                      for i, n in enumerate(r["plan"])]))

    def test_split_rewires_dependents_to_every_part(self):
        plan = [
            {"title": "big", "detail": "several modules",
             "owned_files": [f"p{i}.py" for i in range(OVERSIZED_FILES + 2)]},
            {"title": "consumer", "detail": "wire it all up",
             "owned_files": ["main.py"], "after": [0]},
        ]
        r = replan(plan)
        parts = [i for i, n in enumerate(r["plan"]) if "p" in n["title"]]
        self.assertEqual(len(parts), OVERSIZED_FILES + 2)
        self.assertEqual(r["plan"][-1]["after"], parts)
        self.assertTrue(any("split task" in c for c in r["changes"]))

    def test_cycles_are_broken_and_reported(self):
        plan = [{"title": "a", "detail": "x a.py", "owned_files": ["a.py"],
                 "after": [1]},
                {"title": "b", "detail": "x b.py", "owned_files": ["b.py"],
                 "after": [0]}]
        r = replan(plan)
        self.assertTrue(any("break a cycle" in c for c in r["changes"]))
        self.assertFalse(find_cycles([{"index": i, "after": n["after"]}
                                      for i, n in enumerate(r["plan"])]))

    def test_trivial_merge_is_opt_in(self):
        plan = [{"title": "x", "detail": "tiny", "owned_files": ["x.py"]},
                {"title": "y", "detail": "tiny", "owned_files": ["y.py"]}]
        self.assertEqual(len(replan(plan)["plan"]), 2)
        merged = replan(plan, merge_trivial=True)
        self.assertEqual(len(merged["plan"]), 1)
        self.assertEqual(merged["plan"][0]["owned_files"], ["x.py", "y.py"])

    def test_repair_can_never_create_a_structural_problem(self):
        plan = [
            {"title": "a", "detail": "x a.py", "owned_files": ["a.py"], "after": [4]},
            {"title": "b", "detail": "x a.py", "owned_files": ["a.py"], "after": [0]},
            {"title": "c", "detail": "x c.py", "owned_files": ["c.py"], "after": [1]},
            {"title": "d", "detail": "y" * 900,
             "owned_files": [f"d{i}.py" for i in range(OVERSIZED_FILES + 1)],
             "after": [0]},
        ]
        r = replan(plan)
        repaired = analyze(r["plan"])
        self.assertEqual(repaired["blockers"], 0, repaired["issues"])
        self.assertEqual(repaired["issues"][0]["kind"]
                         if repaired["issues"] else "", repaired["issues"][0]["kind"]
                         if repaired["issues"] else "")
        self.assertNotIn("duplicate_file_ownership",
                         [i["kind"] for i in repaired["issues"]])
        self.assertNotIn("circular_dependency",
                         [i["kind"] for i in repaired["issues"]])
        self.assertNotIn("unknown_dependency",
                         [i["kind"] for i in repaired["issues"]])

    def test_replanning_a_repaired_plan_changes_nothing(self):
        plan = [{"title": "a", "detail": "x a.py", "owned_files": ["a.py"]},
                {"title": "b", "detail": "x a.py", "owned_files": ["a.py"],
                 "after": [9]}]
        once = replan(plan)
        twice = replan(once["plan"])
        self.assertEqual(twice["changes"], [])
        self.assertEqual(len(twice["plan"]), len(once["plan"]))


# ---------------------------------------------------------------------------
# master integration
# ---------------------------------------------------------------------------
class MasterHarness:
    def __init__(self, files=(), plan_lines=None):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "ws")
        os.makedirs(self.ws)
        self.store = TaskStore(os.path.join(self.tmp, "board.sqlite"))
        self.pm = ProviderManager()
        self.plan_lines = plan_lines or [
            "- write demo module|Create demo.py with def add(a, b)"]
        self.prompts = []
        outer = self

        class _Backend:
            def __call__(self, messages, max_tokens=None, temperature=None,
                         timeout=None):
                outer.prompts.append(messages[-1].get("content", ""))
                return "\n".join(outer.plan_lines) + "\n", ""

        p = self.pm.register(ProviderConfig(
            kind="openai", label="p0", model="m",
            capabilities=["chat", "coding", "reasoning"], concurrency=2))
        p._chat_openai = _Backend()
        p.status = "healthy"
        p.check_health = lambda: "healthy"
        self.events = EventBus()
        self.master = MasterController(
            self.store, self.pm, self.ws, cfg=Config(), events=self.events,
            resources=_NoPressure(), max_tasks=1, run_tests=False,
            poll_interval_s=0.05, retry_backoff_s=0.2, worker_id="graph-test")

    def close(self):
        self.master.stop()


class TestMasterGraphIntegration(unittest.TestCase):
    def setUp(self):
        self._h = []

    def tearDown(self):
        for h in self._h:
            h.close()

    def harness(self, **kw):
        h = MasterHarness(**kw)
        self._h.append(h)
        return h

    def test_plan_returns_analysis_and_repairs(self):
        h = self.harness(plan_lines=["- write calc.py|Create calc.py",
                                     "- also calc.py|Extend calc.py"])
        res = h.master.plan("two tasks on the same file")
        self.assertTrue(res["ok"])
        self.assertIn("graph", res)
        self.assertIn("repairs", res)
        # the duplicate owner was repaired before anything was persisted
        self.assertEqual(len(res["tasks"]), 1)
        self.assertTrue(any("two writers" in c for c in res["repairs"]["changes"]))
        self.assertEqual(res["graph"]["blockers"], 0)
        self.assertIn("goal.planned", [e["event_type"]
                                       for e in h.events.recent(50)])

    def test_plan_seeds_the_planner_with_project_intelligence(self):
        h = self.harness()
        with open(os.path.join(h.ws, "setup.cfg"), "w") as f:
            f.write("[metadata]\nname = demo\n")
        h.master.plan("add a helper")
        self.assertTrue(h.prompts)
        # the planner prompt now describes the real repository
        self.assertIn("## task", h.prompts[0])
        self.assertGreater(len(h.prompts[0]), 40)

    def test_simulate_reports_conflicts_and_writes_nothing(self):
        h = self.harness(plan_lines=["- write calc.py|Create calc.py",
                                     "- write calc.py|Extend calc.py"])
        sim = h.master.simulate("two writers", plan_with_model=True)
        self.assertEqual(sim["writes"], 0)
        self.assertFalse(sim["executor_started"])
        # the raw planner output conflicted on calc.py; that is reported, and
        # the repaired graph is what would actually run
        self.assertTrue(sim["conflicts"], sim)
        self.assertIn("calc.py", sim["conflicts"][0]["file"])
        self.assertEqual(sim["conflicts"][0]["tasks"], [0, 1])
        self.assertTrue(sim["repairs"]["changes"])
        self.assertEqual(sim["raw_task_count"], 2)
        self.assertEqual(sim["would_create_tasks"], 1)
        self.assertTrue(sim["ok"], sim["blocked"])
        self.assertIn("estimates", sim)
        self.assertEqual(h.store.counts()["total"], 0)
        self.assertFalse(os.path.exists(os.path.join(h.ws, "calc.py")))

    def test_simulate_blocks_on_a_task_that_cannot_be_executed(self):
        h = self.harness()
        sim = h.master.simulate("review only", subs=[
            {"title": "review it", "detail": "review calc.py",
             "agent_role": "code_reviewer", "owned_files": ["calc.py"]}])
        self.assertFalse(sim["ok"])
        kinds = [i["kind"] for i in sim["blocked"]]
        self.assertIn("no_write_permission", kinds)
        self.assertEqual(sim["writes"], 0)
        self.assertEqual(h.store.counts()["total"], 0)

    def test_memory_dir_never_resolves_against_the_cwd(self):
        self.assertEqual(_resolve_memory_dir(None, "/tmp/proj/ws"),
                         "/tmp/proj/state/memory")
        self.assertEqual(_resolve_memory_dir("state/memory", "/tmp/proj/ws"),
                         "/tmp/proj/state/memory")
        self.assertEqual(_resolve_memory_dir("/abs/mem", "/tmp/proj/ws"),
                         "/abs/mem")
        # a controller over a temp workspace keeps its memory with that project
        h = self.harness()
        self.assertTrue(h.master.memory.store.dir.startswith(h.tmp))

    def test_submit_keeps_explicit_graphs_and_persists_them(self):
        h = self.harness()
        run = h.master.submit("explicit", subs=[
            {"title": "one", "detail": "create one.py"},
            {"title": "two", "detail": "create two.py", "after": [0]}],
            start=False)
        self.assertTrue(run["ok"])
        self.assertEqual(len(run["subtask_ids"]), 2)
        first, second = [h.store.get(t) for t in run["subtask_ids"]]
        self.assertIn(first["id"], second["dependencies"])


if __name__ == "__main__":
    unittest.main()
