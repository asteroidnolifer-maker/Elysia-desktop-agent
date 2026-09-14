"""Provider presets — one catalog, many AI backends.

Elysia is provider-agnostic: the local llama.cpp/Ollama server is just one
entry. This module is the curated catalog of everything else Elysia can talk
to out of the box:

  - Cloud OpenAI-compatible APIs (OpenRouter, Groq, Together, DeepSeek,
    Mistral, xAI, NVIDIA NIM, GitHub Models, Cerebras, Google Gemini,
    HuggingFace Inference)
  - Freebuff-style gateways (any OpenAI-compatible base URL + key you own)
  - CLI coding agents installed on this machine (Claude Code ``claude``,
    OpenAI ``codex``, Google ``gemini``, ``opencode``, ``openclaw``) —
    they reuse whatever login those tools already have

Activation model (offline-first, zero surprise):
  - the repo config (``elysia/config.json``) is always loaded first
  - a preset activates ONLY when its credential env var is set
    (API providers) or its binary is found on PATH (CLI providers)
  - ``missing_requirements(name)`` tells the operator exactly what to export
  - nothing here ever raises; a provider that is not configured is simply
    absent from the runtime set

Security: keys are read from the environment only and never logged, never
written to disk by this module, and are redacted by ``config.redact_config``.
"""
from __future__ import annotations

import os
import shutil

from .config import ProviderConfig

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
# Each entry:
#   kind          provider transport (openai | cli)
#   label         runtime name (dedupe key)
#   base_url      OpenAI-compatible base URL, or CLI command prefix
#   model         default model id (edit freely via config/env)
#   capabilities  routing capabilities for the scheduler
#   env           credential env vars (first one present wins; all listed in docs)
#   env_url       optional env var overriding base_url
#   env_model     optional env var overriding the default model
#   bin           (cli kind) binary checked on PATH
#   docs          where to get a key / install the CLI
#   priority      lower is tried first within the activated set

CATALOG: dict[str, dict] = {
    # ---- cloud OpenAI-compatible APIs -------------------------------------
    "openrouter": {
        "kind": "openai", "label": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openrouter/auto",
        "capabilities": ["chat", "coding", "reasoning", "tool_calling",
                         "long_context"],
        "env": ["OPENROUTER_API_KEY"], "env_model": "OPENROUTER_MODEL",
        "docs": "https://openrouter.ai/keys", "priority": 10,
    },
    "groq": {
        "kind": "openai", "label": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "capabilities": ["chat", "coding", "reasoning", "streaming"],
        "env": ["GROQ_API_KEY"], "env_model": "GROQ_MODEL",
        "docs": "https://console.groq.com/keys", "priority": 11,
    },
    "together": {
        "kind": "openai", "label": "together",
        "base_url": "https://api.together.xyz/v1",
        "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "capabilities": ["chat", "coding", "reasoning"],
        "env": ["TOGETHER_API_KEY"], "env_model": "TOGETHER_MODEL",
        "docs": "https://api.together.xyz/settings/api-keys", "priority": 12,
    },
    "deepseek": {
        "kind": "openai", "label": "deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "capabilities": ["chat", "coding", "reasoning"],
        "env": ["DEEPSEEK_API_KEY"], "env_model": "DEEPSEEK_MODEL",
        "docs": "https://platform.deepseek.com/api_keys", "priority": 13,
    },
    "mistral": {
        "kind": "openai", "label": "mistral",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-large-latest",
        "capabilities": ["chat", "coding", "reasoning"],
        "env": ["MISTRAL_API_KEY"], "env_model": "MISTRAL_MODEL",
        "docs": "https://console.mistral.ai/api-keys", "priority": 14,
    },
    "xai": {
        "kind": "openai", "label": "xai",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-3",
        "capabilities": ["chat", "coding", "reasoning"],
        "env": ["XAI_API_KEY"], "env_model": "XAI_MODEL",
        "docs": "https://console.x.ai", "priority": 15,
    },
    "nim": {
        "kind": "openai", "label": "nim",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "meta/llama-3.3-70b-instruct",
        "capabilities": ["chat", "coding", "reasoning"],
        "env": ["NVIDIA_API_KEY", "NIM_API_KEY"], "env_model": "NIM_MODEL",
        "docs": "https://build.nvidia.com", "priority": 16,
    },
    "github-models": {
        "kind": "openai", "label": "github-models",
        "base_url": "https://models.github.ai/inference",
        "model": "openai/gpt-4o-mini",
        "capabilities": ["chat", "coding", "reasoning"],
        "env": ["GITHUB_TOKEN", "GH_TOKEN", "GITHUB_MODELS_TOKEN"],
        "env_model": "GITHUB_MODELS_MODEL",
        "docs": "https://github.com/marketplace/models", "priority": 17,
    },
    "cerebras": {
        "kind": "openai", "label": "cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b",
        "capabilities": ["chat", "coding", "streaming"],
        "env": ["CEREBRAS_API_KEY"], "env_model": "CEREBRAS_MODEL",
        "docs": "https://cloud.cerebras.ai", "priority": 18,
    },
    "gemini": {
        "kind": "openai", "label": "gemini-api",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "capabilities": ["chat", "coding", "reasoning", "vision",
                         "long_context"],
        "env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "env_model": "GEMINI_MODEL",
        "docs": "https://aistudio.google.com/apikey", "priority": 19,
    },
    # ---- Freebuff-style gateway (bring your own OpenAI-compatible URL) ----
    "freebuff": {
        "kind": "openai", "label": "freebuff",
        "base_url": "",  # required: ELYSIA_FREEBUFF_BASE_URL
        "model": "freebuff-default",
        "capabilities": ["chat", "coding", "reasoning"],
        "env": ["ELYSIA_FREEBUFF_KEY", "FREEBUFF_API_KEY"],
        "env_url": "ELYSIA_FREEBUFF_BASE_URL",
        "env_model": "ELYSIA_FREEBUFF_MODEL",
        "docs": "set ELYSIA_FREEBUFF_BASE_URL + ELYSIA_FREEBUFF_KEY",
        "priority": 9,
    },
    # ---- CLI coding agents (reuse the login the tool already has) ---------
    "claude-code": {
        "kind": "cli", "label": "claude-code",
        "base_url": "claude -p", "bin": "claude",
        "model": "claude-code",
        "capabilities": ["chat", "coding", "reasoning", "tool_calling",
                         "file_access"],
        "docs": "https://docs.anthropic.com/en/docs/claude-code",
        "priority": 40,
    },
    "codex": {
        "kind": "cli", "label": "codex",
        "base_url": "codex exec", "bin": "codex",
        "model": "codex",
        "capabilities": ["chat", "coding", "reasoning", "file_access"],
        "docs": "https://github.com/openai/codex", "priority": 41,
    },
    "gemini-cli": {
        "kind": "cli", "label": "gemini-cli",
        "base_url": "gemini -p", "bin": "gemini",
        "model": "gemini-cli",
        "capabilities": ["chat", "coding", "reasoning", "file_access"],
        "docs": "https://github.com/google-gemini/gemini-cli", "priority": 42,
    },
    "opencode": {
        "kind": "cli", "label": "opencode",
        "base_url": "opencode run", "bin": "opencode",
        "model": "opencode",
        "capabilities": ["chat", "coding", "file_access"],
        "docs": "https://opencode.ai", "priority": 43,
    },
    "openclaw": {
        "kind": "cli", "label": "openclaw",
        "base_url": "openclaw ask", "bin": "openclaw",
        "model": "openclaw",
        "capabilities": ["chat", "coding", "file_access"],
        "docs": "https://openclaw.ai (community CLI)", "priority": 44,
    },
}


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

