"""Tests for the provider-ecosystem + knowledge + prompt-style additions.

Offline and hermetic: credential env vars are always set via mocks so the
host's real keys never influence results, and no network is touched.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from elysia.core import browser_login as bl
from elysia.core import hf as hf_mod
from elysia.core import knowledge as kb
from elysia.core import prompts as prompts_mod
from elysia.core import provider_presets as pp
from elysia.core.config import load_config

# Env vars the presets read — cleared for hermetic tests.
CREDENTIAL_ENV = [
    "OPENROUTER_API_KEY", "GROQ_API_KEY", "HF_TOKEN",
    "ELYSIA_FREEBUFF_KEY", "ELYSIA_FREEBUFF_BASE_URL",
    "ELYSIA_DISABLE_PRESETS", "ELYSIA_PROMPT_STYLE",
]


def clean_env():
    """Decorator factory: run the test with credential env vars cleared."""
    def decorator(fn):
        def wrapper(*a, **kw):
            saved = {k: os.environ.get(k) for k in CREDENTIAL_ENV}
            for k in CREDENTIAL_ENV:
                os.environ.pop(k, None)
            try:
                return fn(*a, **kw)
            finally:
                for k, v in saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator


class ProviderPresetTests(unittest.TestCase):
    @clean_env()
    def test_preset_inactive_without_credentials(self):
        self.assertFalse(pp.is_ready("openrouter"))
        self.assertIsNotNone(pp.missing_requirements("openrouter"))
        self.assertIsNone(pp.resolve_provider("openrouter"))

    @clean_env()
    def test_preset_activates_with_env_key(self):
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        pcfg = pp.resolve_provider("openrouter")
        self.assertIsNotNone(pcfg)
        self.assertEqual(pcfg.label, "openrouter")
        self.assertEqual(pcfg.base_url, "https://openrouter.ai/api/v1")
        # freebuff needs URL + key
        self.assertFalse(pp.is_ready("freebuff"))
        os.environ["ELYSIA_FREEBUFF_KEY"] = "k"
        os.environ["ELYSIA_FREEBUFF_BASE_URL"] = "https://gw.example/v1"
        fb = pp.resolve_provider("freebuff")
        self.assertIsNotNone(fb)
        self.assertEqual(fb.base_url, "https://gw.example/v1")

    def test_cli_preset_needs_binary(self):
        # readiness follows PATH regardless of what this machine has installed
        with mock.patch.object(pp.shutil, "which", return_value=None):
            self.assertFalse(pp.is_ready("claude-code"))
            self.assertIsNone(pp.resolve_provider("claude-code"))
        with mock.patch.object(pp.shutil, "which", return_value="/usr/bin/claude"):
            self.assertTrue(pp.is_ready("claude-code"))
            pcfg = pp.resolve_provider("claude-code")
        self.assertEqual(pcfg.kind, "cli")
        self.assertEqual(pcfg.base_url, "claude -p")

    @clean_env()
    def test_load_merges_into_config_providers(self):
        os.environ["GROQ_API_KEY"] = "k"
        cfg = load_config(include_presets=False)
        self.assertEqual([p.label for p in cfg.providers], ["local"])
        merged = pp.load_provider_configs(cfg.providers)
        names = [p.label for p in merged]
        self.assertEqual(names[0], "local")           # repo config stays first
        self.assertIn("groq", names)
        # local wins dedupe
        self.assertEqual(names.count("local"), 1)

    @clean_env()
    def test_describe_has_no_secrets(self):
        os.environ["OPENROUTER_API_KEY"] = "supersecret"
        rows = pp.describe()
        blob = repr(rows)
        self.assertNotIn("supersecret", blob)
        by = {r["name"]: r for r in rows}
        self.assertTrue(by["openrouter"]["ready"])


class ConfigPresetIntegrationTests(unittest.TestCase):
    @clean_env()
    def test_load_config_appends_activated_presets(self):
        os.environ["GROQ_API_KEY"] = "k"
        cfg = load_config()  # include_presets defaults True
        names = [p.label for p in cfg.providers]
        self.assertEqual(names[0], "local")
        self.assertIn("groq", names)

    @clean_env()
    def test_disable_presets_env_flag(self):
        os.environ["GROQ_API_KEY"] = "k"
        os.environ["ELYSIA_DISABLE_PRESETS"] = "1"
        cfg = load_config()
        self.assertEqual([p.label for p in cfg.providers], ["local"])

    @clean_env()
    def test_hf_inference_provider_attached(self):
        os.environ["HF_TOKEN"] = "hf_test"
        cfg = load_config()
        names = [p.label for p in cfg.providers]
        self.assertIn("hf-inference", names)


class PromptStyleTests(unittest.TestCase):
    def test_default_is_worker_contract(self):
        self.assertIn("fenced code block", prompts_mod.system_prompt("elysia"))
        self.assertIn("Output ONLY file blocks", prompts_mod.system_prompt("elysia"))

    def test_unknown_style_falls_back(self):
        sp = prompts_mod.system_prompt("no-such-style")
        self.assertEqual(sp, prompts_mod.system_prompt("elysia"))

    def test_styles_have_discipline(self):
        for name in ("claude-code", "hermes", "openhands"):
            sp = prompts_mod.system_prompt(name)
            self.assertIn("fewest changes", sp)
            self.assertIn("forbidden", sp)

    @clean_env()
    def test_env_selects_style(self):
        os.environ["ELYSIA_PROMPT_STYLE"] = "claude-code"
        self.assertIn("Claude Code", prompts_mod.system_prompt())

    def test_brain_system_prompt_unchanged_contract(self):
        # worker safety: the elysia style must keep the original contract lines
        import orchestrator.brain as brain
        self.assertIn("Never truncate content", brain.SYSTEM_PROMPT)
        self.assertIn("```ts src/foo.ts", brain.SYSTEM_PROMPT)


class BrowserLoginTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "providers.env")
        try:
            bl.save_key("openrouter", "OPENROUTER_API_KEY", "abc'quote", path)
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("OPENROUTER_API_KEY", None)
                n = bl.load_env_file(path)
                self.assertEqual(n, 1)
                self.assertEqual(os.environ["OPENROUTER_API_KEY"], "abc'quote")
                os.environ.pop("OPENROUTER_API_KEY", None)
            # second save replaces, not appends
            bl.save_key("openrouter", "OPENROUTER_API_KEY", "newkey", path)
            body = open(path).read()
            self.assertEqual(body.count("OPENROUTER_API_KEY="), 1)
            self.assertIn("newkey", body)
            mode = os.stat(path).st_mode & 0o777
            self.assertEqual(mode, 0o600)
        finally:
            os.remove(path)
            os.rmdir(d)

    def test_environment_wins_over_stored(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "p.env")
        try:
            bl.save_key("groq", "GROQ_API_KEY", "stored", path)
            with mock.patch.dict(os.environ, {"GROQ_API_KEY": "envvalue"}):
                bl.load_env_file(path)
                self.assertEqual(os.environ["GROQ_API_KEY"], "envvalue")
        finally:
            os.remove(path)
            os.rmdir(d)

    def test_stored_status_no_secrets(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "p.env")
        try:
            bl.save_key("groq", "GROQ_API_KEY", "sekrit", path)
            st = bl.stored_status(path)
            self.assertEqual(st["stored"], {"GROQ_API_KEY": "groq"})
            self.assertNotIn("sekrit", repr(st))
        finally:
            os.remove(path)
            os.rmdir(d)

    def test_login_unknown_provider(self):
        res = bl.login("not-a-provider", no_browser=True)
        self.assertFalse(res["ok"])

    def test_cli_login_end_to_end(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "p.env")
        try:
            from elysia import cli as cli_mod
            with mock.patch.object(bl, "ENV_FILE", path):
                rc = cli_mod.main(["login", "groq", "--paste", "gsk_x",
                                   "--no-browser"])
                self.assertEqual(rc, 0)
                self.assertTrue(os.path.isfile(path))
                rc2 = cli_mod.main(["login", "--status"])
        finally:
            if os.path.isfile(path):
                os.remove(path)
            os.rmdir(d)

    def test_login_cli_provider_reports_install(self):
        res = bl.login("claude-code", no_browser=True)
        self.assertIn("install", res["message"].lower())

    @clean_env()
    def test_login_paste_stores_key(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "p.env")
        try:
            with mock.patch.object(bl, "ENV_FILE", path):
                res = bl.login("groq", paste_value="gsk_test",
                               no_browser=True)
                self.assertTrue(res["ok"], res)
                self.assertTrue(os.path.isfile(path))
                # empty paste is rejected without writing anything
                res2 = bl.login("groq", paste_value="   ", no_browser=True)
            self.assertFalse(res2.get("ok", True))
            self.assertIn("stored", res.get("message", ""))
        finally:
            if os.path.isfile(path):
                os.remove(path)
            os.rmdir(d)


class KnowledgeTests(unittest.TestCase):
    def test_loads_vendored_docs(self):
        entries = kb.load_all()
        names = {e.name for e in entries}
        self.assertIn("nmap", names)
        self.assertIn("metasploit", names)
        self.assertGreaterEqual(len(entries), 8)

    def test_search_by_alias(self):
        hits = kb.search("port scanner")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["name"], "nmap")

    def test_search_risk_fields(self):
        hits = {h["name"]: h for h in kb.search("sql injection")}
        self.assertIn("sqlmap", hits)
        self.assertEqual(hits["sqlmap"]["risk"], "high")

    def test_context_digest_bounded_and_defensive(self):
        digest = kb.for_context("scan my own network ports")
        self.assertIn("authorized", digest.lower())
        self.assertLess(len(digest), 6000)

    def test_no_match_gives_empty_context(self):
        self.assertEqual(kb.for_context("q"), "")

    def test_stats(self):
        st = kb.stats()
        self.assertGreaterEqual(st["entries"], 8)
        self.assertIn("recon", st["categories"])


class HuggingFaceTests(unittest.TestCase):
    def test_catalog_shape(self):
        for m in hf_mod.MODELS.values():
            self.assertIn("repo", m)
            self.assertIn("gguf", m)
            self.assertIn("size_mb", m)
        for d in hf_mod.DATASETS.values():
            self.assertTrue(d["url"].startswith("https://huggingface.co/"))

    def test_recommend_prefers_largest_fit(self):
        self.assertEqual(hf_mod.recommend(800), "qwen2.5-1.5b")
        self.assertEqual(hf_mod.recommend(5000), "granite-3.1-8b")  # 4900MB fits
        self.assertEqual(hf_mod.recommend(2400), "phi-4-mini")  # 2400 <= 2400

    def test_inference_provider_needs_token(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HF_TOKEN", None)
            self.assertIsNone(hf_mod.inference_provider())
            os.environ["HF_TOKEN"] = "hf_x"
            p = hf_mod.inference_provider()
        self.assertEqual(p.label, "hf-inference")
        self.assertEqual(p.base_url, hf_mod.HF_INFER_URL)

    def test_resolve_offline_degrades(self):
        res = hf_mod.resolve("this-repo/does-not-exist-xyz", timeout_s=3)
        self.assertFalse(res["ok"])
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
