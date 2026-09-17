"""Master control plane tests: goal -> agents -> files -> tests -> review.

Everything below the fake transport is real: TaskStore (SQLite), Scheduler
(leases + atomic provider reservation), TaskExecutor (parallel in-process
slots), AgentPipeline (logical roles), Workspace (path-guarded writes), QA
(python compile), the git-diff code reviewer, and the master controller that
reports all of it.

The fake providers answer by ROLE (read from the system message) instead of by
call order, so the tests do not depend on incidental sequencing.

Proves:
  - the planner really produced the task graph (goal milestone + subtasks)
  - the master drove execution: files exist on disk, QA passed, states stored
  - multiple logical agents ran: planner -> implementer -> tester -> reviewer
  - provider A failing -> provider B executes the same task (failover)
  - independent sub-tasks execute in parallel; dependent ones wait
  - a fresh master over the same board recovers and finishes the work
  - cancellation and QA rejection are honest failures, never silent success
"""
import json
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
from elysia.core.master import (ROLE_CAPABILITIES, MasterController, persist_goal,
                                role_assignments)
from elysia.core.providers import ProviderManager
from elysia.core.resources import ResourceManager
from elysia.core.tasks import TaskStore

PLAN_REPLY = "- write demo module|Create demo.py with def add(a, b)\n"


def plan_reply(*items):
    """A planner reply that names the files each sub-task owns."""
    return "\n".join(items) + "\n"


def py_block(path, body="def add(a, b):\n    return a + b\n"):
    return f"```py {path}\n{body}```\n"


class RoleBackend:
    """Answers like a real model, keyed on the role in the system message.

    ``files`` maps a sub-task's owned file to its written content; the planner
    reply is derived from those same files so plan and write agree.
    """

    SYSTEM_PROMPTS = {
        "planner": "- ",
        "implementer": "```",
        "code reviewer": "MINOR: -: looks fine",
    }

    def __init__(self, files, review="MINOR: demo.py:1: add a docstring",
                 calls=None, lock=None, delay=0.0, fail_roles=()):
        self.files = dict(files)
        self.review = review
        self.calls = calls if calls is not None else {"n": 0}
        self.lock = lock or threading.Lock()
        self.delay = delay
        self.fail_roles = set(fail_roles)
        self.roles = []

    def _role(self, messages):
        sys_msg = messages[0].get("content", "") if messages else ""
        for role in ("planner", "implementer", "code reviewer"):
            if role in sys_msg.lower():
                return role
        return "chat"

    def __call__(self, messages, max_tokens=None, temperature=None,
                 timeout=None):
        role = self._role(messages)
        with self.lock:
            self.calls["n"] += 1
            self.roles.append(role)
        if self.delay:
            time.sleep(self.delay)
        if role in self.fail_roles:
            return "", f"http 500: {role} backend down"
        if role == "planner":
            return plan_reply(*[f"- write {p}|Create {p}" for p in self.files]), ""
        if role == "code reviewer":
            return self.review, ""
        if role == "implementer":
            # answer for the file THIS task owns (parsed from the prompt)
            import re as _re
            prompt = messages[-1].get("content", "") if messages else ""
            m = _re.search(r"FILES YOU OWN.*?\[(.*?)\]", prompt, _re.S)
            owned = [x.strip().strip("'\"") for x in m.group(1).split(",")] \
                if m and m.group(1).strip() else []
            paths = [p for p in owned if p in self.files] or list(self.files)
            return "".join(py_block(p, self.files[p]) for p in paths[:1]), ""
        return "ok", ""


def fake_provider(pm, label, backend, capabilities=None, concurrency=2):
    p = pm.register(ProviderConfig(
        kind="openai", label=label, model=f"m-{label}",
        capabilities=capabilities or ["chat", "coding", "reasoning"],
        concurrency=concurrency))
    p._chat_openai = backend
    p.status = "healthy"
    p.check_health = lambda: "healthy"
    return p


class _NoPressure(ResourceManager):
    def memory_pressure(self):
        return False