def _first_env(names: list) -> str:
    for n in names or ():
        v = os.environ.get(n, "")
        if v:
            return v
    return ""


def missing_requirements(name: str) -> list[str]:
    """What is missing to activate preset ``name`` (empty list = ready)."""
    entry = CATALOG.get(name)
    if not entry:
        return [f"unknown provider preset: {name}"]
    missing = []
    if entry["kind"] == "cli":
        if not shutil.which(entry["bin"]):
            missing.append(f"CLI binary not on PATH: {entry['bin']} "
                           f"(install per {entry['docs']})")
        return missing
    if not _first_env(entry["env"]):
        missing.append(f"set one of {entry['env']} (get a key: {entry['docs']})")
    if entry.get("env_url") and not os.environ.get(entry["env_url"]):
        if not entry.get("base_url"):
            missing.append(f"set {entry['env_url']}")
    return missing


def is_ready(name: str) -> bool:
    return not missing_requirements(name)


def resolve_provider(name: str) -> ProviderConfig | None:
    """Build a ProviderConfig for ``name``; None when not configured."""
    entry = CATALOG.get(name)
    if not entry or missing_requirements(name):
        return None
    model = os.environ.get(entry.get("env_model", ""), "") or entry["model"]
    base = entry.get("base_url", "")
    if entry.get("env_url"):
        base = os.environ.get(entry["env_url"], "") or base
    return ProviderConfig(
        kind=entry["kind"],
        label=entry["label"],
        base_url=base,
        api_key=_first_env(entry["env"]) if entry["kind"] == "openai" else "",
        model=model,
        capabilities=list(entry["capabilities"]),
        concurrency=2 if entry["kind"] == "openai" else 1,
        timeout_s=120 if entry["kind"] == "cli" else 300,
        max_tokens=2048,
        priority=entry["priority"],
    )


def _pname(p) -> str:
    """Runtime dedupe key for a ProviderConfig (label first)."""
    return p.label or f"{p.kind}:{p.model}"


def load_provider_configs(cfg_providers=None, extra: list | None = None) -> list:
    """The runtime provider set: repo config first, then activated presets.

    Order (and therefore failover order): config providers (local first),
    then cloud presets by priority, then CLI agents. ``extra`` force-tries
    additional preset names (they still need their credentials to activate).
    Dedupe by runtime name keeps config overrides authoritative.
    """
    out: list = []
    seen: set[str] = set()
    for p in (cfg_providers or []):
        out.append(p)
        seen.add(_pname(p))
    names = sorted(CATALOG,
                   key=lambda n: (CATALOG[n]["priority"], n))
    if extra:
        names = [n for n in names if n not in extra] + [n for n in extra
                                                        if n in CATALOG]
    for name in names:
        pcfg = resolve_provider(name)
        if pcfg is None or _pname(pcfg) in seen:
            continue
        out.append(pcfg)
        seen.add(_pname(pcfg))
    return out


def describe() -> list[dict]:
    """Catalog summary for the CLI/UI: state, what is missing, no secrets."""
    rows = []
    for name, e in sorted(CATALOG.items(), key=lambda kv:
                          (kv[1]["priority"], kv[0])):
        ready = is_ready(name)
        rows.append({
            "name": name,
            "kind": e["kind"],
            "model": e["model"],
            "capabilities": list(e["capabilities"]),
            "ready": ready,
            "missing": missing_requirements(name),
            "docs": e["docs"],
            "priority": e["priority"],
        })
    return rows
