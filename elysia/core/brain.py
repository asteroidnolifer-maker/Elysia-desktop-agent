#!/usr/bin/env python3
"""
Elysia brain.py — shared LLM runtime for all agents (multi-provider).

Backward-compatible wrapper over ``elysia.core.providers`` so existing callers
(worker_local.py, server.py, ask.sh) keep working unchanged, while the actual
backend is now dynamic: local llama.cpp/Ollama is just ONE provider among many
(OpenAI-compatible APIs, NVIDIA NIM, CLI providers).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elysia.core.fileblocks import (  # noqa: E402
    FENCE_RE, FILEMARK_RE, parse_file_blocks)
from elysia.core.prompts import get_style, system_prompt  # noqa: E402
from elysia.core.qa import validate_file  # noqa: E402
from elysia.core.config import load_config  # noqa: E402

MODEL = os.environ.get("ELYSIA_MODEL", "qwen2.5-coder:7b")
LLAMA_URL = os.environ.get("ELYSIA_LLM_URL", "http://127.0.0.1:11434/v1")

# The worker contract (byte-identical to the original contract; now the
# "elysia" prompt style). Other styles: claude-code, hermes, openhands,
# research — see elysia.core.prompts.py and `elysia prompt list`.
SYSTEM_PROMPT = system_prompt("elysia")


def chat_style(messages, style: str | None = None, max_tokens=2048,
               temperature=0.2, timeout=900, provider=None):
    """chat() with a prompt style injected as the system message.

    ``style`` defaults to ELYSIA_PROMPT_STYLE (or the elysia contract).
    ``messages`` should be role/content pairs WITHOUT a system message;
    the style's system prompt is prepended automatically.
    """
    msgs = list(messages or [])
    if msgs and msgs[0].get("role") == "system":
        msgs = msgs[1:]
    msgs.insert(0, {"role": "system", "content": system_prompt(style)})
    return chat(msgs, max_tokens=max_tokens, temperature=temperature,
                timeout=timeout, provider=provider)


# The file-block parser is canonical in elysia.core.fileblocks (re-exported
# here so legacy callers keep working unchanged).


# Module-level manager instance (for test patching)
_manager_instance = None
_manager_override = None  # Tests can set this to override the manager
_MANAGER_SIG = None


def _provider_sig(cfg):
    """Tuple identifying the configured provider set (cache key)."""
    return tuple((p.kind, p.label, p.model, p.base_url, p.concurrency)
                 for p in (cfg.providers or []))


def _manager():
    """Build (once) a ProviderManager from ALL configured providers.

    Memoized: one shared manager per process so concurrency caps and failover
    counters apply across concurrent calls — this is the single canonical AI
    execution seam. Rebuilds only when the provider set changes.
    """
    global _manager_instance, _manager_override, _MANAGER_SIG
    # Allow tests to override the manager completely
    # Check orchestrator.brain._manager first (legacy test patching)
    # Then check both local _manager_override and orchestrator.brain._manager_override
    import sys
    if 'orchestrator.brain' in sys.modules:
        orch_brain = sys.modules['orchestrator.brain']
        if getattr(orch_brain, '_manager', None) is not None:
            return orch_brain._manager
        if getattr(orch_brain, '_manager_override', None) is not None:
            return orch_brain._manager_override
    if _manager_override is not None:
        return _manager_override
    from elysia.core.config import ProviderConfig
    from elysia.core.providers import ProviderManager
    cfg = load_config()
    sig = _provider_sig(cfg)
    if _manager_instance is None or sig != _MANAGER_SIG:
        pm = ProviderManager()
        if cfg.providers:
            pm.register_many(cfg.providers)
        else:
            pm.register(ProviderConfig(kind="openai", label="local",
                                       model=MODEL, base_url=LLAMA_URL))
        _manager_instance, _MANAGER_SIG = pm, sig
    return _manager_instance


def chat(messages, max_tokens=2048, temperature=0.2, timeout=900, provider=None):
    """One chat call through the provider abstraction. Returns (text, error).

    Default path is ProviderManager.execute (capability-aware, with failover).
    An explicit ``provider`` bypasses the manager for single-provider callers.
    """
    if provider is not None:
        return provider.chat(messages, max_tokens=max_tokens,
                             temperature=temperature, timeout=timeout)
    return _manager().execute(messages, capabilities=["chat"],
                              max_tokens=max_tokens, temperature=temperature,
                              timeout=timeout)


def qa_check(path, content):
    """Language-aware verification of a written file.
    Returns (ok, reason). Delegates to elysia.core.qa.validate_file.
    """
    if not content or not content.strip():
        return False, "empty content"
    return validate_file(path, content)


def health():
    """True if ANY configured provider's API answers."""
    pm = _manager()
    return any(p.check_health() == "healthy" for p in pm.list())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ask"
    if cmd == "ask":
        args = sys.argv[2:]
        style = None
        if args and args[0] == "--style":
            style = args[1]
            args = args[2:]
        prompt = " ".join(args) or sys.stdin.read()
        text, err = chat_style([{"role": "user", "content": prompt}],
                               style=style, max_tokens=1024)
        if err:
            print(f"[error] {err}", file=sys.stderr)
            sys.exit(1)
        print(text)
    elif cmd == "health":
        print("UP" if health() else "DOWN")
        sys.exit(0 if health() else 1)