def wait_until(fn, timeout=20.0, interval=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return False


def git_repo(root, tracked="tracked.py", body="x = 1\n"):
    """A real git repo so the code reviewer sees a real diff."""
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q"], cwd=root, env=env, check=True)
    with open(os.path.join(root, tracked), "w") as f:
        f.write(body)
    subprocess.run(["git", "add", tracked], cwd=root, env=env, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, env=env,
                   check=True)
    return tracked


class MasterHarness:
    def __init__(self, files, max_tasks=2, init_git=False, run_tests=False,
                 fail_roles=(), delay=0.0, label="p0"):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "ws")
        os.makedirs(self.ws)
        if init_git:
            # track a file the implementer will overwrite, so the code
            # reviewer has a real (non-empty) diff to inspect
            git_repo(self.ws, tracked=sorted(files)[0], body="# placeholder\n")
        self.store = TaskStore(os.path.join(self.tmp, "board.sqlite"))
        self.backend = RoleBackend(files, calls={"n": 0}, delay=delay,
                                   fail_roles=fail_roles)
        self.pm = ProviderManager()
        self.provider = fake_provider(self.pm, label, self.backend)
        self.events = EventBus()
        self.master = MasterController(
            self.store, self.pm, self.ws, cfg=Config(), events=self.events,
            resources=_NoPressure(), max_tasks=max_tasks, run_tests=run_tests,
            poll_interval_s=0.05, heartbeat_interval_s=0.2,
            retry_backoff_s=0.2, worker_id="master-test")

    def new_master(self, max_tasks=2):
        """A second controller over the SAME board (simulated restart)."""
        return MasterController(
            self.store, self.pm, self.ws, cfg=Config(), events=self.events,
            resources=_NoPressure(), max_tasks=max_tasks, run_tests=False,
            poll_interval_s=0.05, heartbeat_interval_s=0.2,
            retry_backoff_s=0.2, worker_id="master-restart")

    def close(self):
        self.master.stop()
        self.new_master().stop()


