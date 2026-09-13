#!/usr/bin/env python3
"""
Elysia brain.py — shared local-LLM runtime for all agents.

NO opencode. NO third-party AI. Talks only to the local llama-server
(OpenAI-compatible API on 127.0.0.1:11434).

Responsibilities:
  - chat(): call the local model
  - parse_file_blocks(): extract files the model wrote
  - qa_check(): automatic verification (JSON parse, py compile, brace balance)
  - CLI: `brain.py ask "prompt"` = one-shot local answer (ask.sh uses this)
"""
import json
import re
import sys
import urllib.request

LLAMA_URL = "http://127.0.0.1:11434/v1/chat/completions"
MODEL = "qwen2.5-coder:7b"

SYSTEM_PROMPT = (
    "You are a precise coding agent working offline. "
    "When asked to create or edit files, output each file as a fenced code block "
    "whose opening fence line ends with the file path, like:\n"
    "```ts src/foo.ts\n"
    "<full file content>\n"
    "```\n"
    "Output ONLY file blocks (plus at most one short sentence before them). "
    "Never truncate content. No explanations after the blocks."
)

# fence with OPTIONAL path token after the language:
#   ```md docs/x.md\n<body>```   (path in group 2)
#   ```md\n<body>```             (empty group 2)
FENCE_RE = re.compile(r"```([\w.+-]*)[ \t]*([^\s`]*)[ \t]*\n(.*?)```", re.S)
FILEMARK_RE = re.compile(
    r"(?:^|\n)#{2,4}[ \t]*(?:FILE:|File:)[ \t]*`?([^\s`]+)`?[ \t]*\n+?(.*?)(?=\n#{2,4}[ \t]*(?:FILE:|File:)|\Z)",
    re.S,
)


def chat(messages, max_tokens=2048, temperature=0.2, timeout=900):
    """One local-model chat call. Returns (text, error)."""
    payload = json.dumps({
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        LLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        text = data["choices"][0]["message"]["content"]
        return text, ""
    except Exception as e:
        return "", str(e)


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
        # treat the token after the language as a path only if it looks like one
        looks_like_path = bool(tok) and ("/" in tok or tok.lower().endswith(EXTS))
        candidates.append((tok if looks_like_path else None, body))
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
    """Automatic verification of a written file. Returns (ok, reason)."""
    if not content or not content.strip():
        return False, "empty content"
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "json":
        try:
            json.loads(content)
        except Exception as e:
            return False, f"invalid JSON: {e}"
    elif ext == "py":
        try:
            compile(content, path, "exec")
        except SyntaxError as e:
            return False, f"python syntax error: {e}"
    elif ext in ("ts", "tsx", "js", "jsx", "go"):
        # crude balance check (strings/comments can fool it, catches gross damage)
        for a, b in (("{", "}"), ("(", ")"), ("[", "]")):
            if content.count(a) - content.count(b) > 3:
                return False, f"unbalanced {a}{b}"
    elif ext == "md":
        body = content.lstrip()
        if len(body) < 30:
            return False, "markdown too short"
        if "TODO_FILL" in content or "<content>" in content:
            return False, "placeholder left in file"
        # raw JSON dumps are not markdown documents
        if body.startswith(("{", "[")):
            try:
                json.loads(body)
                return False, "raw JSON dump, not a markdown document"
            except Exception:
                pass
        # real markdown starts with a heading or bulleted/titled text
        head = "\n".join(content.splitlines()[:10])
        if not re.search(r"^#+\s", head, re.M):
            return False, "missing a markdown heading (start with '# ')"
    return True, ""


def health():
    """True if the local model API answers."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/v1/models", timeout=5):
            return True
    except Exception:
        return False


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "ask"
    if cmd == "ask":
        prompt = " ".join(sys.argv[2:]) or sys.stdin.read()
        text, err = chat([{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": prompt}], max_tokens=1024)
        if err:
            print(f"[error] {err}", file=sys.stderr)
            sys.exit(1)
        print(text)
    elif cmd == "health":
        print("UP" if health() else "DOWN")
        sys.exit(0 if health() else 1)
