"""Kali / security tooling knowledge base for Elysia.

Answers the agent's questions "which tool does X?" and "how do I use Y
responsibly?" from curated, vendored docs in ``docs/knowledge/kali-tools/``.

Scope and stance (matches the repo's security posture):
  - DEFENSIVE-FIRST: descriptions emphasize legitimate, authorized use,
    installation and documentation — not attack execution.
  - Each entry carries category, purpose, safe/authorized usage summary,
    and install hints. Offensive "run this against a target" content is out
    of scope and stays out; ``elysia.core.skills`` already quarantines
    high-risk skills, and ``docs/security/SECURITY_TOOLING.md`` records the
    operator policy for installing real tooling on an authorized machine.

No third-party dependencies: discovery + keyword search are stdlib-only and
offline-first, like the rest of Elysia. ``Knowledge.for_context()`` gives the
agent a bounded digest of matching entries so answers cite the vendored docs
instead of hallucinating tool names or flags.
"""
from __future__ import annotations

import os
import re

from .config import repo_root

DOCS_DIR = os.path.join(repo_root(), "docs", "knowledge", "kali-tools")
MAX_QUERY_RESULTS = 5
MAX_CONTEXT_ENTRIES = 4
MAX_ENTRY_CHARS = 900


class Entry:
    """One vendored tool doc (front-matter parsed leniently, YAML-free)."""

    def __init__(self, name: str, path: str, meta: dict, body: str):
        self.name = name
        self.path = path
        self.meta = meta
        self.body = body

    @property
    def category(self) -> str:
        return str(self.meta.get("category", "general"))

    @property
    def purpose(self) -> str:
        return str(self.meta.get("purpose", ""))

    @property
    def package(self) -> str:
        return str(self.meta.get("package", self.name))

    @property
    def risk(self) -> str:
        return str(self.meta.get("risk", "low"))

    @property
    def aliases(self) -> list[str]:
        v = self.meta.get("aliases", [])
        if isinstance(v, str):
            v = [a.strip() for a in v.split(",") if a.strip()]
        return [str(a).lower() for a in (v or [])]

    def to_dict(self) -> dict:
        return {"name": self.name, "category": self.category,
                "purpose": self.purpose, "package": self.package,
                "risk": self.risk, "aliases": self.aliases,
                "path": self.path, "body": self.body}

    def summary(self, limit: int = MAX_ENTRY_CHARS) -> str:
        head = (f"{self.name} [{self.category}] — {self.purpose}\n"
                f"package: {self.package} | risk: {self.risk}\n")
        body = self.body.strip()
        if len(body) > limit:
            body = body[: limit - 3] + "..."
        return head + body


def _read_frontmatter(text: str) -> tuple[dict, str]:
    """Parse the lenient ``---`` key: value front matter (same style as skills)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            meta[k] = v
    return meta, m.group(2)


def load_all(docs_dir: str = DOCS_DIR) -> list[Entry]:
    """Load every vendored tool doc (bounded, offline, never raises)."""
    entries: list[Entry] = []
    if not os.path.isdir(docs_dir):
        return entries
    for fn in sorted(os.listdir(docs_dir)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(docs_dir, fn)
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        meta, body = _read_frontmatter(text)
        name = str(meta.get("name") or fn[:-3])
        entries.append(Entry(name=name, path=path, meta=meta, body=body))
    return entries


def search(query: str, entries: list[Entry] | None = None,
           limit: int = MAX_QUERY_RESULTS) -> list[dict]:
    """Keyword-scored search over the knowledge base (stdlib only).

    Scoring: name/alias matches weigh most, then purpose, then body. Returns
    best-first [{name, score, entry-dict}].
    """
    entries = entries if entries is not None else load_all()
    terms = [t for t in re.split(r"\W+", (query or "").lower()) if len(t) > 2]
    if not terms:
        return []
    scored = []
    for e in entries:
        hay_name = (e.name + " " + " ".join(e.aliases)).lower()
        hay_purpose = e.purpose.lower()
        hay_body = e.body.lower()
        score = 0
        for t in terms:
            if t in hay_name:
                score += 4
            if t in hay_purpose:
                score += 2
            if t in hay_body:
                score += 1
        if score:
            d = e.to_dict()
            scored.append({"name": e.name, "score": score, **d})
    scored.sort(key=lambda r: -r["score"])
    return scored[:limit]


def for_context(query: str, max_entries: int = MAX_CONTEXT_ENTRIES) -> str:
    """Bounded digest of matching knowledge for an agent prompt layer.

    Empty string when nothing matches — the layer is simply omitted.
    """
    hits = search(query, limit=max_entries)
    if not hits:
        return ""
    parts = ["Authorized-use security tooling knowledge (from vendored docs; "
             "use only on systems you own or have written permission to "
             "test):"]
    for h in hits:
        e = Entry(name=h["name"], path=h["path"],
                  meta={"category": h["category"], "purpose": h["purpose"],
                        "package": h["package"], "risk": h["risk"]},
                  body=h["body"])
        parts.append(e.summary())
    return "\n\n".join(parts)


def stats(docs_dir: str = DOCS_DIR) -> dict:
    entries = load_all(docs_dir)
    by_cat: dict[str, int] = {}
    for e in entries:
        by_cat[e.category] = by_cat.get(e.category, 0) + 1
    return {"entries": len(entries), "categories": by_cat, "dir": docs_dir}
