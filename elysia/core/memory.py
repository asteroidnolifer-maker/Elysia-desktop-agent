"""Structured, layered persistent memory for Elysia.

Separates intentional concerns:
  - short-term task context (per task/run)
  - long-term project memory (decisions, architecture notes)
  - user preferences
  - agent memory (per logical role)
  - provider state
  - execution history (audit trail)

Not one giant JSON blob: each memory is its own JSON file under a scoped
namespace; search is keyword-based (fast, dependency-free); size limits and a
compaction routine stop unbounded growth and corruption.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time


def _now() -> float:
    return time.time()


class MemoryStore:
    """Namespaced key-value memory with search + compaction.

    Layout: <dir>/<namespace>/<key>.json  (key sanitised).
    """

    def __init__(self, state_dir: str, max_entries: int = 20000,
                 namespace: str = "memory"):
        self.dir = os.path.join(state_dir, namespace)
        os.makedirs(self.dir, exist_ok=True)
        self.max_entries = max_entries

    def _ns_dir(self, ns: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", ns)
        d = os.path.join(self.dir, safe)
        os.makedirs(d, exist_ok=True)
        return d

    def _path(self, ns: str, key: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key)
        return os.path.join(self._ns_dir(ns), safe + ".json")

    def set(self, ns: str, key: str, value, ttl: float | None = None,
            tags: list | None = None) -> None:
        path = self._path(ns, key)
        tmp = path + ".tmp"
        record = {
            "key": key,
            "value": value,
            "tags": tags or [],
            "updated": _now(),
            "expires": (_now() + ttl) if ttl else None,
        }
        # atomic write (avoid corruption on crash)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, default=str)
        os.replace(tmp, path)
        self._compact_if_needed()

    def get(self, ns: str, key: str, default=None):
        path = self._path(ns, key)
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
            if rec.get("expires") and rec["expires"] < _now():
                self.delete(ns, key)
                return default
            return rec.get("value", default)
        except (OSError, json.JSONDecodeError):
            return default

    def update(self, ns: str, key: str, **fields):
        cur = self.get(ns, key) or {}
        if isinstance(cur, dict):
            cur.update(fields)
        else:
            cur = fields
        self.set(ns, key, cur)
        return cur

    def delete(self, ns: str, key: str) -> None:
        try:
            os.remove(self._path(ns, key))
        except OSError:
            pass

    def keys(self, ns: str) -> list[str]:
        d = self._ns_dir(ns)
        try:
            return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))
        except OSError:
            return []

    def search(self, query: str, ns: str | None = None,
               limit: int = 20) -> list[dict]:
        """Keyword search across one or all namespaces."""
        q = query.lower()
        terms = [t for t in re.split(r"\W+", q) if len(t) > 2]
        results = []
        nss = [ns] if ns else self._list_namespaces()
        for n in nss:
            for key in self.keys(n):
                rec = self._read(n, key)
                if not rec:
                    continue
                blob = json.dumps(rec, ensure_ascii=False).lower()
                score = sum(1 for t in terms if t in blob) or (1 if q in blob else 0)
                if score:
                    results.append({"namespace": n, "key": key,
                                    "value": rec.get("value"),
                                    "tags": rec.get("tags", []),
                                    "updated": rec.get("updated"),
                                    "score": score})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def _read(self, ns: str, key: str) -> dict | None:
        try:
            with open(self._path(ns, key), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _list_namespaces(self) -> list[str]:
        try:
            return [d for d in os.listdir(self.dir)
                    if os.path.isdir(os.path.join(self.dir, d))]
        except OSError:
            return []

    def stats(self) -> dict:
        total = 0
        by_ns = {}
        for ns in self._list_namespaces():
            c = len(self.keys(ns))
            by_ns[ns] = c
            total += c
        return {"namespaces": by_ns, "entries": total,
                "max_entries": self.max_entries}

    def _compact_if_needed(self) -> None:
        if self.stats()["entries"] > self.max_entries:
            self.compact()

    def compact(self, dry_run: bool = False) -> dict:
        """Compaction: drop expired entries (size guard) and report the count."""
        removed = 0
        now = _now()
        for ns in self._list_namespaces():
            for key in self.keys(ns):
                rec = self._read(ns, key)
                if rec and rec.get("expires") and rec["expires"] < now:
                    if not dry_run:
                        self.delete(ns, key)
                    removed += 1
        return {"expired_removed": removed, "stats": self.stats()}


class Memory:
    """High-level layered API over MemoryStore for Elysia subsystems."""

    NS_SHORT = "short_term"
    NS_PROJECT = "project"
    NS_USER = "user_prefs"
    NS_AGENT = "agents"
    NS_PROVIDER = "providers"
    NS_HISTORY = "history"

    def __init__(self, state_dir: str, max_entries: int = 20000):
        self.store = MemoryStore(state_dir, max_entries=max_entries)

    def context(self, task_id, value):
        self.store.set(self.NS_SHORT, f"task_{task_id}", value,
                       ttl=86400 * 7)

    def context_get(self, task_id, default=None):
        return self.store.get(self.NS_SHORT, f"task_{task_id}", default)

    def project_memory(self, key, value=None):
        """Long-term project memory (decisions, notes, previous failures)."""
        if value is not None:
            self.store.set(self.NS_PROJECT, key, value)
            return value
        return self.store.get(self.NS_PROJECT, key)

    def record_project_note(self, kind, text):
        key = f"{kind}_{int(_now() * 1000)}"
        return self.store.set(self.NS_PROJECT, key, {"kind": kind, "text": text,
                                                     "ts": _now()})

    def user_pref(self, key, value=None, default=None):
        if value is not None:
            self.store.set(self.NS_USER, key, value)
            return value
        return self.store.get(self.NS_USER, key, default)

    def agent_memory(self, role, key, value=None):
        if value is not None:
            self.store.set(self.NS_AGENT, f"{role}/{key}", value)
            return value
        return self.store.get(self.NS_AGENT, f"{role}/{key}")

    def history_entry(self, key, **fields):
        fields["ts"] = _now()
        return self.store.set(self.NS_HISTORY, key, fields)

    def search(self, query, limit=20):
        return self.store.search(query, limit=limit)
