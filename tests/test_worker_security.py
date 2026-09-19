"""Test the secure write behavior of the canonical AgentPipeline.solve_task.

Monkeypatches provider to return a malicious/valid model payload and verifies
(1) path traversal is rejected and never written, and (2) a valid owned-file
write succeeds.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.tasks import TaskStore
from elysia.core.providers import ProviderManager
from elysia.core.agents import AgentPipeline
from elysia.core.fileblocks import parse_file_blocks


class TestWorkerSecurity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = TaskStore(os.path.join(self.tmp, "board.sqlite"))
        self.pm = ProviderManager()

    def _fake_provider(self, output):
        """Register a provider that returns the given output."""
        p = self.pm.register(__import__("elysia.core.config", fromlist=["ProviderConfig"]).ProviderConfig(
            kind="openai", label="fake", model="fake", base_url="http://fake",
            capabilities=["chat", "coding"], concurrency=1))
        p._chat_openai = lambda messages, max_tokens=None, temperature=None, timeout=None: (output, "")

    def test_traversal_rejected(self):
        malicious = ("```py ../escaped.py\nprint('evil')\n```\n")
        self._fake_provider(malicious)

        tid = self.store.add_task("traversal", "do it", owned_files=["target.py"], status="ready")
        self.store.claim(tid, "w1", "fake", "fake", 1200)

        pipe = AgentPipeline(self.pm, self.store, cfg=None)
        outcome = pipe.solve_task(self.store.get(tid), self.tmp, reservation=None, run_tests=False)

        self.assertFalse(outcome.get("ok", True), "traversal must be rejected")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "..", "escaped.py")))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(self.tmp), "escaped.py")))

    def test_out_of_scope_rejected_no_remap(self):
        """Owned file is target.py; model writes other.py. Must NOT remap."""
        output = ("```py other.py\nx = 1\n```\n")
        self._fake_provider(output)

        tid = self.store.add_task("scope", "do it", owned_files=["target.py"], status="ready")
        self.store.claim(tid, "w1", "fake", "fake", 1200)

        pipe = AgentPipeline(self.pm, self.store, cfg=None)
        outcome = pipe.solve_task(self.store.get(tid), self.tmp, reservation=None, run_tests=False)

        self.assertFalse(outcome.get("ok", True), "out-of-scope must be rejected")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "other.py")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "target.py")))

    def test_valid_owned_write(self):
        output = ("```py target.py\ndef f():\n    return 1\n```\n")
        self._fake_provider(output)

        tid = self.store.add_task("valid", "do it", owned_files=["target.py"], status="ready")
        self.store.claim(tid, "w1", "fake", "fake", 1200)

        pipe = AgentPipeline(self.pm, self.store, cfg=None)
        outcome = pipe.solve_task(self.store.get(tid), self.tmp, reservation=None, run_tests=False)

        self.assertTrue(outcome.get("ok"))
        with open(os.path.join(self.tmp, "target.py")) as f:
            self.assertIn("def f()", f.read())


if __name__ == "__main__":
    unittest.main()