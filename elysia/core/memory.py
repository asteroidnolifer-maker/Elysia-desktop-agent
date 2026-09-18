"""Structured, layered persistent memory for Elysia.

Separates intentional concerns (one namespace each, never one giant blob):

  session      per-run scratch that dies with the run
  conversation the recent dialogue/turn log
  task         per-task context (goal, owned files, attempts)
  workflow     per-workflow state notes (gates, approvals, replans)
  project      long-term project memory (decisions, architecture notes)
  repo         repository knowledge (maps, detected stacks)
  user_prefs   operator preferences
  agents       per logical-role notes
  providers    provider state/history
  failure      failure memory (what broke, how, how it was fixed)
  solution     solution memory (what worked, for which kind of problem)
  decision     decision memory (choices + rationale)
  architecture architecture memory
  research     research notes
  tools        tool-use memory
  history      execution audit trail

Every record carries metadata so retrieval is honest:

    importance   0..1   (how much it matters)
    confidence   0..1   (how sure we are it is true)
    provenance   str    (who/what produced it: agent role, tool, run id)
    tags         list
    expires      float  (TTL, optional)
    created/updated
    recalls      int    (how often it was actually retrieved)
    last_recalled
    hash         str    (content hash — used for dedup)

Behaviour guarantees:
  - writes are atomic (tmp + os.replace), so a crash cannot corrupt a record
  - duplicate content is detected by hash and merged instead of duplicated
  - compaction drops expired records and *compresses* the oldest low-value
    ones into a summary record, so memory never grows without bound
  - retrieval scores by keyword relevance weighted by importance/recency and
    reports provenance + confidence, never a bare opaque number
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time


def _now() -> float:
    return time.time()


def content_hash(value) -> str:
    blob = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest()[:16]


def _clamp(v, lo=0.0, hi=1.0, default=0.5) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, f))


class MemoryStore:
    """Namespaced record store with search, dedup, TTL and compression.

    Layout: <dir>/<namespace>/<key>.json  plus <namespace>/_index.json
    (hash -> key) used for duplicate detection.
    """

    INDEX = "_index.json"

    def __init__(self, state_dir: str, max_entries: int = 20000,
                 namespace: str = "memory"):
        self.dir = os.path.join(state_dir, namespace)
        os.makedirs(self.dir, exist_ok=True)
        self.max_entries = max_entries

    # -- paths ---------------------------------------------------------------
    def _safe(self, name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", str(name))

    def _ns_dir(self, ns: str, create: bool = True) -> str:
        """Namespace directory. Reads must NOT create it (an empty
        namespace would otherwise show up in stats as if it held data)."""
        d = os.path.join(self.dir, self._safe(ns))
        if create:
            os.makedirs(d, exist_ok=True)
        return d

    def _path(self, ns: str, key: str) -> str:
        return os.path.join(self._ns_dir(ns), self._safe(key) + ".json")

    def _path_read(self, ns: str, key: str) -> str:
        return os.path.join(self._ns_dir(ns, create=False),
                            self._safe(key) + ".json")

    def _atomic_write(self, path: str, payload) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, default=str)
        os.replace(tmp, path)

    # -- raw record io -------------------------------------------------------
    def _read(self, ns: str, key: str) -> dict | None:
        try:
            with open(self._path_read(ns, key), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _index_read(self, ns: str) -> dict:
        try:
            with open(os.path.join(self._ns_dir(ns, create=False), self.INDEX),
                      encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _index_write(self, ns: str, index: dict) -> None:
        self._ns_dir(ns)
        try:
            self._atomic_write(os.path.join(self._ns_dir(ns), self.INDEX), index)
        except OSError:
            pass

    def _expired(self, rec: dict) -> bool:
        exp = rec.get("expires")
        return bool(exp) and exp < _now()

    # -- public api ----------------------------------------------------------
    def set(self, ns: str, key: str, value, ttl: float | None = None,
            tags: list | None = None, importance: float = 0.5,
            confidence: float = 0.7, provenance: str = "unknown",
            kind: str | None = None) -> None:
        """Create or replace one record (keeps created/recall history)."""
        prior = self._read(ns, key) or {}
        now = _now()
        record = {
            "key": key,
            "value": value,
            "kind": kind or prior.get("kind") or "note",
            "tags": tags if tags is not None else prior.get("tags", []),
            "importance": _clamp(importance, default=prior.get("importance", 0.5)),
            "confidence": _clamp(confidence, default=prior.get("confidence", 0.7)),
            "provenance": provenance or prior.get("provenance") or "unknown",
            "created": prior.get("created") or now,
            "updated": now,
            "expires": (_now() + ttl) if ttl else prior.get("expires"),
            "recalls": prior.get("recalls", 0),
            "last_recalled": prior.get("last_recalled"),
            "hash": content_hash(value),
            "version": int(prior.get("version") or 0) + 1,
        }
        try:
            self._atomic_write(self._path(ns, key), record)
        except OSError:
            return
        index = self._index_read(ns)
        index[record["hash"]] = key
        self._index_write(ns, index)
        self._compact_if_needed()

    def remember(self, ns: str, text, kind: str = "note",
                 importance: float = 0.5, confidence: float = 0.7,
                 provenance: str = "unknown", tags: list | None = None,
                 ttl: float | None = None, key: str | None = None) -> dict:
        """Append a memory, deduplicating identical content.

        Returns ``{ok, key, duplicate, reason}`` — a duplicate merges the new
        metadata into the existing record instead of adding a second copy.
        """
        h = content_hash(text)
        index = self._index_read(ns)
        existing = index.get(h)
        if existing and self._read(ns, existing):
            rec = self._read(ns, existing) or {}
            merged_tags = sorted(set(
                (rec.get("tags") or []) + (tags or [])))
            self.set(ns, existing, rec.get("value"),
                     tags=merged_tags,
                     importance=max(_clamp(importance, default=0.5),
                                    float(rec.get("importance") or 0.5)),
                     confidence=max(_clamp(confidence, default=0.7),
                                    float(rec.get("confidence") or 0.7)),
                     provenance=provenance)
            return {"ok": True, "key": existing, "duplicate": True,
                    "reason": "identical content already remembered"}
        rec_key = key or f"{kind}_{int(_now() * 1000)}_{h[:6]}"
        self.set(ns, rec_key, text, ttl=ttl, tags=tags,
                 importance=importance, confidence=confidence,
                 provenance=provenance, kind=kind)
        return {"ok": True, "key": rec_key, "duplicate": False, "reason": ""}

    def get(self, ns: str, key: str, default=None):
        try:
            with open(self._path_read(ns, key), encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError):
            return default
        if self._expired(rec):
            self.delete(ns, key)
            return default
        return rec.get("value", default)

    def record(self, ns: str, key: str, default=None) -> dict | None:
        """Full record (metadata included) — None when missing/expired."""
        rec = self._read(ns, key)
        if not rec:
            return default
        if self._expired(rec):
            self.delete(ns, key)
            return default
        return rec

    def update(self, ns: str, key: str, **fields):
        cur = self.get(ns, key) or {}
        if isinstance(cur, dict):
            cur.update(fields)
        else:
            cur = fields
        self.set(ns, key, cur)
        return cur

    def delete(self, ns: str, key: str) -> None:
        rec = self._read(ns, key)
        try:
            os.remove(self._path(ns, key))
        except OSError:
            pass
        if rec:
            index = self._index_read(ns)
            if index.get(rec.get("hash")) == key:
                index.pop(rec.get("hash"), None)
                self._index_write(ns, index)

    def keys(self, ns: str) -> list[str]:
        d = self._ns_dir(ns, create=False)
        try:
            return sorted(f[:-5] for f in os.listdir(d)
                          if f.endswith(".json") and f != self.INDEX)
        except OSError:
            return []

    def namespaces(self) -> list[str]:
        try:
            return sorted(d for d in os.listdir(self.dir)
                          if os.path.isdir(os.path.join(self.dir, d)))
        except OSError:
            return []

    # -- retrieval -----------------------------------------------------------
    def search(self, query: str, ns: str | None = None,
               limit: int = 20, min_score: float = 0.0) -> list[dict]:
        """Relevance-ranked recall across one or all namespaces.

        The score is a transparent product of term overlap, importance,
        recency and how often the memory has been useful before — surfaced in
        the result so callers can judge it, never hidden.
        """
        q = (query or "").lower()
        terms = [t for t in re.split(r"\W+", q) if len(t) > 2]
        now = _now()
        results = []
        for n in ([ns] if ns else self.namespaces()):
            for key in self.keys(n):
                rec = self._read(n, key)
                if not rec or self._expired(rec):
                    continue
                blob = json.dumps(rec.get("value"), ensure_ascii=False,
                                  default=str).lower()
                if terms:
                    hits = sum(1 for t in terms if t in blob)
                    if not hits:
                        continue
                    keyword = hits / len(terms)
                else:
                    if q and q not in blob:
                        continue
                    keyword = 1.0
                importance = _clamp(rec.get("importance"), default=0.5)
                confidence = _clamp(rec.get("confidence"), default=0.7)
                age_days = max(0.0, (now - float(rec.get("updated") or now))) / 86400
                recency = 1.0 / (1.0 + age_days / 14.0)
                recall_boost = min(0.25, 0.05 * int(rec.get("recalls") or 0))
                score = round(keyword * importance * recency
                              + recall_boost * recency, 4)
                if score <= min_score:
                    continue
                results.append({
                    "namespace": n, "key": key, "value": rec.get("value"),
                    "kind": rec.get("kind"),
                    "tags": rec.get("tags", []),
                    "importance": importance, "confidence": confidence,
                    "provenance": rec.get("provenance"),
                    "updated": rec.get("updated"), "recalls": rec.get("recalls", 0),
                    "score": score,
                    "why": f"keyword={keyword:.2f} importance={importance:.2f} "
                           f"recency={recency:.2f}",
                })
        results.sort(key=lambda r: (r["score"], r["updated"] or 0), reverse=True)
        return results[:limit]

    def recall(self, query: str, ns: str | None = None, limit: int = 10) -> list[dict]:
        """Search + record the fact that these memories were used."""
        hits = self.search(query, ns=ns, limit=limit)
        for h in hits:
            self.touch(h["namespace"], h["key"])
        return hits

    def touch(self, ns: str, key: str) -> None:
        """Bump recall counters (importance decays if never recalled)."""
        rec = self._read(ns, key)
        if not rec:
            return
        rec["recalls"] = int(rec.get("recalls") or 0) + 1
        rec["last_recalled"] = _now()
        try:
            self._atomic_write(self._path(ns, key), rec)
        except OSError:
            pass

    def invalidate(self, ns: str, key: str, reason: str = "") -> bool:
        """Mark a memory as wrong/superseded without deleting its history."""
        rec = self._read(ns, key)
        if not rec:
            return False
        rec["invalidated"] = True
        rec["invalid_reason"] = reason or "invalidated"
        rec["confidence"] = 0.0
        rec["updated"] = _now()
        try:
            self._atomic_write(self._path(ns, key), rec)
        except OSError:
            return False
        return True

    def correct(self, ns: str, key: str, value, reason: str = "") -> bool:
        """Correct a memory in place, keeping an audit trail of the old value."""
        rec = self._read(ns, key)
        if not rec:
            return False
        rec.setdefault("corrections", []).append(
            {"at": _now(), "old": rec.get("value"), "reason": reason})
        rec["value"] = value
        rec["hash"] = content_hash(value)
        rec["confidence"] = max(0.8, float(rec.get("confidence") or 0.0))
        rec["updated"] = _now()
        rec.pop("invalidated", None)
        try:
            self._atomic_write(self._path(ns, key), rec)
        except OSError:
            return False
        index = self._index_read(ns)
        index[rec["hash"]] = key
        self._index_write(ns, index)
        return True

    def timeline(self, ns: str | None = None, limit: int = 50) -> list[dict]:
        """Newest-first record timeline (provenance for a run or namespace)."""
        rows = []
        for n in ([ns] if ns else self.namespaces()):
            for key in self.keys(n):
                rec = self._read(n, key)
                if not rec or self._expired(rec):
                    continue
                rows.append({"namespace": n, "key": key,
                             "kind": rec.get("kind"),
                             "provenance": rec.get("provenance"),
                             "importance": rec.get("importance"),
                             "confidence": rec.get("confidence"),
                             "updated": rec.get("updated"),
                             "invalidated": bool(rec.get("invalidated")),
                             "value": rec.get("value")})
        rows.sort(key=lambda r: r["updated"] or 0, reverse=True)
        return rows[:limit]

    # -- stats / maintenance -------------------------------------------------
    def stats(self) -> dict:
        total = 0
        by_ns = {}
        for ns in self.namespaces():
            c = len(self.keys(ns))
            by_ns[ns] = c
            total += c
        return {"namespaces": by_ns, "entries": total,
                "max_entries": self.max_entries}

    def _compact_if_needed(self) -> None:
        if self.stats()["entries"] > self.max_entries:
            self.compact()

    def compact(self, dry_run: bool = False, keep_per_ns: int = 2000) -> dict:
        """Drop expired records, then compress the oldest low-value ones.

        Compression is real: the omitted records are replaced by ONE summary
        record per namespace (keys + kinds + when), so the history is kept in
        compressed form instead of being silently destroyed.
        """
        removed_expired = 0
        compressed = 0
        summaries = {}
        now = _now()
        for ns in self.namespaces():
            records = []
            for key in self.keys(ns):
                rec = self._read(ns, key)
                if not rec:
                    continue
                if self._expired(rec):
                    if not dry_run:
                        self.delete(ns, key)
                    removed_expired += 1
                    continue
                records.append(rec)
            if len(records) <= keep_per_ns:
                continue
            # highest importance first, then newest — keep those verbatim
            records.sort(key=lambda r: (_clamp(r.get("importance"), default=0.5),
                                        r.get("updated") or 0), reverse=True)
            keep, drop = records[:keep_per_ns], records[keep_per_ns:]
            compressed += len(drop)
            summaries[ns] = {
                "count": len(drop),
                "keys": [r.get("key") for r in drop][:200],
                "kinds": sorted({r.get("kind") for r in drop if r.get("kind")}),
                "span": [min((r.get("updated") or now) for r in drop),
                         max((r.get("updated") or now) for r in drop)],
            }
            if not dry_run:
                for r in drop:
                    self.delete(ns, r.get("key"))
        if summaries and not dry_run:
            existing = self.get("project", "memory_summary") or {}
            if not isinstance(existing, dict):
                existing = {}
            merged = dict(existing)
            for ns, s in summaries.items():
                merged[ns] = {"last_compressed": now, **s}
            self.set("project", "memory_summary", merged,
                     importance=0.6, confidence=0.9,
                     provenance="memory.compact",
                     tags=["compaction", "summary"])
        return {"expired_removed": removed_expired,
                "compressed": compressed,
                "summaries": summaries,
                "dry_run": bool(dry_run),
                "stats": self.stats()}

    def export(self) -> dict:
        """Full dump of live records (for backup / inspection / migration)."""
        out = {}
        for ns in self.namespaces():
            recs = {}
            for key in self.keys(ns):
                rec = self._read(ns, key)
                if rec:
                    recs[key] = rec
            out[ns] = recs
        return {"exported_at": _now(), "namespaces": out,
                "stats": self.stats()}

    def backup(self, path: str) -> dict:
        """Write a JSON backup to ``path``; returns a receipt (never raises)."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            payload = self.export()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, default=str)
            os.replace(tmp, path)
            return {"ok": True, "path": path,
                    "entries": payload["stats"]["entries"],
                    "bytes": os.path.getsize(path)}
        except OSError as e:
            return {"ok": False, "error": str(e), "path": path}

    def restore(self, path: str, merge: bool = True) -> dict:
        """Restore a backup produced by :meth:`backup`.

        Refuses missing/corrupt files instead of wiping live memory.
        """
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return {"ok": False, "error": f"unreadable backup: {e}"}
        namespaces = payload.get("namespaces")
        if not isinstance(namespaces, dict):
            return {"ok": False, "error": "backup has no namespaces mapping"}
        if not merge:
            for ns in self.namespaces():
                for key in self.keys(ns):
                    self.delete(ns, key)
        restored = 0
        for ns, recs in namespaces.items():
            if not isinstance(recs, dict):
                continue
            for key, rec in recs.items():
                if not isinstance(rec, dict):
                    continue
                self.set(ns, key, rec.get("value"),
                         tags=rec.get("tags"),
                         importance=rec.get("importance", 0.5),
                         confidence=rec.get("confidence", 0.7),
                         provenance=rec.get("provenance", "restore"))
                restored += 1
        return {"ok": True, "restored": restored, "merge": bool(merge),
                "stats": self.stats()}


