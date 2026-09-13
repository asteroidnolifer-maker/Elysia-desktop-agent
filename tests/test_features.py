"""Tests for the Phase 17 hardening + feature-expansion modules.

Pure/offline tests only — no real provider calls, no network. Each test is
isolated to its own temp directory.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core import context as ctx_mod
from elysia.core import git as git_mod
from elysia.core import templates as tpl_mod
from elysia.core import telemetry
from elysia.core import tools as tools_mod
from elysia.core import skills as skills_mod
from elysia.core import plugins as plugins_mod
from elysia.core import research
from elysia.core import agents
from elysia.core import doctor
from elysia.core.computer import Computer
from elysia.core.workspace import Workspace


class FakeExec:
    """Deterministic stand-in for ProviderManager.execute()."""

    def __init__(self, plans=None):
        self.plans = plans or ["Elysia architecture\nContext layers\n"]
        self.calls = []

    def execute(self, messages, capabilities=None, max_tokens=None,
                temperature=None, timeout=None, preferred=None):
        self.calls.append((messages, capabilities))
        if "Break the research question" in messages[0]["content"]:
            return self.plans[0], ""
        user = messages[-1]["content"]
        if "Follow-up queries" in user:
            return "", ""  # no refinement offline — degradable path
        # synthesis stage: echo cited sources from the user message
        cited = [l for l in user.splitlines() if l.startswith("[")]
        body = "\n".join(cited[:3]) or "[1] no sources"
        return ("## Executive Summary\nOK\n## Findings\n" + body +
                "\n## Next Steps\ndone\n"), ""


class ContextTests(unittest.TestCase):
    def test_layer_budget_trim(self):
        cb = ctx_mod.ContextBuilder(budget_chars=500)
        cb.set("system", "S" * 300)      # protected -> must survive
        cb.set("task", "T" * 5000)
        cb.set("memory", "M" * 3000)
        out = cb.to_prompt()
        self.assertIn("S" * 300, out)               # protected raw survives
        self.assertTrue(out.endswith("..."))        # truncated-layer marker
        self.assertLessEqual(len(out), 550)

    def test_unknown_layer_rejected(self):
        cb = ctx_mod.ContextBuilder()
        with self.assertRaises(ctx_mod.ContextError):
            cb.set("nope", "x")

    def test_compress_history(self):
        cb = ctx_mod.ContextBuilder()
        entries = [f"e{i}" for i in range(50)]
        s = cb.compress_history(entries, keep=10)
        # summary line + 10 kept lines -> 10 newlines total
        self.assertEqual(s.count("\n"), 10)
        self.assertIn("[... 40 older events omitted ...]", s)
        self.assertIn("e49", s)


class TelemetryTests(unittest.TestCase):
    def test_cost_tracker_aggregation(self):
        ct = telemetry.CostTracker()
        ct.record("openai", "gpt-4o", 1000, 2000)
        ct.record("openai", "gpt-4o", 500, 500)
        g = ct.grand_total()
        self.assertEqual(g["requests"], 2)
        self.assertEqual(g["tokens_in"], 1500)
        self.assertGreater(g["cost_usd"], 0)   # non-free model estimated
        self.assertEqual(g["failures"], 0)

    def test_journal_append_crash_safe(self):
        d = tempfile.mkdtemp()
        try:
            j = telemetry.Journal(os.path.join(d, "ev.jsonl"))
            j.record({"event_type": "x", "n": 1})
            j.record({"event_type": "x", "n": 2})
            lines = open(os.path.join(d, "ev.jsonl")).read().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[1])["n"], 2)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class ToolsRiskTests(unittest.TestCase):
    def test_high_risk_quarantined_by_default(self):
        reg = tools_mod.ToolRegistry(allowed_high_risk=set())
        reg.register(tools_mod.ToolSpec(name="wipe", permissions=[],
                                        risk=tools_mod.HIGH),
                     lambda args: "ran")
        res = reg.invoke("wipe", {})
        self.assertFalse(res["ok"])
        self.assertIn("high-risk", res["error"])

    def test_high_risk_allowed_when_enabled(self):
        reg = tools_mod.ToolRegistry(allowed_high_risk={"wipe"})
        reg.register(tools_mod.ToolSpec(name="wipe", permissions=[],
                                        risk=tools_mod.HIGH),
                     lambda args: "ran")
        self.assertTrue(reg.invoke("wipe", {})["ok"])

    def test_permission_denied(self):
        reg = tools_mod.ToolRegistry()
        reg.register(tools_mod.ToolSpec(name="deploy",
                                        permissions=["system:deploy"]),
                     lambda args: "ok")
        res = reg.invoke("deploy", {})
        self.assertFalse(res["ok"])
        self.assertIn("permission", res["error"])

    def test_dry_run_preview(self):
        reg = tools_mod.ToolRegistry(dry_run_default=True)
        reg.register(tools_mod.ToolSpec(name="rm", destructive=True,
                                        preview_fn=lambda a: "would delete x"),
                     lambda args: "ran")
        res = reg.invoke("rm", {})
        self.assertTrue(res["ok"])
        self.assertTrue(res["data"]["dry_run"])
        self.assertIn("would delete", res["data"]["preview"])

    def test_unknown_tool_structured_error(self):
        reg = tools_mod.ToolRegistry()
        res = reg.invoke("does-not-exist", {})
        self.assertFalse(res["ok"])


class ComputerTests(unittest.TestCase):
    def test_escape_denied(self):
        d = tempfile.mkdtemp()
        try:
            ws = Workspace(os.path.join(d, "ws"))
            c = Computer(ws)
            r = c.read_file("../outside")
            self.assertFalse(r.ok)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_write_read_roundtrip(self):
        d = tempfile.mkdtemp()
        try:
            ws = Workspace(os.path.join(d, "ws"))
            c = Computer(ws)
            self.assertTrue(c.write_file("sub/a.txt", "hello").ok)
            r = c.read_file("sub/a.txt")
            self.assertTrue(r.ok)
            self.assertEqual(r.preview, "hello")
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_shell_gated_by_policy(self):
        d = tempfile.mkdtemp()
        try:
            ws = Workspace(os.path.join(d, "ws"))
            denied = Computer(ws, allow_shell=False)
            r = denied.run_shell("echo hi")
            self.assertFalse(r.ok)
            allowed = Computer(ws, allow_shell=True, shell_timeout_s=15)
            r = allowed.run_shell("echo hi")
            self.assertTrue(r.ok)
            self.assertEqual(r.preview.strip(), "hi")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class SkillsTests(unittest.TestCase):
    def _write(self, root, name, body):
        d = os.path.join(root, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w") as f:
            f.write(body)

    def test_assess_risk_false_positive_free(self):
        root = tempfile.mkdtemp()
        try:
            self._write(root, "code-review", (
                "---\nname: code-review\n---\n# Review\nCheck for SQL injection "
                "and ensure credentials are never committed.\n"))
            self._write(root, "port-scanner", (
                "---\nname: port-scanner\n---\nScan ports.\n"))
            self._write(root, "rm-destroy", (
                "---\nname: rm-destroy\n---\nUse rm -rf / to clean.\n"))
            found = {s.name: s for s in skills_mod.discover_skills(root)}
            self.assertEqual(found["code-review"].risk, "safe")
            self.assertEqual(found["port-scanner"].risk, "high")   # blocked name
            self.assertEqual(found["rm-destroy"].risk, "high")     # intent
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_frontmatter_parsed(self):
        body = ("---\nname: x\ndescription: \"hello world\"\n"
                "user-invocable: true\nallowed-tools: [a, b]\n---\nbody")
        from elysia.core.skills import _read_frontmatter
        meta, rest = _read_frontmatter(body)
        self.assertEqual(meta["name"], "x")
        self.assertEqual(meta["description"], "hello world")
        self.assertTrue(meta["user-invocable"])
        self.assertEqual(meta["allowed-tools"], ["a", "b"])
        self.assertEqual(rest.strip(), "body")


class TemplatesTests(unittest.TestCase):
    def test_expand_linear_dependencies(self):
        from elysia.core.tasks import TaskStore
        d = tempfile.mkdtemp()
        try:
            s = TaskStore(os.path.join(d, "t.sqlite"))
            ids = tpl_mod.expand_template("feature", "Add login", store=s)
            self.assertEqual(len(ids), 4)
            t1 = s.get(ids[0])
            self.assertEqual(t1["status"], "queued")
            # linear deps: each depends on the previous
            self.assertEqual(s.get(ids[1])["dependencies"], [ids[0]])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_unknown_template(self):
        with self.assertRaises(ValueError):
            tpl_mod.expand_template("nope", "x")

    def test_dedup_hash_stable(self):
        self.assertEqual(tpl_mod.dedup_hash("a", "b", ["x"]),
                         tpl_mod.dedup_hash("a", "b", ["x"]))
        self.assertNotEqual(tpl_mod.dedup_hash("a", "b", ["x"]),
                            tpl_mod.dedup_hash("a", "b", ["y"]))


class ResearchEngineTests(unittest.TestCase):
    def test_offline_plan_search_synthesize(self):
        d = tempfile.mkdtemp()
        try:
            eng = research.ResearchEngine(
                FakeExec(),
                search=research.OfflineSearch(),
                max_sources=5, output_dir=os.path.join(d, "ws"))
            res = eng.run("What is Elysia?")
            self.assertTrue(res["report"])
            self.assertIn("Elysia", res["report"])
            self.assertGreaterEqual(len(res["sources"]), 1)
            # report written to disk
            self.assertTrue(os.path.exists(res["report_path"]))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_fallback_report_when_no_sources(self):
        d = tempfile.mkdtemp()
        try:
            eng = research.ResearchEngine(FakeExec(),
                                          search=research.OfflineSearch([]),
                                          output_dir=d)
            res = eng.run("query without matches", format_spec="brief")
            self.assertIn("no sources found", res["report"].lower())
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_run_deep_degrades_gracefully(self):
        d = tempfile.mkdtemp()
        try:
            eng = research.ResearchEngine(
                FakeExec(),
                search=research.OfflineSearch(),
                max_sources=5, output_dir=os.path.join(d, "ws"))
            res = eng.run_deep("What is Elysia?", breadth=2, depth=1)
            self.assertGreaterEqual(len(res["sources"]), 1)
            self.assertGreaterEqual(res["depth"], 1)
            self.assertTrue(os.path.exists(res["report_path"]))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class OpenReacherTests(unittest.TestCase):
    def test_module_runs_breadth_depth(self):
        from elysia.core.openreacher import OpenReacher
        d = tempfile.mkdtemp()
        try:
            orx = OpenReacher(FakeExec(), search=research.OfflineSearch(),
                              max_sources=5, output_dir=os.path.join(d, "ws"))
            res = orx.research("What is Elysia?", breadth=2, depth=1)
            self.assertTrue(res["report"])
            self.assertGreaterEqual(len(res["sources"]), 1)
            self.assertGreaterEqual(res["depth"], 1)
            self.assertTrue(res["report_path"].endswith(".deep.md"))
            # `run` alias works too
            res2 = orx.run("Elysia", breadth=1, depth=1)
            self.assertTrue(res2["report"])
        finally:
            shutil.rmtree(d, ignore_errors=True)


class ProjectIntelTests(unittest.TestCase):
    def test_detects_commands(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "pyproject.toml"), "w") as f:
                f.write("[project]\n")
            with open(os.path.join(d, "main.py"), "w") as f:
                f.write("print('hi')\n")
            intel = __import__("elysia.core.project", fromlist=["ProjectIntel"])
            pi = intel.ProjectIntel(d)
            info = pi.detect()
            self.assertEqual(info["primary_language"], "Python")
            self.assertIn("pyproject.toml", info["dep_files"])
            self.assertEqual(info["commands"]["test"],
                             "python -m pytest -q")
        finally:
            shutil.rmtree(d, ignore_errors=True)


class PluginTests(unittest.TestCase):
    def test_discover_and_load(self):
        root = tempfile.mkdtemp()
        try:
            plugin_dir = os.path.join(root, "plugins", "hello")
            os.makedirs(plugin_dir)
            with open(os.path.join(plugin_dir, "plugin.json"), "w") as f:
                json.dump({"name": "hello", "description": "d",
                           "version": "1.0", "permissions": []}, f)
            with open(os.path.join(plugin_dir, "plugin.py"), "w") as f:
                f.write("def register(api):\n"
                        "    api['tools']._loaded.append('hello')\n")
            pm = plugins_mod.PluginManager(os.path.join(root, "plugins"),
                                           allow_list=["hello"])
            list_ = pm.list()
            self.assertEqual(len(list_), 1)
            self.assertTrue(list_[0].enabled)
            reg = tools_mod.ToolRegistry()
            reg._loaded = []
            p = pm.load("hello", reg)
            self.assertTrue(p.loaded)
            self.assertEqual(reg._loaded, ["hello"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_forbidden_plugin_not_enabled(self):
        root = tempfile.mkdtemp()
        try:
            pdir = os.path.join(root, "plugins", "x")
            os.makedirs(pdir)
            with open(os.path.join(pdir, "plugin.json"), "w") as f:
                json.dump({"name": "x", "description": "d", "version": "1",
                           "permissions": []}, f)
            pm = plugins_mod.PluginManager(os.path.join(root, "plugins"),
                                           allow_list=["other"])
            list_ = pm.list()
            self.assertEqual(len(list_), 1)
            self.assertFalse(list_[0].enabled)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class AgentPlanTests(unittest.TestCase):
    def test_parse_plan(self):
        text = ("- One | Do one thing\n- Two | Do another\n"
                "Dependencies: 1 -> 2\n# header\n```\nskip\n```\n## title")
        parsed = agents.parse_plan(text)
        self.assertEqual(parsed[0]["title"], "One")
        self.assertEqual(parsed[0]["detail"], "Do one thing")
        self.assertEqual(parsed[1]["title"], "Two")
        self.assertLessEqual(len(parsed), 12)


class DoctorTests(unittest.TestCase):
    def test_workspace_check(self):
        root = tempfile.mkdtemp()
        try:
            ws = os.path.join(root, "ws")
            os.makedirs(ws)
            ok, problems = doctor.check_workspace_secure(ws)
            self.assertTrue(ok, problems)
            self.assertEqual(problems, [])
        finally:
            shutil.rmtree(root, ignore_errors=True)


class GitCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", cls.root], check=True)
        subprocess.run(["git", "-C", cls.root, "config", "user.email",
                        "t@t"], check=True)
        subprocess.run(["git", "-C", cls.root, "config", "user.name",
                        "t"], check=True)
        with open(os.path.join(cls.root, "a.txt"), "w") as f:
            f.write("one")
        subprocess.run(["git", "-C", cls.root, "add", "a.txt"], check=True)
        subprocess.run(["git", "-C", cls.root, "commit", "-qm", "base"],
                       check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_safe_checkpoint_and_rollback(self):
        with open(os.path.join(self.root, "a.txt"), "w") as f:
            f.write("two")
        ok, msg = git_mod.safe_checkpoint(self.root, "checkpoint two")
        self.assertTrue(ok, msg)
        with open(os.path.join(self.root, "a.txt")) as f:
            self.assertEqual(f.read(), "two")
        # rollback soft to the previous commit
        prev = git_mod.last_checkpoint(self.root)
        self.assertIsNotNone(prev)
        # HEAD~1 = base
        ok2, msg2 = git_mod.rollback_checkpoint(self.root, "HEAD~1")
        self.assertTrue(ok2, msg2)


if __name__ == "__main__":
    unittest.main()