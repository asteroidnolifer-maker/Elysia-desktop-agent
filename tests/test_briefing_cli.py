"""Tests for the briefing module and new Jarvis CLI surfaces."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "orchestrator")))

from elysia.core.briefing import brief
from elysia.core.providers import ProviderManager
from elysia.core.config import ProviderConfig
from elysia.core.tasks import TaskStore


def fake_provider(pm, label, status="healthy"):
    p = pm.register(ProviderConfig(kind="openai", label=label, model="m",
                                   capabilities=["chat"], concurrency=1))
    p.status = status
    return p


class TestBriefing(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.store = TaskStore(os.path.join(self.tmp, "b.sqlite"))

    def _pm(self, *statuses):
        pm = ProviderManager()
        for i, s in enumerate(statuses):
            fake_provider(pm, f"p{i}", s)
        return pm

    def test_minimal_brief_never_crashes(self):
        r = brief()   # no store, no providers
        self.assertTrue(r["text"])
        self.assertIn("Capabilities", r["sections"])
        self.assertIn("Next action", r["sections"])

    def test_full_brief_sections(self):
        self.store.add_task("x", "x", owned_files=["a.md"], status="ready")
        r = brief("port scan", store=self.store, providers=self._pm("healthy"))
        for name in ("Capabilities", "Task board", "Providers", "Knowledge",
                     "Next action"):
            self.assertIn(name, r["sections"])
        self.assertTrue(r["ok"])
        self.assertIn("Authorized-use", r["sections"]["Knowledge"])

    def test_failed_tasks_shape_next_action(self):
        self.store.add_task("x", "x", owned_files=["b.md"], status="ready")
        tid = self.store.add_task("y", "y", owned_files=["c.md"], status="ready")
        self.store.complete(tid, "failed", "boom")
        r = brief("", store=self.store, providers=None)
        self.assertIn("ready task", r["sections"]["Next action"])
        # drain the ready ones -> next action must point at failures
        for t in self.store.list(status="ready"):
            self.store.complete(t["id"], "failed", "boom")
        r2 = brief("", store=self.store, providers=None)
        self.assertIn("Review failures", r2["sections"]["Next action"])

    def test_unhealthy_provider_marks_not_ok(self):
        r = brief(store=self.store, providers=self._pm("unavailable"))
        self.assertFalse(r["ok"], "no healthy provider must flag issues")

    def test_empty_store_next_action(self):
        r = brief(store=self.store, providers=None)
        self.assertIn("No work queued", r["sections"]["Next action"])


class TestJarvisCli(unittest.TestCase):
    def _run(self, *argv):
        import subprocess
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        binp = os.path.join(root, "bin", "elysia")   # bash launcher script
        env = dict(os.environ, ELYSIA_DISABLE_PRESETS="1")
        return subprocess.run(["bash", binp, *argv], capture_output=True,
                              text=True, timeout=60, cwd=root, env=env)

    def test_tools_listing(self):
        r = self._run("tools")
        self.assertEqual(r.returncode, 0)
        self.assertIn("machine tool catalog", r.stdout)
        self.assertIn("python3", r.stdout)

    def test_tools_missing_and_check(self):
        r = self._run("tools", "--missing")
        self.assertEqual(r.returncode, 0)
        r2 = self._run("tools", "--check", "nmap")
        self.assertEqual(r2.returncode, 0)
        self.assertIn("nmap", r2.stdout)

    def test_brief_runs(self):
        r = self._run("brief")
        self.assertEqual(r.returncode, 0)
        self.assertIn("## Capabilities", r.stdout)

    def test_knowledge_list_covers_domains(self):
        r = self._run("knowledge", "list")
        self.assertEqual(r.returncode, 0)
        self.assertIn("entries", r.stdout)

    def test_prompt_jarvis(self):
        r = self._run("prompt", "jarvis")
        self.assertEqual(r.returncode, 0)
        self.assertIn("JARVIS", r.stdout)


if __name__ == "__main__":
    unittest.main()