class Memory:
    """High-level layered API over MemoryStore for Elysia subsystems."""

    NS_SESSION = "session"
    NS_CONVERSATION = "conversation"
    NS_TASK = "task"
    NS_WORKFLOW = "workflow"
    NS_SHORT = "short_term"          # legacy alias (kept for compatibility)
    NS_PROJECT = "project"
    NS_REPO = "repo"
    NS_USER = "user_prefs"
    NS_AGENT = "agents"
    NS_PROVIDER = "providers"
    NS_FAILURE = "failure"
    NS_SOLUTION = "solution"
    NS_DECISION = "decision"
    NS_ARCHITECTURE = "architecture"
    NS_RESEARCH = "research"
    NS_TOOL = "tools"
    NS_HISTORY = "history"

    def __init__(self, state_dir: str, max_entries: int = 20000):
        self.store = MemoryStore(state_dir, max_entries=max_entries)

    # -- legacy surface (kept stable for existing callers) ------------------
    def context(self, task_id, value):
        self.store.set(self.NS_SHORT, f"task_{task_id}", value,
                       ttl=86400 * 7, provenance="pipeline")

    def context_get(self, task_id, default=None):
        return self.store.get(self.NS_SHORT, f"task_{task_id}", default)

    def project_memory(self, key, value=None):
        if value is not None:
            self.store.set(self.NS_PROJECT, key, value, provenance="project")
            return value
        return self.store.get(self.NS_PROJECT, key)

    def record_project_note(self, kind, text, **kw):
        key = f"{kind}_{int(_now() * 1000)}"
        return self.store.set(self.NS_PROJECT, key,
                              {"kind": kind, "text": text, "ts": _now()},
                              tags=[kind], provenance=kw.pop(
                                  "provenance", "project.note"), **kw)

    def user_pref(self, key, value=None, default=None):
        if value is not None:
            self.store.set(self.NS_USER, key, value, importance=0.9,
                           provenance="operator")
            return value
        return self.store.get(self.NS_USER, key, default)

    def agent_memory(self, role, key, value=None):
        if value is not None:
            self.store.set(self.NS_AGENT, f"{role}/{key}", value,
                           provenance=f"agent:{role}")
            return value
        return self.store.get(self.NS_AGENT, f"{role}/{key}")

    def history_entry(self, key, **fields):
        fields["ts"] = _now()
        return self.store.set(self.NS_HISTORY, key, fields,
                              provenance=fields.pop("provenance", "runtime"))

    def search(self, query, limit=20):
        return self.store.search(query, limit=limit)

    # -- typed writers -------------------------------------------------------
    def remember_failure(self, task: dict, classification: dict,
                         error: str, run_id: str = "") -> dict:
        """Failure memory: what broke, how it was classified, what was tried."""
        tid = task.get("id")
        text = (f"task#{tid} [{task.get('title') or task.get('description') or ''}] "
                f"failed: {classification.get('kind')} :: {error[:600]}")
        return self.store.remember(
            self.NS_FAILURE, text, kind="failure",
            importance=_clamp(0.4 + float(classification.get("severity_score") or 0.2)),
            provenance=f"task:{tid}" if tid is not None else (run_id or "pipeline"),
            tags=[classification.get("kind") or "unknown",
                  classification.get("action") or "unknown",
                  f"role:{task.get('agent_role') or 'implementer'}"],
            key=f"fail_{tid}_{int(_now() * 1000)}")

    def remember_solution(self, task: dict, summary: str,
                          files: list | None = None, run_id: str = "") -> dict:
        tid = task.get("id")
        text = (f"solved task#{tid} [{task.get('title') or ''}]: {summary[:600]}")
        return self.store.remember(
            self.NS_SOLUTION, text, kind="solution", importance=0.7,
            confidence=0.75,
            provenance=f"task:{tid}" if tid is not None else (run_id or "pipeline"),
            tags=["solution", f"role:{task.get('agent_role') or 'implementer'}"]
                 + [f"file:{f}" for f in (files or [])][:8],
            key=f"sol_{tid}_{int(_now() * 1000)}")

    def remember_decision(self, what: str, why: str, actor: str = "master",
                          tags: list | None = None) -> dict:
        return self.store.remember(
            self.NS_DECISION, {"decision": what, "rationale": why},
            kind="decision", importance=0.75, provenance=actor,
            tags=["decision"] + (tags or []),
            key=f"dec_{int(_now() * 1000)}")

    def remember_task_context(self, task: dict, fields: dict) -> None:
        tid = task.get("id")
        if tid is None:
            return
        self.store.set(self.NS_TASK, f"task_{tid}",
                       {"task": task.get("title"),
                        "goal": task.get("description"),
                        "owned_files": task.get("owned_files") or [],
                        **fields},
                       ttl=86400 * 30, importance=0.6, provenance="pipeline")

    def remember_workflow(self, key: str, value, **kw) -> None:
        self.store.set(self.NS_WORKFLOW, key, value, provenance="workflow", **kw)

    def remember_repo(self, key: str, value) -> None:
        self.store.set(self.NS_REPO, key, value, importance=0.6,
                       provenance="project.map")

    def remember_tool_use(self, tool: str, ok: bool, detail: str = "") -> dict:
        return self.store.remember(
            self.NS_TOOL, f"{tool} {'ok' if ok else 'failed'} {detail[:200]}",
            kind="tool", importance=0.35 if ok else 0.6,
            provenance=f"tool:{tool}", tags=[tool, "ok" if ok else "fail"],
            key=f"tool_{tool}_{int(_now() * 1000)}")

    # -- retrieval -----------------------------------------------------------
    def recall(self, query: str, namespaces: list | None = None,
               limit: int = 10) -> list[dict]:
        """Retrieve relevant memories, counting the recall on each record."""
        hits = []
        for ns in (namespaces or [self.NS_FAILURE, self.NS_SOLUTION,
                                  self.NS_PROJECT, self.NS_DECISION,
                                  self.NS_ARCHITECTURE, self.NS_REPO,
                                  self.NS_USER]):
            hits.extend(self.store.search(query, ns=ns, limit=limit))
        hits.sort(key=lambda r: r["score"], reverse=True)
        hits = hits[:limit]
        for h in hits:
            self.store.touch(h["namespace"], h["key"])
        return hits

    def rec_about(self, task: dict, extra_terms: list | None = None,
                  limit: int = 3, max_chars: int = 900) -> list[dict]:
        """Memories relevant to THIS task (kept small enough for a prompt)."""
        terms = [task.get("title") or "", task.get("description") or ""]
        terms.extend((task.get("owned_files") or [])[:4])
        terms.extend(extra_terms or [])
        query = " ".join(t for t in terms if t)
        if not query.strip():
            return []
        hits = self.store.search(query, limit=limit * 3)
        picked = [h for h in hits if not h.get("value") is None][:limit]
        for h in picked:
            self.store.touch(h["namespace"], h["key"])
        return picked

    # -- maintenance --------------------------------------------------------
    def compact(self, dry_run: bool = False) -> dict:
        return self.store.compact(dry_run=dry_run)

    def stats(self) -> dict:
        return self.store.stats()

    def backup(self, path: str) -> dict:
        return self.store.backup(path)

    def timeline(self, ns: str | None = None, limit: int = 50) -> list[dict]:
        return self.store.timeline(ns=ns, limit=limit)

    def forget(self, ns: str, key: str) -> bool:
        if self.store.record(ns, key) is None:
            return False
        self.store.delete(ns, key)
        return True

    def invalidate(self, ns: str, key: str, reason: str = "") -> bool:
        return self.store.invalidate(ns, key, reason)

    def correct(self, ns: str, key: str, value, reason: str = "") -> bool:
        return self.store.correct(ns, key, value, reason)
