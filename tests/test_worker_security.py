"""Test the secure write behavior of worker_local.run_task.

Monkeypatches brain.chat to return a malicious/valid model payload and verifies
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

# Bring orchestrator onto the path so we can import worker_local.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "orchestrator")))

import worker_local  # noqa: E402


class TestWorkerSecurity(unittest.TestCase):
    def _run(self, model_output, owned=None, task_title="T"):
        ws_dir = tempfile.mkdtemp()
        task = {"id": 1, "title": task_title, "description": "do it",
                "files": json.dumps(owned or ["target.py"])}
        with mock.patch.object(worker_local.brain, "chat",
                               return_value=(model_output, "")) as m:
            with mock.patch.object(worker_local, "tb") as tb:
                worker_local.run_task("w1", task, ws_dir)
        return ws_dir, tb

    def test_traversal_rejected(self):
        malicious = ("```py ../escaped.py\nprint('evil')\n```\n")
        ws_dir, tb = self._run(malicious, owned=["target.py"])
        self.assertFalse(os.path.exists(os.path.join(ws_dir, "..", "escaped.py")))
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(ws_dir), "escaped.py")))
        # task must be marked failed
        call = tb.call_args
        args = call[0] if call else ()
        self.assertTrue(any("failed" in str(a) for a in args))

    def test_out_of_scope_rejected_no_remap(self):
        """Owned file is target.py; model writes other.py. Must NOT remap."""
        output = ("```py other.py\nx = 1\n```\n")
        ws_dir, tb = self._run(output, owned=["target.py"])
        # other.py must NOT be created
        self.assertFalse(os.path.exists(os.path.join(ws_dir, "other.py")))
        self.assertFalse(os.path.exists(os.path.join(ws_dir, "target.py")))

    def test_valid_owned_write(self):
        output = ("```py target.py\ndef f():\n    return 1\n```\n")
        ws_dir, tb = self._run(output, owned=["target.py"])
        with open(os.path.join(ws_dir, "target.py")) as f:
            self.assertIn("def f()", f.read())
        call = tb.call_args
        args = call[0] if call else ()
        self.assertTrue(any("done" in str(a) for a in args))


if __name__ == "__main__":
    unittest.main()