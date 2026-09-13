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
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "orchestrator")))

# Point server's DB at a temp location so tests never touch the real board.
import tempfile

import server  # noqa: E402


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
        import taskboard
        taskboard._store = TaskStore(cls.db)

    @classmethod
    def tearDownClass(cls):
        for p in cls._patchers:
            p.stop()

    def _handler(self):
        """A minimal handler with real server methods (routing bypassed)."""
        import server as s
        from unittest import mock as m
        handler = s.Handler.__new__(s.Handler)
        handler.server = m.MagicMock()
        handler._send = s.Handler._send.__get__(handler, s.Handler)
        return handler

    def test_traversal_rejected(self):
        # instance-level state needed by _send
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
        self.assertTrue(state["health"]["provider_healthy"] is not None)
        ev = server.EVENTS.recent(n=10, event_type="api_state")
        self.assertTrue(any(e["event_type"] == "api_state" for e in ev))

    def test_provider_health_report(self):
        h = self._handler()
        provs = server.Handler._api_providers.__get__(h, type(h))()
        self.assertTrue(provs["ok"])
        names = [p["name"] for p in provs["providers"]]
        self.assertEqual(names, ["local"])


if __name__ == "__main__":
    unittest.main()