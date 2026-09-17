"""Extract the files a model wrote from its reply.

Small models are inconsistent: they annotate the fence with a path, or only
with a language, or they use ``## FILE: path`` headers. This module is the
canonical parser used by both the core pipeline (``elysia.core.agents``) and
the compatibility worker (``orchestrator.brain`` / ``worker_local.py``).

Strategy:
  1. Prefer fences that carry a path annotation.
  2. Otherwise, if the number of pathless blocks equals the number of owned
     files, zip them in order.
  3. Otherwise, if exactly one owned file is unclaimed, join its blocks.
"""
from __future__ import annotations

import re

# fence with OPTIONAL path token after the language:
#   ```md docs/x.md\n<body>```   (path in group 2)
#   ```md\n<body>```             (empty group 2)
FENCE_RE = re.compile(r"```([\w.+-]*)[ \t]*([^\s`]*)[ \t]*\n(.*?)```", re.S)
FILEMARK_RE = re.compile(
    r"(?:^|\n)#{2,4}[ \t]*(?:FILE:|File:)[ \t]*`?([^\s`]+)`?[ \t]*\n+?(.*?)"
    r"(?=\n#{2,4}[ \t]*(?:FILE:|File:)|$)",
    re.S,
)

PATH_EXTS = (".md", ".ts", ".tsx", ".js", ".json", ".py", ".go", ".sh", ".yaml",
             ".yml", ".rs", ".toml", ".sql", ".css", ".html")


def parse_file_blocks(text: str, owned=None) -> dict:
    """Return ``{path: content}`` for the files the model emitted."""
    text = text or ""
    owned = [o for o in (owned or []) if isinstance(o, str) and o]
    files: dict[str, str] = {}
    candidates: list[tuple[str | None, str]] = []

    for m in FENCE_RE.finditer(text):
        tok, body = m.group(2).strip(), m.group(3)
        # some models fuse language + path into one token: "py f.py"
        words = tok.split()
        path = words[-1] if words else ""
        looks_like_path = bool(path) and (
            "/" in path or path.lower().endswith(PATH_EXTS))
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
