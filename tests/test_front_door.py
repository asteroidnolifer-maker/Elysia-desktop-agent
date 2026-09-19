"""Front-door fixes: grounded environment/progress answers, goal milestones.

These cover the four defects visible in the HUD screenshots:

1. "what github repos do i own" was sent to the small local model, which
   invented "I don't have access to your GitHub repositories". It must now be
   answered from REAL local state (git remotes, gh, workspace).
2. "is it done" was sent to the model, which invented "I can't check the
   progress of a workflow". It must now read durable board state.
3. A goal-milestone row was created with no result, so the HUD rendered a
   completed milestone as "(no result yet)". It must carry a real summary.
4. The HUD's legacy counters (open/done) did not match the canonical statuses
   (ready/completed), so the DONE tile under-reported.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))

from elysia.core import jarvis  # noqa: E402
from elysia.core import environment  # noqa: E402
from elysia.core.briefing import goal_progress  # noqa: E402
from elysia.core.master import persist_goal  # noqa: E402
from elysia.core.tasks import TaskStore  # noqa: E402


class TestJarvisRouting(unittest.TestCase):
    def test_repo_questions_route_to_environment(self):
        for t in ("what github repos do i own",
                  "which repositories do i have",
                  "list my remotes",
                  "where is the repo"):
            self.assertEqual(jarvis.classify(t), "environment", t)

    def test_progress_followups(self):
        for t in ("is it done", "is that finished yet?", "any progress?",
                  "did it finish", "still running", "how's it going"):
            self.assertEqual(jarvis.classify(t), "progress", t)

    def test_existing_routes_still_hold(self):
        self.assertEqual(jarvis.classify("what's running?"), "briefing")
        self.assertEqual(jarvis.classify("status"), "briefing")
        self.assertEqual(jarvis.classify("hello there"), "chat")
        self.assertEqual(jarvis.classify("add a retry counter"), "goal")
        self.assertEqual(jarvis.classify("which tool scans ports"),
                         "knowledge")
        self.assertEqual(jarvis.classify("research the latest on llama"),
                         "research")

    def test_environment_handler_returns_real_state(self):
        r = jarvis.handle("what github repos do i own", timeout_s=2)
        self.assertEqual(r["route"], "environment")
        self.assertTrue(r["ok"])
        # the real checkout is reported, never a hallucinated refusal
        self.assertIn("GITHUB REPOSITORIES", r["text"])
        self.assertNotIn("I don't have access", r["text"])

    def test_progress_handler_never_raises(self):
        r = jarvis.handle("is it done", timeout_s=2)
        self.assertEqual(r["route"], "progress")
        self.assertIn("text", r)


class TestEnvironmentReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ws = os.path.join(self.tmp, "workspace")
        os.makedirs(self.ws)
        # a real git repo (no network) so remotes/local_repos have something
        os.makedirs(os.path.join(self.tmp, ".git"))
        import subprocess
        subprocess.run(["git", "init", "-q", self.tmp], capture_output=True)
        subprocess.run(["git", "-C", self.tmp, "remote", "add", "origin",
                        "https://example.com/acme/widget.git"],
                       capture_output=True)

    def test_remotes_are_read(self):
        rs = environment.remotes(self.tmp)
        self.assertTrue(any("widget.git" in r["url"] for r in rs))

    def test_report_has_no_gh_does_not_crash(self):
        rep = environment.environment_report(self.tmp, self.ws)
        self.assertIn("ENVIRONMENT", rep)
        self.assertIn("GITHUB REPOSITORIES", rep)
        self.assertIn("LOCAL REPOSITORIES", rep)

    def test_github_repos_honest_when_gh_missing(self):
        import shutil
        if shutil.which("gh"):
            got = environment.github_repos()
            # either a real list or an explicit, non-fabricated error
            self.assertIn("ok", got)
            self.assertIsInstance(got["repos"], list)
        else:
            got = environment.github_repos()
            self.assertFalse(got["ok"])
            self.assertIn("gh", got["error"])

    def test_environment_dict_shape(self):
        d = environment.environment_dict(self.tmp, self.ws)
        for key in ("root", "branch", "remotes", "github", "local_repos"):
            self.assertIn(key, d)


class TestGoalMilestoneAndProgress(unittest.TestCase):
    def setUp(self):
        self.store = TaskStore(os.path.join(tempfile.mkdtemp(), "b.sqlite"))

    def test_goal_milestone_carries_a_real_result(self):
        nodes = persist_goal("search for ai skills", [
            {"title": "collect", "detail": "write findings/skills.md"},
            {"title": "rank", "detail": "write findings/rank.md"},
        ], self.store)
        g = self.store.get(nodes[0]["goal_id"])
        self.assertEqual(g["kind"], "goal")
        self.assertTrue(g["result"], "milestone must not render '(no result yet)'")
        self.assertIn("2 sub-task", g["result"])

    def test_progress_running_then_done(self):
        nodes = persist_goal("g", [
            {"title": "a", "detail": "write a.md"},
            {"title": "b", "detail": "write b.md"},
        ], self.store)
        running = goal_progress(self.store)
        self.assertIn("still running", running)
        self.store.complete(nodes[0]["id"], "completed", "ok")
        self.store.complete(nodes[1]["id"], "completed", "ok")
        done = goal_progress(self.store)
        self.assertIn("DONE", done)

    def test_progress_reports_failure(self):
        nodes = persist_goal("g", [{"title": "a", "detail": "write a.md"}],
                             self.store)
        self.store.complete(nodes[0]["id"], "failed", "boom")
        rep = goal_progress(self.store, goal_id=nodes[0]["goal_id"])
        self.assertIn("stopped", rep)
        self.assertIn("failed", rep)

    def test_progress_empty_board_is_honest(self):
        self.assertIn("No goal has been submitted", goal_progress(self.store))


class TestHudServerFixes(unittest.TestCase):
    """The legacy HUD server routes and counts (no model required)."""

    @classmethod
    def setUpClass(cls):
        os.environ["ELYSIA_DISABLE_PRESETS"] = "1"
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "hud.sqlite")
        TaskStore(cls.db)
        from unittest import mock
        import server
        cls.server = server
        cls._p = mock.patch.object(server, "DB_PATH", cls.db)
        cls._p.start()

    @classmethod
    def tearDownClass(cls):
        cls._p.stop()

    def test_classify_environment_and_progress(self):
        self.assertEqual(self.server.classify_intent("what github repos do i own"),
                         "environment")
        self.assertEqual(self.server.classify_intent("is it done"), "progress")
        self.assertEqual(self.server.classify_intent("what's running?"), "status")
        self.assertEqual(self.server.classify_intent("hello there"), "general")

    def test_progress_intent_reply_when_no_goal(self):
        h = self.server.Handler.__new__(self.server.Handler)
        h._send = lambda code, payload, ctype=None: setattr(h, "sent", payload)
        h._api_chat({"message": "is it done"})
        self.assertEqual(h.sent["intent"], "progress")
        self.assertIn("No goal has been submitted", h.sent["reply"])

    def test_board_counts_maps_canonical_statuses(self):
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM tasks")
        for st in ("ready", "queued", "completed", "failed"):
            con.execute(
                "INSERT INTO tasks (title, description, owned_files, "
                "read_files, dependencies, priority, max_attempts, kind, "
                "status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (st, st, "[]", "[]", "[]", 5, 3, "task", st, 0.0))
        con.commit()
        con.close()
        c = self.server.board_counts()
        self.assertEqual(c["open"], 2)      # ready + queued
        self.assertEqual(c["done"], 1)      # completed
        self.assertEqual(c["failed"], 1)
        self.assertEqual(c["total"], 4)

    def test_recent_tasks_accepts_status_group(self):
        rows = self.server.recent_tasks(limit=10, status="ready,queued")
        self.assertTrue(all(r["status"] in ("ready", "queued") for r in rows))


if __name__ == "__main__":
    unittest.main()
