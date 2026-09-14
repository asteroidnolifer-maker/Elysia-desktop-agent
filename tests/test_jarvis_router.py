"""Tests for the jarvis front door: intent routing and handler dispatch."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.jarvis import classify, handle


class TestRouting(unittest.TestCase):
    def test_briefing_intents(self):
        for t in ("what's running?", "are we ok", "status report",
                  "what can you do", "any tasks on the board?"):
            self.assertEqual(classify(t), "briefing", t)

    def test_knowledge_intents(self):
        for t in ("which tool scans ports", "how do I audit my own server",
                  "is nmap legal to use", "authorized use of hydra"):
            self.assertEqual(classify(t), "knowledge", t)

    def test_research_and_goal_and_chat(self):
        self.assertEqual(classify("research the latest on llama"),
                         "research")
        self.assertEqual(classify("add a retry counter to the exporter"),
                         "goal")
        self.assertEqual(classify("hello there"), "chat")

    def test_never_crashes_on_empty(self):
        self.assertEqual(classify(""), "chat")
        self.assertEqual(classify(None), "chat")


class TestHandler(unittest.TestCase):
    def test_briefing_handler_returns_sections(self):
        r = handle("what's running?")
        self.assertTrue(r["ok"])
        self.assertIn("Capabilities", r["sections"])
        self.assertIn("Next action", r["sections"])

    def test_knowledge_handler_defensive_stance(self):
        r = handle("how do I scan my own server for exposed panels")
        self.assertTrue(r["ok"])
        self.assertIn("Authorized-use", r["text"])

    def test_knowledge_handler_honest_miss(self):
        r = handle("which tool brews espresso")
        self.assertIn("No vendored knowledge", r["text"])

    def test_handler_never_raises(self):
        # any route must return a dict, never raise
        for t in ("", "x", "what's running", "research quantum computing",
                  "add feature to workspace"):
            r = handle(t, timeout_s=1)
            self.assertIsInstance(r, dict)
            self.assertIn("route", r)


if __name__ == "__main__":
    unittest.main()
