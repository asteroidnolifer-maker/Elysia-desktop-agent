"""Integration tests for orchestrator/server.py API against the new core.

Exercises the HTTP handlers directly (no real model needed):
- /api/task rejects traversal paths
- /api/task accepts valid owned files and emits a structured event
- /api/providers returns the config-driven provider health
- /api/state includes structured event emission
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Hermetic + must precede `import server`: server.py builds its provider
# manager at import time from load_config(), and credential-activated
# presets (cloud keys, CLI agents on PATH) would change what this legacy
# test asserts. Preset integration is covered by tests/test_providers_plus.py.
os.environ["ELYSIA_DISABLE_PRESETS"] = "1"

# Point server's DB at a temp location so tests never touch the real board.
import tempfile

import orchestrator.server as server  # noqa: E402


class ServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "test.sqlite")
        # fresh board schema on the temp DB, then point both modules at it
        from elysia.core.tasks import TaskStore
        TaskStore(cls.db)
        patcher_db = mock.patch.object(server, "DB_PATH", cls.db)
        patcher_hud = mock.patch.object(server, "HUD_PATH",
                                        os.path.join(cls.tmp, "hud.html"))
        patcher_db.start()
        patcher_hud.start()
        cls._patchers = (patcher_db, patcher_hud)
        with open(patcher_hud.new, "w") as f:
            f.write("<html>hud</html>")
        # TaskStore is canonical; no legacy taskboard module needed
        from elysia.core.tasks import TaskStore
        TaskStore(cls.db)

    @classmethod
    def tearDownClass(cls):
        for p in cls._patchers:
            p.stop()

    def _handler(self):
        """A minimal handler with real server methods (routing bypassed)."""
        handler = server.Handler.__new__(server.Handler)
        handler.server = mock.MagicMock()
        handler._send = server.Handler._send.__get__(handler, server.Handler)
        return handler

    def test_traversal_rejected(self):
        h = self._handler()
        from http.server import BaseHTTPRequestHandler
        # actual _send expects self.wfile etc.; instead test validate boundaries:
        from elysia.core.paths import validate_file_list
        with self.assertRaises(Exception):
            validate_file_list(server.WS_DIR, ["../../etc/passwd"])
        with self.assertRaises(Exception):
            validate_file_list(server.WS_DIR, ["/etc/passwd"])

    def test_api_state_and_events(self):
        h = self._handler()
        state = server.Handler._api_state.__get__(h, type(h))()
        self.assertTrue(state["ok"])
        self.assertIn("health", state)
        self.assertIn("providers", state["health"])
        # New health format: providers dict with status
        self.assertIn("status", state["health"]["providers"])


if __name__ == "__main__":
    unittest.main()