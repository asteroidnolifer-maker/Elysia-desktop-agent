"""Tests for the canonical runtime tool layer, simulation, routing and health.

These tests exercise the REAL subsystems: Workspace path validation, the QA
harness, the task store, the scheduler/executor, and (for the live test) the
whole master pipeline driven by a fake provider transport.

Proves:
  - deny-by-default: unknown roles and unknown tools are refused
  - reviewers can never write, even when config tries to grant it
  - traversal, absolute paths and symlink escapes are refused by the tool layer
  - dry-run previews change nothing on disk
  - desktop/clipboard control needs BOTH policy and permission, and reports an
    unavailable host honestly instead of pretending
  - the SSRF guard refuses loopback/link-local/private targets and bad schemes
  - simulation writes nothing (no files, no board rows, no scheduler)
  - routing is explainable (why this provider, who was rejected and why)
  - health is reported as independent dimensions, never one magic score
  - the live pipeline really writes files THROUGH the tool layer
"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core.computer import Computer, DesktopBackend, NullDesktop
from elysia.core.config import Config, ProviderConfig
from elysia.core.events import EventBus
from elysia.core.health import dimensions, failing
from elysia.core.master import MasterController
from elysia.core.providers import ProviderManager
from elysia.core.resources import ResourceManager
from elysia.core.tasks import TaskStore
from elysia.core.toolkit import (build_tools, role_permissions, tool_audit,
                                 url_blocked_reason)
from elysia.core.workspace import Workspace


def tmp_ws():
    root = tempfile.mkdtemp()
    return root, Workspace(root)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Permission model
# ---------------------------------------------------------------------------
class TestPermissions(unittest.TestCase):
    def test_unknown_role_is_granted_nothing(self):
        root, ws = tmp_ws()
        layer = build_tools(ws)
        self.assertEqual(layer.grant("nobody"), [])
        res = layer.invoke("fs.write", {"path": "a.py", "content": "x = 1\n"},
                           "nobody")
        self.assertFalse(res["ok"])
        self.assertFalse(os.path.exists(os.path.join(root, "a.py")))

    def test_unknown_tool_is_refused(self):
        _, ws = tmp_ws()
        layer = build_tools(ws)
        res = layer.invoke("shell.exec", {"cmd": "rm -rf /"}, "implementer")
        self.assertFalse(res["ok"])
        self.assertIn("unknown tool", res["error"])

    def test_reviewer_cannot_write_even_if_config_asks(self):
        _, ws = tmp_ws()
        # A config that (wrongly) tries to grant reviewers write access.
        roles = role_permissions(ceiling=["read_only", "workspace_write",
                                          "git_write"],
                                 overrides={"code_reviewer": ["workspace_write",
                                                              "git_write"]})
        self.assertNotIn("workspace:write", roles["code_reviewer"])
        self.assertNotIn("git:write", roles["code_reviewer"])
        layer = build_tools(ws, role_levels={"code_reviewer": ["workspace_write"]})
        self.assertFalse(layer.allowed("fs.write", "code_reviewer")[0])

    def test_implementer_may_write_via_tool(self):
        root, ws = tmp_ws()
        events = EventBus()
        layer = build_tools(ws, events=events)
        res = layer.invoke("fs.write", {"path": "sub/mod.py",
                                        "content": "def f():\n    return 1\n"},
                           "implementer")
        self.assertTrue(res["ok"], res)
        self.assertTrue(os.path.isfile(os.path.join(root, "sub", "mod.py")))
        kinds = [e["event_type"] for e in events.recent(50)]
        self.assertIn("tool.invoke", kinds)
        self.assertIn("tool.result", kinds)
        self.assertIn("file.changed", kinds)

    def test_qa_and_git_tools_are_real(self):
        root, ws = tmp_ws()
        layer = build_tools(ws)
        bad = layer.invoke("qa.validate", {"path": "broken.py",
                                           "content": "def f(:\n"},
                           "implementer")
        self.assertFalse(bad["data"]["valid"])
        good = layer.invoke("qa.validate", {"path": "ok.py",
                                            "content": "x = 1\n"},
                            "implementer")
        self.assertTrue(good["data"]["valid"])
        status = layer.invoke("git.status", {}, "implementer")
        self.assertFalse(status["data"]["repo"])   # plain temp dir, not a repo

    def test_search_finds_text_and_stays_in_workspace(self):
        root, ws = tmp_ws()
        ws.write_owned("pkg/a.py", "SECRET_MARKER = 1\n")
        outside = tempfile.mkdtemp()
        with open(os.path.join(outside, "b.py"), "w") as f:
            f.write("SECRET_MARKER = 2\n")
        layer = build_tools(ws)
        res = layer.invoke("fs.search", {"pattern": "SECRET_MARKER"},
                           "implementer")
        paths = [h["path"] for h in res["data"]["hits"]]
        self.assertEqual(paths, ["pkg/a.py"])

    def test_config_drives_ceiling_and_role_overrides(self):
        cfg = Config()
        cfg.tools.allow_high_risk = True
        cfg.tools.enable_shell = True
        cfg.tools.default_permissions = ["read_only", "workspace_write",
                                         "system", "desktop"]
        cfg.tools.role_permissions = {"implementer": ["desktop"]}
        layer = build_tools(tempfile.mkdtemp(), cfg=cfg,
                            desktop=FakeDesktop())
        self.assertTrue(layer.allowed("desktop.click", "implementer")[0])
        self.assertTrue(layer.allowed("qa.run_tests", "tester")[0])
        # the ceiling still applies: no git:write was granted to anyone
        self.assertFalse(layer.allowed("git.checkpoint", "implementer")[0])

    def test_tools_disabled_is_the_documented_escape_hatch(self):
        from elysia.core.master import MasterController
        root = tempfile.mkdtemp()
        cfg = Config()
        cfg.tools.enabled = False
        store = TaskStore(os.path.join(root, "t.sqlite"))
        pm = ProviderManager()
        master = MasterController(store, pm, os.path.join(root, "ws"), cfg=cfg,
                                  events=EventBus(), resources=_NoPressure(),
                                  max_tasks=1)
        self.assertIsNone(master.tools)
        self.assertEqual(master.tools_report(), [])
        master.stop()

    def test_permission_report_lists_denials(self):
        _, ws = tmp_ws()
        layer = build_tools(ws)
        audit = tool_audit(layer, "code_reviewer")
        self.assertFalse([r for r in audit["rows"]
                          if r["tool"] == "fs.write"][0]["allowed"])
        self.assertTrue([r for r in audit["rows"]
                         if r["tool"] == "fs.read"][0]["allowed"])


# ---------------------------------------------------------------------------
# Workspace security through the tool layer
# ---------------------------------------------------------------------------
class TestToolSecurity(unittest.TestCase):
    def test_traversal_and_absolute_paths_refused(self):
        root, ws = tmp_ws()
        layer = build_tools(ws)
        outside = os.path.join(os.path.dirname(root), "escaped.py")
        for bad in ("../escaped.py", "/etc/passwd", "a/../../b.py", ""):
            res = layer.invoke("fs.write", {"path": bad, "content": "x = 1\n"},
                               "implementer")
            self.assertFalse(res["ok"], bad)
        self.assertFalse(os.path.exists(outside))

    def test_symlink_escape_refused(self):
        root, ws = tmp_ws()
        secret = tempfile.mkdtemp()
        target = os.path.join(secret, "outside.txt")
        with open(target, "w") as f:
            f.write("secret")
        os.symlink(secret, os.path.join(root, "link"))
        layer = build_tools(ws)
        res = layer.invoke("fs.read", {"path": "link/outside.txt"}, "implementer")
        self.assertFalse(res["ok"])

    def test_dry_run_previews_without_touching_disk(self):
        root, ws = tmp_ws()
        layer = build_tools(ws)
        layer.invoke("fs.write", {"path": "keep.py", "content": "x = 1\n"},
                     "implementer")
        res = layer.invoke("fs.remove", {"path": "keep.py", "_dry_run": True},
                           "implementer")
        self.assertTrue(res["ok"])
        self.assertTrue(res.get("dry_run"))
        self.assertTrue(os.path.isfile(os.path.join(root, "keep.py")))
        # without the dry-run flag the removal really happens
        res = layer.invoke("fs.remove", {"path": "keep.py"}, "implementer")
        self.assertTrue(res["ok"])
        self.assertFalse(os.path.exists(os.path.join(root, "keep.py")))

    def test_ssrf_guard_blocks_internal_targets(self):
        for url in ("http://127.0.0.1:8087/api/state",
                    "http://169.254.169.254/latest/meta-data/",
                    "http://10.0.0.5/", "http://192.168.1.1/",
                    "file:///etc/passwd", "ftp://example.com/x", "not a url"):
            self.assertIsNotNone(url_blocked_reason(url), url)
        self.assertIsNone(url_blocked_reason("https://example.com/page"))

    def test_browser_tool_refuses_ssrf_url(self):
        _, ws = tmp_ws()
        events = EventBus()
        # grant the browser capability first, so the refusal can only come from
        # the SSRF guard rather than from the permission gate
        layer = build_tools(ws, events=events,
                            ceiling=["browser"],
                            role_levels={"researcher": ["browser"]})
        self.assertTrue(layer.allowed("browser.open_url", "researcher")[0])
        res = layer.invoke("browser.open_url",
                           {"url": "http://169.254.169.254/latest/meta-data"},
                           "researcher")
        self.assertFalse(res["ok"])
        quarantine = [e for e in events.recent(50)
                      if e["event_type"] == "tool.quarantined"]
        self.assertTrue(quarantine)

    def test_browser_tool_denied_without_permission(self):
        _, ws = tmp_ws()
        layer = build_tools(ws)          # default ceiling: no browser:control
        res = layer.invoke("browser.open_url", {"url": "https://example.com"},
                           "researcher")
        self.assertFalse(res["ok"])
        self.assertIn("browser:control", res["error"])


# ---------------------------------------------------------------------------
# Desktop / computer control
# ---------------------------------------------------------------------------
class FakeDesktop(DesktopBackend):
    name = "fake"

    def __init__(self):
        self.calls = []
        self.clip = ""

    def available(self):
        return True

    def screenshot(self, path=""):
        self.calls.append(("screenshot", path))
        return {"path": path}

    def windows(self):
        self.calls.append(("windows", None))
        return {"count": 1, "windows": [{"id": "1", "title": "term"}]}

    def move_mouse(self, x, y):
        self.calls.append(("mouse", (x, y)))
        return {"moved": [x, y]}

    def click(self, x=None, y=None, button="left"):
        self.calls.append(("click", (x, y, button)))
        return {"clicked": True}

    def type_text(self, text):
        self.calls.append(("type", text))
        return {"typed": len(text)}

    def press(self, key):
        self.calls.append(("key", key))
        return {"pressed": key}

    def clipboard_read(self):
        return self.clip or "clip"

    def clipboard_write(self, text):
        self.clip = text
        self.calls.append(("clip_write", text))
        return True

    def launch(self, app, args=None):
        self.calls.append(("launch", app))
        return {"pid": 42, "app": app}


class TestDesktopControl(unittest.TestCase):
    def test_needs_policy_and_permission(self):
        _, ws = tmp_ws()
        default = build_tools(ws, desktop=FakeDesktop())
        # 1. high-risk gate closed -> refused
        ok, why = default.allowed("desktop.click", "implementer")
        self.assertFalse(ok)
        self.assertIn("high-risk", why)
        # 2. open the gate but keep the permission ceiling -> still refused
        opened = build_tools(ws, desktop=FakeDesktop(),
                             ceiling=["read_only", "workspace_write", "desktop"],
                             allow_high_risk=True)
        ok, why = opened.allowed("desktop.click", "implementer")
        self.assertFalse(ok)
        self.assertIn("desktop:control", why)
        # 3. grant the role the desktop level -> allowed and it really executes
        granted = build_tools(ws, desktop=FakeDesktop(),
                              ceiling=["read_only", "workspace_write", "desktop"],
                              allow_high_risk=True,
                              role_levels={"implementer": ["workspace_write",
                                                           "desktop"]})
        ok, why = granted.allowed("desktop.click", "implementer")
        self.assertTrue(ok, why)
        res = granted.invoke("desktop.click", {"x": 3, "y": 4}, "implementer")
        self.assertTrue(res["ok"], res)
        self.assertIn(("click", (3, 4, "left")), granted.desktop.calls)

    def test_reviewer_never_gets_desktop(self):
        _, ws = tmp_ws()
        layer = build_tools(ws, desktop=FakeDesktop(),
                            ceiling=["read_only", "desktop"],
                            allow_high_risk=True,
                            role_levels={"code_reviewer": ["desktop"]})
        self.assertFalse(layer.allowed("desktop.click", "code_reviewer")[0])

    def test_unavailable_backend_is_honest(self):
        _, ws = tmp_ws()
        layer = build_tools(ws, desktop=NullDesktop(),
                            ceiling=["read_only", "desktop"],
                            allow_high_risk=True,
                            role_levels={"implementer": ["workspace_write",
                                                         "desktop"]})
        self.assertTrue(layer.allowed("desktop.windows", "implementer")[0])
        res = layer.invoke("desktop.windows", {}, "implementer")
        self.assertFalse(res["ok"])
        self.assertIn("unavailable", res["error"])

    def test_computer_requires_explicit_grant(self):
        root, ws = tmp_ws()
        c = Computer(ws, desktop=FakeDesktop())
        denied = c.desktop_action("windows")
        self.assertFalse(denied.ok)
        self.assertIn("permission", denied.error)
        allowed = Computer(ws, desktop=NullDesktop(), allow_desktop=True)
        res = allowed.desktop_action("windows")
        self.assertFalse(res.ok)          # no driver on this host
        self.assertIn("unavailable", res.error)


# ---------------------------------------------------------------------------
# Simulation + routing + health
# ---------------------------------------------------------------------------
class _NoPressure(ResourceManager):
    def memory_pressure(self):
        return False


class Backend:
    """Minimal fake transport: writes the owned file for the implementer role."""

    def __init__(self):
        self.calls = 0

    def __call__(self, messages, max_tokens=None, temperature=None, timeout=None):
        self.calls += 1
        prompt = messages[-1].get("content", "") if messages else ""
        m = re.search(r"FILES YOU OWN.*?\[(.*?)\]", prompt, re.S)
        owned = [x.strip().strip("'\"") for x in m.group(1).split(",")] if m \
            and m.group(1).strip() else []
        path = owned[0] if owned else "out.py"
        return f"```py {path}\ndef add(a, b):\n    return a + b\n```\n", ""


def harness(cfg=None, files=None, caps=("chat", "coding", "reasoning")):
    root = tempfile.mkdtemp()
    store = TaskStore(os.path.join(root, "tasks.sqlite"))
    pm = ProviderManager()
    backend = Backend()
    p = pm.register(ProviderConfig(kind="openai", label="fake", model="fake-1",
                                   capabilities=list(caps), concurrency=2))
    p._chat_openai = backend
    p.status = "healthy"
    p.check_health = lambda: "healthy"
    master = MasterController(store, pm, os.path.join(root, "ws"), cfg=cfg,
                              events=EventBus(), resources=_NoPressure(),
                              max_tasks=1, run_tests=False)
    return root, store, pm, master, backend


class TestSimulation(unittest.TestCase):
    def test_simulation_writes_nothing_and_finds_conflicts(self):
        root, store, pm, master, backend = harness()
        before = store.counts()
        sim = master.simulate("add a feature", subs=[
            {"title": "one", "detail": "add calc.py", "owned_files": ["calc.py"]},
            {"title": "two", "detail": "also calc.py", "owned_files": ["calc.py"],
             "after": [0]},
        ])
        self.assertIn(sim["mode"], ("simulation",))
        self.assertEqual(sim["writes"], 0)
        self.assertFalse(sim["executor_started"])
        self.assertEqual(backend.calls, 0, "simulation must not call a model "
                                          "when sub-tasks are supplied")
        self.assertEqual(store.counts(), before, "simulation must not create tasks")
        self.assertEqual(os.listdir(os.path.join(root, "ws")), [])
        self.assertEqual(sim["files_that_would_change"], ["calc.py"])
        self.assertEqual(len(sim["conflicts"]), 1)
        self.assertIn("calc.py", sim["conflicts"][0]["file"])

    def test_simulation_detects_circular_dependencies(self):
        _, _, _, master, _ = harness()
        sim = master.simulate("circular", subs=[
            {"title": "a", "detail": "x.py", "after": [1]},
            {"title": "b", "detail": "y.py", "after": [0]},
        ])
        self.assertTrue(sim["circular_dependencies"])
        self.assertFalse(sim["ok"])

    def test_simulation_reports_unservable_role(self):
        _, _, _, master, _ = harness(caps=("chat",))   # no coding/reasoning
        sim = master.simulate("needs a coder", subs=[
            {"title": "impl", "detail": "calc.py", "agent_role": "implementer"},
        ])
        kinds = [i["kind"] for i in sim["blocked"]]
        self.assertIn("no_executor", kinds)
        self.assertFalse(sim["ok"])

    def test_simulation_without_subs_needs_a_model(self):
        _, _, _, master, _ = harness()
        sim = master.simulate("anything", plan_with_model=False)
        self.assertFalse(sim["ok"])
        self.assertIn("disabled", sim["error"])


class TestRoutingExplanation(unittest.TestCase):
    def test_explain_picks_and_justifies(self):
        _, _, pm, master, _ = harness()
        why = master.explain_routing(["chat", "coding"])
        self.assertEqual(why["selected"], "fake")
        self.assertEqual(why["model"], "fake-1")
        self.assertIn("fake", why["reason"])
        self.assertIn("chat", why["reason"])
        self.assertTrue(why["priority_order"])
        self.assertEqual(why["trace"][0]["reason"], None)

    def test_explain_records_rejections(self):
        root = tempfile.mkdtemp()
        store = TaskStore(os.path.join(root, "t.sqlite"))
        pm = ProviderManager()
        bad = pm.register(ProviderConfig(kind="openai", label="nocoder",
                                        model="m0", capabilities=["chat"]))
        bad.status = "healthy"
        good = pm.register(ProviderConfig(kind="openai", label="coder",
                                         model="m1",
                                         capabilities=["chat", "coding"]))
        good.status = "healthy"
        why = pm.explain(["chat", "coding"])
        self.assertEqual(why["selected"], "coder")
        reasons = {r["provider"]: r["reason"] for r in why["trace"]}
        self.assertIn("missing capabilities", reasons["nocoder"])

    def test_explain_is_read_only(self):
        _, _, pm, master, _ = harness()
        p = pm.get("fake")
        master.explain_routing(["chat"])
        self.assertEqual(p.in_flight, 0, "explain must not hold a slot")

    def test_no_provider_is_reported_not_raised(self):
        root = tempfile.mkdtemp()
        store = TaskStore(os.path.join(root, "t.sqlite"))
        pm = ProviderManager()
        why = pm.explain(["chat"])
        self.assertIsNone(why["selected"])
        self.assertIn("queue", why["reason"])


class TestHealthDimensions(unittest.TestCase):
    def test_dimensions_are_independent_no_magic_score(self):
        _, _, _, master, _ = harness()
        rep = master.health()
        for name in ("providers", "scheduler", "task_store", "workspace",
                     "resources", "security", "tests", "git", "memory",
                     "installation"):
            self.assertIn(name, rep)
            self.assertIn(rep[name]["status"],
                          ("ok", "warn", "fail", "unknown"))
        self.assertNotIn("score", rep)
        self.assertIn("no aggregate score", rep["summary"]["note"])
        self.assertEqual(rep["summary"]["dimensions"], 10)

    def test_unprobed_providers_are_warned_not_claimed_healthy(self):
        _, _, _, master, _ = harness()
        rep = master.health()
        self.assertEqual(rep["providers"]["status"], "warn")
        self.assertIn("never contacted", rep["providers"]["detail"])

    def test_failing_lists_only_failures(self):
        rep = {"a": {"status": "fail"}, "b": {"status": "warn"},
               "c": {"status": "ok"}}
        self.assertEqual(failing(rep), ["a"])

    def test_resources_dimension_resolves_from_config(self):
        from elysia.core.resources import ResourceManager
        cfg = Config()
        rm = ResourceManager.from_config(cfg)
        self.assertEqual(rm.reserve_mb, cfg.resources.reserve_mb)
        rep = dimensions(store=None, providers=None, events=None,
                         workspace_root=tempfile.mkdtemp(), cfg=cfg,
                         repo_root=tempfile.mkdtemp())
        self.assertIn(rep["resources"]["status"], ("ok", "warn", "fail"))
        self.assertNotIn("probe failed", rep["resources"]["detail"])

    def test_empty_report_is_honest(self):
        rep = dimensions(store=None, providers=None, events=None,
                         workspace_root=tempfile.mkdtemp(), cfg=None,
                         repo_root=tempfile.mkdtemp())
        self.assertEqual(rep["providers"]["status"], "unknown")
        self.assertEqual(rep["task_store"]["status"], "unknown")


# ---------------------------------------------------------------------------
# The live path really goes through the tool layer
# ---------------------------------------------------------------------------
class TestLivePipelineUsesTools(unittest.TestCase):
    def _run(self, cfg):
        root, store, pm, master, backend = harness(cfg=cfg)
        run = master.submit("add calc", subs=[
            {"title": "implement calc", "detail": "create calc.py",
             "owned_files": ["calc.py"]}])
        self.assertTrue(run["ok"], run)
        wait = master.wait(run["subtask_ids"], timeout_s=20)
        master.stop()
        task = store.get(run["subtask_ids"][0])
        return root, master, task

    def test_write_happens_through_the_registry(self):
        root, master, task = self._run(Config())
        path = os.path.join(root, "ws", "calc.py")
        self.assertTrue(os.path.isfile(path), "file was not written")
        self.assertIn("def add", read(path))
        # the write is evidence of the tool path, not a direct ws call
        changed = [e for e in master.events.recent(500)
                   if e["event_type"] == "file.changed" and e["detail"] == "calc.py"]
        self.assertTrue(changed)
        tools = [e.get("tool") for e in master.events.recent(500)
                 if e["event_type"] == "tool.invoke"]
        self.assertIn("fs.write", tools)
        self.assertIn(task["status"], ("completed", "reviewing", "done"))

    def test_read_only_ceiling_fails_loudly_and_writes_nothing(self):
        cfg = Config()
        cfg.tools.default_permissions = ["workspace:read", "system:info"]
        root, master, task = self._run(cfg)
        self.assertFalse(os.path.exists(os.path.join(root, "ws", "calc.py")))
        self.assertIn(task["status"], ("failed", "ready"))
        self.assertIn("refused", (task.get("last_error") or ""))

    def test_master_reports_tools(self):
        _, _, _, master, _ = harness()
        names = {t["name"] for t in master.tools_report()}
        self.assertIn("fs.write", names)
        self.assertIn("git.checkpoint", names)
        perms = master.tool_permissions("code_reviewer")
        self.assertNotIn("fs.write", perms["allowed"])


if __name__ == "__main__":
    unittest.main()