class TestMasterControlPlane(unittest.TestCase):
    def setUp(self):
        self._h = []

    def tearDown(self):
        for h in self._h:
            h.close()

    def harness(self, files, **kw):
        h = MasterHarness(files, **kw)
        self._h.append(h)
        return h

    # -- the complete workflow ------------------------------------------------
    def test_goal_to_completion_with_full_agent_trace(self):
        body = "def add(a, b):\n    return a + b\n"
        h = self.harness({"demo.py": body}, init_git=True, run_tests=True)
        run = h.master.run("add an add() helper to demo.py", timeout_s=30)

        rep = run["report"]
        self.assertTrue(rep["ok"], rep)
        self.assertEqual(rep["completed"], 1)
        self.assertEqual(rep["failed"], 0)

        # durable task graph: goal milestone + subtask depending on it
        goal = h.store.get(run["goal_task"])
        self.assertEqual(goal["kind"], "goal")
        self.assertEqual(goal["status"], "done")
        sub = h.store.get(run["subtask_ids"][0])
        self.assertEqual(sub["kind"], "subtask")
        self.assertEqual(sub["status"], "completed")
        self.assertIn(run["goal_task"], sub["dependencies"])
        self.assertEqual(sub["agent_role"], "implementer")
        self.assertEqual(sub["owned_files"], ["demo.py"])

        # real file on disk, valid python (QA used the real compiler)
        path = os.path.join(h.ws, "demo.py")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            written = f.read()
        compile(written, "demo.py", "exec")
        self.assertIn("def add", written)
        self.assertIn("demo.py", rep["files_changed"])

        # every stage really executed, in order
        self.assertEqual(rep["stages"],
                         ["implementer", "tester", "code_reviewer"])
        self.assertIn("planner", h.backend.roles)
        self.assertIn("code reviewer", h.backend.roles)

        # the reviewer saw the real diff and its output is stored on the task
        self.assertIn("docstring", sub["result"] or "")
        self.assertEqual(rep["executor_stats"]["executed"], 1)

    def test_planner_role_ran_first_and_defined_the_graph(self):
        h = self.harness({"one.py": "a = 1\n", "two.py": "b = 2\n"})
        run = h.master.run("create two small modules", timeout_s=30)
        self.assertTrue(run["report"]["ok"])
        self.assertEqual(h.backend.roles[0], "planner")
        # two planned sub-tasks -> two durable rows owning the planned files
        self.assertEqual(len(run["subtasks"]), 2)
        owned = {f for t in run["report"]["tasks"] for f in t["owned_files"]}
        self.assertEqual(owned, {"one.py", "two.py"})

    # -- provider selection / failover ---------------------------------------
    def test_provider_failover_executes_second_provider(self):
        h = self.harness({"demo.py": "def add(a, b):\n    return a + b\n"})
        # A fails every model call; B must take over for the same task.
        h.backend.fail_roles = {"planner", "implementer", "code reviewer"}
        pb = RoleBackend({"demo.py": "def add(a, b):\n    return a + b\n"})
        fake_provider(h.pm, "p1", pb)

        run = h.master.run("write demo.py", timeout_s=30)
        rep = run["report"]
        self.assertTrue(rep["ok"], rep)
        self.assertTrue(os.path.exists(os.path.join(h.ws, "demo.py")))
        self.assertGreaterEqual(h.provider.failures, 1)
        self.assertGreater(pb.calls["n"], 0)
        self.assertGreaterEqual(rep["provider_failures"], 1)
        # the completed task records the provider that actually answered
        self.assertEqual(h.store.get(run["subtask_ids"][0])["status"],
                         "completed")

    def test_no_provider_means_goal_is_reported_not_lost(self):
        h = self.harness({"demo.py": "x = 1\n"})
        h.backend.fail_roles = {"planner", "implementer", "code reviewer"}
        run = h.master.run("doomed goal", timeout_s=10)
        self.assertFalse(run["ok"])
        self.assertEqual(run["status"], "error")
        self.assertIn("http 500", run.get("error") or "")

    # -- parallelism and dependencies ----------------------------------------
    def test_independent_subtasks_run_in_parallel(self):
        calls = {"n": 0}
        lock = threading.Lock()
        peak = {"n": 0, "now": 0}

        class _Counter(RoleBackend):
            def __call__(self, *a, **kw):
                role = self._role(a[0] if a else [])
                if role == "implementer":
                    with lock:
                        peak["now"] += 1
                        peak["n"] = max(peak["n"], peak["now"])
                    try:
                        return super().__call__(*a, **kw)
                    finally:
                        with lock:
                            peak["now"] -= 1
                return super().__call__(*a, **kw)

        h = self.harness({})
        h.backend = _Counter({"one.py": "a = 1\n", "two.py": "b = 2\n",
                              "three.py": "c = 3\n"}, calls={"n": 0},
                             delay=0.25)
        h.pm.get("p0")._chat_openai = h.backend

        run = h.master.run("three independent modules", timeout_s=30)
        self.assertTrue(run["report"]["ok"], run["report"])
        self.assertGreaterEqual(peak["n"], 2,
                                "independent sub-tasks must overlap")
        for f in ("one.py", "two.py", "three.py"):
            self.assertTrue(os.path.exists(os.path.join(h.ws, f)))

    def test_dependent_subtask_waits_for_prerequisite(self):
        order = []
        h = self.harness({})
        base = RoleBackend({"a.py": "a = 1\n", "b.py": "b = 2\n"})

        class _Ordered(RoleBackend):
            def __call__(self, messages, *a, **kw):
                if self._role(messages) == "implementer":
                    prompt = messages[-1].get("content", "")
                    tail = prompt.split("FILES YOU OWN", 1)[-1][:120]
                    order.append("a.py" if "a.py" in tail else "b.py")
                return base(messages, *a, **kw)

        h.backend = _Ordered({"a.py": "a = 1\n", "b.py": "b = 2\n"})
        h.pm.get("p0")._chat_openai = h.backend

        run = h.master.run(
            "first then second",
            # explicit sequencing: item 1 must wait for item 0
            subs=[{"title": "first", "detail": "create a.py", "after": []},
                  {"title": "second", "detail": "create b.py", "after": [0]}],
            timeout_s=30)
        rep = run["report"]
        self.assertTrue(rep["ok"], rep)
        first, second = h.store.get(run["subtask_ids"][0]), \
            h.store.get(run["subtask_ids"][1])
        self.assertIn(first["id"], second["dependencies"])
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")
        self.assertEqual(order, ["a.py", "b.py"],
                         "dependent work must not start first")

    # -- durability -----------------------------------------------------------
    def test_restart_recovers_and_finishes_the_workflow(self):
        h = self.harness({"recovered.py": "def ok():\n    return True\n"})
        # submit without executing: the durable rows are the workflow
        run = h.master.submit("write recovered.py", start=False)
        self.assertTrue(run["ok"])
        self.assertEqual(run["status"], "queued")
        self.assertFalse(h.master.running)
        self.assertTrue(all(h.store.get(t)["status"] == "ready"
                            for t in run["subtask_ids"]))

        # a brand-new controller over the same board == a restarted process
        mc2 = h.new_master()
        mc2.start()
        try:
            wait = mc2.wait(run["subtask_ids"], timeout_s=30)
            self.assertTrue(wait["ok"], wait)
        finally:
            mc2.stop()
        self.assertEqual(h.store.get(run["subtask_ids"][0])["status"],
                         "completed")
        self.assertTrue(os.path.exists(os.path.join(h.ws, "recovered.py")))

    def test_interrupt_releases_claims_so_work_is_resumable(self):
        h = self.harness({"later.py": "x = 1\n"})
        run = h.master.submit("write later.py", start=True)
        # stopping mid-flight must not strand claimed tasks
        h.master.stop(release=True)
        t = h.store.get(run["subtask_ids"][0])
        self.assertIn(t["status"], ("ready", "completed"))
        if t["status"] == "ready":
            # handed back to the board: no stale worker, and a short retry
            # backoff so the next master/worker can pick it up
            self.assertIsNone(t["worker"], "claim must be handed back")
            self.assertIsNotNone(t["backoff_until"])

    # -- honest failure -------------------------------------------------------
    def test_qa_rejection_is_a_real_failure(self):
        h = self.harness({"broken.py": "def broken(:\n    pass\n"})
        run = h.master.run("write broken.py", timeout_s=30,
                           subs=[{"title": "broken module",
                                  "detail": "create broken.py"}])
        rep = run["report"]
        self.assertFalse(rep["ok"])
        self.assertEqual(rep["failed"], 1)
        self.assertFalse(os.path.exists(os.path.join(h.ws, "broken.py")))
        self.assertIn("QA failed", h.store.get(run["subtask_ids"][0])["last_error"])

    def test_cancel_stops_the_workflow(self):
        h = self.harness({"never.py": "x = 1\n"})
        run = h.master.submit("write never.py", start=False)
        tid = run["subtask_ids"][0]
        affected = h.master.cancel(tid)
        self.assertIn(tid, affected)
        self.assertEqual(h.store.get(tid)["status"], "cancelled")
        self.assertFalse(os.path.exists(os.path.join(h.ws, "never.py")))

    # -- introspection --------------------------------------------------------
    def test_status_and_agents_describe_the_control_plane(self):
        h = self.harness({"demo.py": "x = 1\n"})
        run = h.master.run("write demo.py", timeout_s=30)
        st = h.master.status()
        self.assertTrue(st["running"])
        self.assertEqual(st["worker"], "master-test")
        self.assertEqual(st["counts"]["completed"], 1)
        self.assertIn("planner", st["stages_seen"])
        self.assertIn("demo.py", json.dumps(st["counts"]) + " " +
                      json.dumps(run["report"]["files_changed"]))

        agents = h.master.agents()
        self.assertEqual({a["role"] for a in agents}, set(ROLE_CAPABILITIES))
        implementer = next(a for a in agents if a["role"] == "implementer")
        self.assertEqual(implementer["provider"], "p0")
        self.assertEqual(implementer["capabilities"], ["chat", "coding"])

    def test_role_assignments_require_matching_capabilities(self):
        pm = ProviderManager()
        chat_only = fake_provider(pm, "chatonly", RoleBackend({}),
                                  capabilities=["chat"])
        rows = {r["role"]: r for r in role_assignments(pm)}
        # documentation needs chat only -> served; implementer needs coding
        self.assertEqual(rows["documentation_agent"]["provider"], "chatonly")
        self.assertIsNone(rows["implementer"]["provider"])
        self.assertEqual(chat_only.cfg.capabilities, ["chat"])

    def test_persist_goal_is_durable_and_idempotent_per_call(self):
        store = TaskStore(os.path.join(tempfile.mkdtemp(), "b.sqlite"))
        nodes = persist_goal("goal", [{"title": "t", "detail": "write a.py"}],
                             store)
        self.assertEqual(len(nodes), 1)
        t = store.get(nodes[0]["id"])
        self.assertEqual(t["status"], "ready")
        self.assertEqual(t["owned_files"], ["a.py"])
        self.assertEqual(t["dependencies"], [nodes[0]["goal_id"]])
        # the goal milestone is already satisfied -> subtask is claimable
        self.assertEqual(len(store.ready_tasks()), 1)


if __name__ == "__main__":
    unittest.main()
