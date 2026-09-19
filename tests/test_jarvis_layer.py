"""Tests for the Jarvis-layer additions: multi-domain knowledge base,
machine tool catalog, and the jarvis prompt style."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core import knowledge as kb
from elysia.core import toolcatalog as tc


class TestKnowledgeDomains(unittest.TestCase):
    def test_multi_domain_sweep(self):
        st = kb.stats()
        self.assertGreaterEqual(st["entries"], 18)
        # categories are per-tool front matter; domains come from directories
        entries = kb.load_all()
        domains = {e.domain for e in entries}
        for domain in ("osint", "web-security", "forensics",
                       "reverse-engineering", "kali-tools"):
            self.assertIn(domain, domains, f"{domain} docs missing")

    def test_entries_carry_domain(self):
        entries = kb.load_all()
        domains = {e.domain for e in entries}
        self.assertIn("osint", domains)
        self.assertIn("forensics", domains)
        # README files are not tool entries
        names = {e.name for e in entries}
        self.assertNotIn("README", names)

    def test_search_across_domains(self):
        hits = kb.search("memory forensics incident")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["name"], "volatility3")
        hits = kb.search("username footprint social")
        self.assertTrue(any(h["name"] == "sherlock" for h in hits))

    def test_context_injection_defensive_stance(self):
        ctx = kb.for_context("subdomain enumeration my own company")
        self.assertIn("Authorized-use", ctx)
        self.assertIn("permission", ctx.lower())

    def test_search_no_query_no_crash(self):
        self.assertEqual(kb.search(""), [])
        # a token that only appears in one doc body may match weakly — just
        # assert honesty: results carry scores and names, never crash
        for h in kb.search("zzz-no-match-zzz"):
            self.assertIn("name", h)
            self.assertIn("score", h)


class TestToolCatalog(unittest.TestCase):
    def test_catalog_shapes(self):
        rows = tc.scan()
        self.assertGreaterEqual(len(rows), 30)
        for r in rows:
            self.assertIn("installed", r)
            self.assertIn("group", r)
            self.assertIn("purpose", r)
        # sorted by group then name
        keys = [(r["group"], r["name"]) for r in rows]
        self.assertEqual(keys, sorted(keys))

    def test_detect_installed_and_missing(self):
        r = tc.detect("python3")
        self.assertTrue(r["installed"])
        r2 = tc.detect("definitely-not-a-binary-xyz")
        # not in catalog -> honest error, no crash
        self.assertFalse(r2["installed"])
        self.assertIn("error", r2)
        # Use a tool that's definitely not installed on any CI/dev machine
        r3 = tc.detect("ghidra")
        self.assertFalse(r3["installed"])
        self.assertEqual(r3["group"], "security")

    def test_alias_probe(self):
        # radare2 installs as r2; the catalog probes aliases
        self.assertIn("r2", tc.TOOL_CATALOG["radare2"].get("also", []))

    def test_summary_counts(self):
        s = tc.summary()
        self.assertEqual(s["total"], len(tc.TOOL_CATALOG))
        self.assertEqual(s["installed"] + s["missing"], s["total"])

    def test_capability_brief(self):
        brief = tc.capability_brief()
        self.assertIn("Machine capabilities", brief)
        self.assertIn("python3", brief)

    def test_knowledge_link(self):
        doc = tc.knowledge_for("nmap")
        self.assertIn("nmap", doc)
        self.assertEqual(tc.knowledge_for("not-a-tool-zzz"), "")

    def test_groups_complete(self):
        for r in tc.scan():
            self.assertIn(r["group"], tc.GROUPS)


class TestJarvisStyle(unittest.TestCase):
    def test_style_registered(self):
        from elysia.core.prompts import STYLES, system_prompt
        self.assertIn("jarvis", STYLES)
        prompt = system_prompt("jarvis")
        self.assertIn("JARVIS", prompt)
        self.assertIn("authorization", prompt.lower())

    def test_existing_styles_unaffected(self):
        from elysia.core.prompts import system_prompt
        self.assertIn("precise coding agent", system_prompt("elysia"))
        self.assertIn("Claude Code", system_prompt("claude-code"))


class TestAgentContextCapabilities(unittest.TestCase):
    def test_capability_layer_present(self):
        from elysia.core.agents_context import build_agent_context
        ctx = build_agent_context(None, "review the repo")
        self.assertIn("Machine capabilities", ctx)
        self.assertIn("python3", ctx)

    def test_security_goal_pulls_knowledge_and_caps(self):
        from elysia.core.agents_context import build_agent_context
        ctx = build_agent_context(None, "plan an exposure audit with nmap")
        self.assertIn("Machine capabilities", ctx)
        self.assertIn("Authorized-use", ctx)


if __name__ == "__main__":
    unittest.main()
