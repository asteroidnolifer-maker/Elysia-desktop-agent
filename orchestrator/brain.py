#!/usr/bin/env python3
"""
Elysia brain.py — shared LLM runtime for all agents (multi-provider).

Backward-compatible wrapper over ``elysia.core.providers`` so existing callers
(worker_local.py, server.py, ask.sh) keep working unchanged, while the actual
backend is now dynamic: local llama.cpp/Ollama is just ONE provider among many
(OpenAI-compatible APIs, NVIDIA NIM, CLI providers).

Responsibilities:
  - chat(): call the selected model via the provider abstraction
  - parse_file_blocks(): extract files the model wrote
  - qa_check(): language-aware verification via elysia.core.qa
  - CLI: `brain.py ask "prompt"` = one-shot answer (ask.sh uses this)
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from elysia.core.config import load_config  # noqa: E402
from elysia.core.prompts import get_style, system_prompt  # noqa: E402
from elysia.core.qa import validate_file  # noqa: E402

MODEL = os.environ.get("ELYSIA_MODEL", "qwen2.5-coder:7b")
LLAMA_URL = os.environ.get("ELYSIA_LLM_URL", "http://127.0.0.1:11434/v1")

# The worker contract (byte-identical to the original contract; now the
# "elysia" prompt style). Other styles: claude-code, hermes, openhands,
# research — see elysia/core/prompts.py and `elysia prompt list`.
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

# fence with OPTIONAL path token after the language:
#   ```md docs/x.md\n<body>```   (path in group 2)
#   ```md\n<body>```             (empty group 2)
FENCE_RE = re.compile(r"```([\w.+-]*)[ \t]*([^\s`]*)[ \t]*\n(.*?)```", re.S)
FILEMARK_RE = re.compile(
    r"(?:^|\n)#{2,4}[ \t]*(?:FILE:|File:)[ \t]*`?([^\s`]+)`?[ \t]*\n+?(.*?)(?=\n#{2,4}[ \t]*(?:FILE:|File:)|\Z)",
    re.S,
)


_MANAGER = None          # process-global manager (concurrency accounting)
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
    global _MANAGER, _MANAGER_SIG
    from elysia.core.config import ProviderConfig
    from elysia.core.providers import ProviderManager
    cfg = load_config()
    sig = _provider_sig(cfg)
    if _MANAGER is None or sig != _MANAGER_SIG:
        pm = ProviderManager()
        if cfg.providers:
            pm.register_many(cfg.providers)
        else:
            pm.register(ProviderConfig(kind="openai", label="local",
                                       model=MODEL, base_url=LLAMA_URL))
        _MANAGER, _MANAGER_SIG = pm, sig
    return _MANAGER


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


def parse_file_blocks(text, owned=None):
    """Extract {path: content} from the model reply.

    Small models often omit the path after the fence (```md instead of
    ```md docs/x.md). Strategy:
      1. Prefer fences that carry a path annotation.
      2. Otherwise, if exactly one owned file -> first fenced block goes there.
      3. Otherwise, if block count == owned count -> zip in order.
    """
    text = text or ""
    owned = [o for o in (owned or []) if isinstance(o, str) and o]
    files = {}
    candidates = []  # (path_or_None, body)
    EXTS = (".md", ".ts", ".tsx", ".js", ".json", ".py", ".go", ".sh", ".yaml", ".yml")
    for m in FENCE_RE.finditer(text):
        tok, body = m.group(2).strip(), m.group(3)
        # some models fuse language + path into one token: "py f.py"
        words = tok.split()
        path = words[-1] if words else ""
        # treat the token after the language as a path only if it looks like one
        looks_like_path = bool(path) and (
            "/" in path or path.lower().endswith(EXTS))
        candidates.append((path if looks_like_path else None, body))
    if not candidates:
        for m in FILEMARK_RE.finditer(text):
            candidates.append((m.group(1).strip(), m.group(2)))
        # salvage: unclosed final fence (output truncated mid-block)
        if not candidates and "```" in text:
            tail = text.rsplit("```", 1)[-1]
            tail = tail.split("\n", 1)[-1] if "\n" in tail else tail
            if tail.strip():
                candidates.append((None, tail))

    # 1) annotated blocks
    for path, body in candidates:
        if path and body.strip():
            files[path] = body

    # 2/3) map pathless blocks onto owned files
    pathless = [b for p, b in candidates if not p and b.strip()]
    if owned and pathless:
        unclaimed = [o for o in owned if not any(
            o == p or p.endswith("/" + o) or o.endswith("/" + p)
            for p in files)]
        if len(unclaimed) == len(pathless):
            for o, b in zip(unclaimed, pathless):
                files[o] = b
        elif len(unclaimed) == 1:
            # model emitted several snippets for one file: join non-trivial
            # blocks in order (small fragments are usually parts of the file)
            solid = [b for b in pathless if len(b.strip()) > 40] or pathless
            files[unclaimed[0]] = "\n\n".join(b.strip("\n") for b in solid)

    return {p: c.strip("\n") + "\n" for p, c in files.items()}


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
