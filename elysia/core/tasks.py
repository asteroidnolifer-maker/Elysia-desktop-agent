"""Task model + persistence — canonical Elysia task lifecycle.

States follow the explicit lifecycle:

    queued -> ready -> claimed -> running -> testing -> reviewing -> completed
                                     |                                      |
                                     +-> failed --+-> retrying -> ready     |
                     running -> cancelled / lease_expired -> ready          |
                     retrying -> ready (with backoff)                       |
                     failed    (terminal)                                   |

A task is never permanently stuck: workers hold leases and heartbeat; when a
lease expires without a heartbeat the task is released back to ready (or, after
the retry limit, marked failed). Cancellation and timeouts are first-class.
Dependency propagation: a task whose dependency fails is skipped with status
``dependency_failed``.

Also stores: correlation_id (trace across agents/providers/tools), agent_role
(logical agent), workflow/kind, cost/usage, and a dedup hash for idempotency.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'task',         -- task | research | goal | checkpoint
    workflow TEXT,                              -- template name, e.g. feature|bugfix
    agent_role TEXT,                            -- planner|architect|implementer|...
    status TEXT NOT NULL DEFAULT 'queued',
    priority INTEGER NOT NULL DEFAULT 5,
    dependencies TEXT NOT NULL DEFAULT '[]',    -- JSON list of task ids
    dedup_hash TEXT,
    owned_files TEXT NOT NULL DEFAULT '[]',
    read_files TEXT NOT NULL DEFAULT '[]',
    worker TEXT,
    provider TEXT,
    model TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    backoff_until REAL,                         -- next-claim gate for retries
    timeout_s REAL,
    started_at REAL,
    created_at REAL NOT NULL,
    claimed_at REAL,
    heartbeat_at REAL,
    lease_expires_at REAL,
    scheduled_at REAL,
    completed_at REAL,
    cancelled_by TEXT,
    last_error TEXT,
    result TEXT,
    test_status TEXT,
    correlation_id TEXT,
    project_path TEXT,
    cost_usd REAL NOT NULL DEFAULT 0,
    usage_json TEXT NOT NULL DEFAULT '{}',
    -- resource-aware execution (see resources.py / RESOURCE_ARCHITECTURE.md)
    resource_class TEXT,                        -- light|io|network|cpu|cpu_heavy|
                                                -- memory_heavy|local_llm|remote_llm|build
    priority_class TEXT NOT NULL DEFAULT 'normal',  -- critical|interactive|normal|background|idle
    privacy TEXT NOT NULL DEFAULT '',            -- ''|local_only
    deterministic_checks INTEGER NOT NULL DEFAULT 0,
    retries INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_deps ON tasks(dependencies);
CREATE INDEX IF NOT EXISTS idx_tasks_dedup ON tasks(dedup_hash);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority) WHERE status='ready';
"""

#: Bump when the schema changes; _init() migrates existing boards forward.
SCHEMA_VERSION = 2

#: Columns added after v1. ``_ensure_columns`` applies only the missing ones, so
#: an existing board is upgraded in place (never recreated, never data loss).
_ADDED_COLUMNS = {
    "resource_class": "TEXT",
    "priority_class": "TEXT NOT NULL DEFAULT 'normal'",
    "privacy": "TEXT NOT NULL DEFAULT ''",
    "deterministic_checks": "INTEGER NOT NULL DEFAULT 0",
    "retries": "INTEGER NOT NULL DEFAULT 0",
}


def _ensure_columns(con: sqlite3.Connection) -> list[str]:
    """Add any missing column (idempotent). Returns the columns added."""
    have = {r[1] for r in con.execute("PRAGMA table_info(tasks)").fetchall()}
    added = []
    for name, decl in _ADDED_COLUMNS.items():
        if name not in have:
            con.execute(f"ALTER TABLE tasks ADD COLUMN {name} {decl}")
            added.append(name)
    return added


def _migrate(con: sqlite3.Connection) -> None:
    """Bring an existing database up to SCHEMA_VERSION.

    Uses SQLite's user_version pragma (atomic, no extra table). Each step is
    idempotent; executescript() has already added any missing columns/indexes
    for this version. Future migrations append "if v < N: ..." steps here —
    never edit history in place.
    """
    v = int(con.execute("PRAGMA user_version").fetchone()[0] or 0)
    if v < SCHEMA_VERSION:
        # v0 -> v1: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS in
        # SCHEMA already covers the delta (an older board just lacks objects).
        # v1 -> v2: resource-aware execution columns (ADD COLUMN only).
        _ensure_columns(con)
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

# Lifecycle helpers
TERMINAL = {"completed", "done", "failed", "cancelled", "dependency_failed"}
ACTIVE = {"queued", "ready", "claimed", "running", "testing", "reviewing",
          "retrying"}
ALLOWED = {"queued", "ready", "claimed", "running", "testing", "reviewing",
           "completed", "done", "failed", "retrying", "cancelled",
           "dependency_failed"}


def _now() -> float:
    return time.time()


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


# Explicit, edge-by-edge transition table. A status may ONLY move to one of
# the targets listed here; anything else is rejected by `transition()`.
VALID_TRANSITIONS: dict[str, set[str]] = {
    "queued":            {"ready", "cancelled", "failed", "dependency_failed"},
    "ready":             {"claimed", "queued", "cancelled", "failed",
                          "completed", "done", "dependency_failed"},
    "claimed":           {"running", "ready", "cancelled", "failed",
                          "completed", "done"},  # worker may finish direct
    "running":           {"testing", "reviewing", "ready", "failed",
                          "cancelled", "completed", "done"},
    "testing":           {"reviewing", "ready", "failed", "cancelled"},
    "reviewing":         {"completed", "done", "ready", "failed", "cancelled"},
    "retrying":          {"ready", "cancelled", "failed"},
    "completed":         set(),            # terminal
    "done":              set(),            # terminal
    "failed":            {"retrying", "ready"},
    "cancelled":         set(),            # terminal
    "dependency_failed": set(),            # terminal
}


def status_transition(current: str, target: str) -> bool:
    """True iff ``current -> target`` is an explicit legal lifecycle move."""
    if current == target:
        return False        # no-op moves are not transitions
    return target in VALID_TRANSITIONS.get(current, set())


class TaskStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init()

    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def _init(self):
        con = self._connect()
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript(SCHEMA)
        _migrate(con)
        con.commit()
        con.close()

    # -- health / maintenance (Phase 35) -------------------------------------
    def health_check(self) -> dict:
        """Is the board openable, intact and sane? Never raises."""
        info: dict = {"path": self.db_path, "exists": os.path.exists(self.db_path)}
        try:
            con = self._connect()
            try:
                info["integrity"] = (con.execute(
                    "PRAGMA integrity_check").fetchone()[0] or "?").lower()
                info["schema_version"] = int(
                    con.execute("PRAGMA user_version").fetchone()[0] or 0)
                info["journal_mode"] = con.execute(
                    "PRAGMA journal_mode").fetchone()[0]
                info["counts"] = self.counts()
                malformed = 0
                for row in con.execute("SELECT dependencies FROM tasks"):
                    try:
                        val = json.loads(row[0] or "[]")
                        if not isinstance(val, list):
                            malformed += 1
                    except (json.JSONDecodeError, TypeError):
                        malformed += 1
                info["malformed_dependency_rows"] = malformed
            finally:
                con.close()
            info["ok"] = info["integrity"] == "ok"
        except sqlite3.DatabaseError as e:
            info["ok"] = False
            info["error"] = str(e)[:200]
        return info

    def backup(self, dest_dir: str) -> dict:
        """Consistent online backup via SQLite's backup API (WAL-safe)."""
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, "taskboard-backup.sqlite")
        src = self._connect()
        try:
            dst = sqlite3.connect(dest)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return {"ok": True, "path": dest, "bytes": os.path.getsize(dest)}

    def restore(self, src_path: str) -> dict:
        """Restore from a backup (DB file only — workspace files are untouched)."""
        if not os.path.isfile(src_path):
            return {"ok": False, "error": f"no such backup: {src_path}"}
        try:
            chk = sqlite3.connect(src_path)
            try:
                ok = (chk.execute("PRAGMA integrity_check").fetchone()[0]
                      or "").lower() == "ok"
            finally:
                chk.close()
        except sqlite3.DatabaseError as e:
            return {"ok": False,
                    "error": f"backup unreadable: {str(e)[:120]}"}
        if not ok:
            return {"ok": False, "error": "backup failed integrity check"}
        for suffix in ("", "-wal", "-shm"):
            side = self.db_path + suffix
            if os.path.exists(side):
                os.remove(side)
        shutil.copy2(src_path, self.db_path)
        self._init()
        return {"ok": True, "restored_from": src_path}

    def vacuum(self) -> dict:
        """Reclaim space from deleted rows (compaction)."""
        before = os.path.getsize(self.db_path)
        con = self._connect()
        try:
            con.execute("VACUUM")
        finally:
            con.close()
        after = os.path.getsize(self.db_path)
        return {"ok": True, "bytes_before": before, "bytes_after": after,
                "reclaimed": max(0, before - after)}

    # -- create -------------------------------------------------------------
    def add_task(self, title, description="", owned_files=None, read_files=None,
                 dependencies=None, priority=5, max_attempts=3, kind="task",
                 workflow=None, agent_role=None, dedup_hash=None,
                 timeout_s=None, correlation_id=None, project_path=None,
                 status="queued", resource_class=None, priority_class=None,
                 privacy="") -> int:
        con = self._connect()
        cur = con.execute(
            "INSERT INTO tasks (title, description, owned_files, read_files, "
            "dependencies, priority, max_attempts, kind, workflow, agent_role, "
            "dedup_hash, timeout_s, correlation_id, project_path, status, "
            "created_at, resource_class, priority_class, privacy) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (title, description or title, json.dumps(owned_files or []),
             json.dumps(read_files or []),
             json.dumps([int(d) for d in (dependencies or [])]),
             int(priority), int(max_attempts), kind or "task", workflow,
             agent_role, dedup_hash, timeout_s,
             correlation_id or uuid.uuid4().hex[:12],
             project_path,
             status if status in ALLOWED else "queued", _now(),
             resource_class, priority_class or "normal", privacy or ""),
        )
        con.commit()
        tid = cur.lastrowid
        con.close()
        return tid

    # -- read ---------------------------------------------------------------
    def get(self, task_id: int) -> dict | None:
        con = self._connect()
        r = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        con.close()
        return self._row(r) if r else None

    def list(self, status: str | None = None, limit: int = 500,
             agent_role: str | None = None, workflow: str | None = None,
             kind: str | None = None) -> list[dict]:
        con = self._connect()
        q, args = "SELECT * FROM tasks", []
        where = []
        if status:
            where.append("status=?")
            args.append(status)
        if agent_role:
            where.append("agent_role=?")
            args.append(agent_role)
        if workflow:
            where.append("workflow=?")
            args.append(workflow)
        if kind:
            where.append("kind=?")
            args.append(kind)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = con.execute(q, args).fetchall()
        con.close()
        return [self._row(r) for r in rows]

    def _row(self, r: sqlite3.Row) -> dict:
        t = dict(r)
        for col in ("dependencies", "owned_files", "read_files", "usage_json"):
            try:
                if col == "usage_json":
                    t[col] = json.loads(t.get(col) or "{}")
                else:
                    t[col] = json.loads(t.get(col) or "[]")
            except json.JSONDecodeError:
                t[col] = {} if col == "usage_json" else []
        return t

    # -- state updates ------------------------------------------------------
    def _update(self, task_id: int, **fields) -> None:
        cols, vals = [], []
        for k, v in fields.items():
            cols.append(k + "=?")
            vals.append(v)
        if not cols:
            return
        vals.append(task_id)
        con = self._connect()
        con.execute(f"UPDATE tasks SET {', '.join(cols)} WHERE id=?", vals)
        con.commit()
        con.close()

    def set_status(self, task_id: int, status: str):
        """Explicit, validated status change (rejects illegal moves)."""
        if status not in ALLOWED:
            raise ValueError(f"illegal status {status}")
        if not self.transition(task_id, status):
            raise ValueError(f"unknown task {task_id}")

    def transition(self, task_id: int, target: str, last_error: str | None = None):
        """Validate and apply a lifecycle transition.

        Same-status moves are idempotent no-ops (still apply last_error if
        given). Illegal edges raise ValueError.
        """
        t = self.get(task_id)
        if not t:
            return False
        if t["status"] == target:
            # idempotent no-op
            if last_error is not None:
                self._update(task_id, last_error=last_error)
            return True
        if not status_transition(t["status"], target):
            raise ValueError(
                f"invalid transition {t['status']} -> {target} (task {task_id})")
        fields = {"status": target}
        if target in TERMINAL:
            fields["completed_at"] = _now()
            fields["lease_expires_at"] = None
        if last_error is not None:
            fields["last_error"] = last_error
        self._update(task_id, **fields)
        return True

    def mark_ready(self, task_id: int) -> None:
        self.transition(task_id, "ready")
        self._update(task_id, backoff_until=None)

    def mark_queued(self, task_id: int) -> None:
        self.transition(task_id, "queued")
        self._update(task_id, backoff_until=None)

    # -- claim / lease ------------------------------------------------------
    def claim(self, task_id: int, worker: str, provider: str | None,
              model: str | None, lease_seconds: int) -> bool:
        """Atomically claim a ready task; re-claim an expired lease too.

        Enforces backoff_until (retry wait). Returns True on success.
        """
        con = self._connect()
        con.execute("BEGIN IMMEDIATE")
        try:
            r = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not r:
                con.rollback()
                return False
            now = time.time()
            if r["status"] not in ("ready", "claimed", "running", "testing",
                                   "reviewing", "retrying"):
                con.rollback()
                return False
            if r["backoff_until"] and now < r["backoff_until"]:
                con.rollback()
                return False
            if (r["kind"] or "").startswith("gate:"):
                # workflow gates are evaluated by the WorkflowEngine, never
                # claimed/executed by a worker
                con.rollback()
                return False
            if r["status"] in ("claimed", "running", "testing", "reviewing",
                               "retrying"):
                # occupied by a live worker?
                if r["lease_expires_at"] and now < r["lease_expires_at"] \
                        and r["worker"] != worker:
                    con.rollback()
                    return False
            now = time.time()
            con.execute(
                "UPDATE tasks SET status='claimed', worker=?, provider=?, model=?, "
                "attempts=attempts+1, claimed_at=?, heartbeat_at=?, "
                "lease_expires_at=?, started_at=COALESCE(started_at, ?) "
                "WHERE id=?",
                (worker, provider, model, now, now, now + lease_seconds, now,
                 task_id),
            )
            con.commit()
            return True
        finally:
            con.close()

    def heartbeat(self, task_id: int, worker: str, lease_seconds: int) -> bool:
        now = time.time()
        con = self._connect()
        cur = con.execute(
            "UPDATE tasks SET heartbeat_at=?, lease_expires_at=? "
            "WHERE id=? AND (worker=? OR worker IS NULL)",
            (now, now + lease_seconds, task_id, worker))
        con.commit()
        ok = cur.rowcount > 0
        con.close()
        return ok

    def complete(self, task_id: int, status: str, result: str | None,
                 test_status: str | None = None) -> None:
        self.transition(task_id, status)
        self._update(task_id, result=result, test_status=test_status,
                     completed_at=_now(), lease_expires_at=None,
                     last_error=None)

    def fail_attempt(self, task_id: int, error: str, backoff_s: float) -> bool:
        """Register an attempt failure. If max_attempts reached -> failed."""
        t = self.get(task_id)
        if not t:
            return False
        attempts = (t.get("attempts") or 0)
        if attempts >= (t.get("max_attempts") or 3):
            self.transition(task_id, "failed", last_error=error)
            self._update(task_id, completed_at=_now())
            return False
        self.transition(task_id, "ready", last_error=error)
        self._update(task_id, backoff_until=time.time() + backoff_s,
                     worker=None, provider=None, model=None,
                     lease_expires_at=None)
        return True

    def timeout_task(self, task_id: int) -> None:
        self.transition(task_id, "ready", last_error="timed out; released")
        self._update(task_id, worker=None, provider=None, model=None,
                     lease_expires_at=None, backoff_until=None)

    # -- release / expiry ---------------------------------------------------
    def _lease_outcome(self, attempts: int, max_attempts: int) -> str:
        """A lease loss resolves to 'failed' (too many attempts) or 'ready'."""
        return "failed" if (attempts or 0) >= max_attempts else "ready"

    def release_expired(self, max_attempts: int = 3) -> list[int]:
        """Reopen claimed tasks whose lease expired without heartbeat.

        Each task's OWN ``max_attempts`` column is authoritative (the global
        ``max_attempts`` is only a default for rows missing it), so a task
        created with a smaller retry budget terminates instead of looping.

        Only performs table-legal transitions (claimed/running/testing/
        reviewing/retrying -> ready|failed). Returns released task ids.
        """
        con = self._connect()
        now = time.time()
        rows = con.execute(
            "SELECT id, status, attempts, max_attempts FROM tasks WHERE status IN "
            "('claimed','running','testing','reviewing','retrying') "
            "AND lease_expires_at IS NOT NULL AND lease_expires_at < ?",
            (now,)).fetchall()
        out = []
        for r in rows:
            eff_max = r["max_attempts"] if r["max_attempts"] else max_attempts
            target = self._lease_outcome(r["attempts"], eff_max)
            if not status_transition(r["status"], target):
                continue  # not a table-legal move — leave untouched
            if target == "failed":
                con.execute(
                    "UPDATE tasks SET status='failed', last_error=?, "
                    "completed_at=?, worker=NULL, provider=NULL, model=NULL, "
                    "lease_expires_at=NULL WHERE id=?",
                    ("lease expired too many times", now, r["id"]))
            else:
                con.execute(
                    "UPDATE tasks SET status='ready', worker=NULL, provider=NULL, "
                    "model=NULL, claimed_at=NULL, lease_expires_at=NULL, "
                    "backoff_until=?, last_error='lease expired; released' "
                    "WHERE id=?",
                    (now + 30, r["id"]))
                out.append(r["id"])
        con.commit()
        con.close()
        return out

    def release_all_for_worker(self, worker: str, max_attempts: int = 3) -> list[int]:
        con = self._connect()
        now = time.time()
        rows = con.execute(
            "SELECT id, status, attempts, max_attempts FROM tasks WHERE worker=?",
            (worker,)).fetchall()
        out = []
        for r in rows:
            eff_max = r["max_attempts"] if r["max_attempts"] else max_attempts
            target = self._lease_outcome(r["attempts"], eff_max)
            if not status_transition(r["status"], target):
                continue
            if target == "failed":
                con.execute(
                    "UPDATE tasks SET status='failed', last_error=?, "
                    "completed_at=?, worker=NULL WHERE id=?",
                    (f"worker {worker} disappeared", now, r["id"]))
            else:
                con.execute(
                    "UPDATE tasks SET status='ready', worker=NULL, provider=NULL, "
                    "model=NULL, claimed_at=NULL, lease_expires_at=NULL, "
                    "backoff_until=?, last_error='worker disappeared' WHERE id=?",
                    (now + 15, r["id"]))
                out.append(r["id"])
        con.commit()
        con.close()
        return out

    # -- cancellation / pause ----------------------------------------------
    def cancel(self, task_id: int, by: str = "user",
               deps_cascade: bool = True) -> list[int]:
        """Cancel a task (and, optionally, tasks waiting on it). Returns any
        additional task ids that were cancelled via dependency cascade.

        Only table-legal moves (non-terminal -> cancelled) are applied.
        """
        out = []
        t = self.get(task_id)
        if not t:
            return out
        if t["status"] not in TERMINAL and status_transition(t["status"],
                                                             "cancelled"):
            self._update(task_id, status="cancelled", cancelled_by=by,
                         completed_at=_now(), lease_expires_at=None,
                         last_error=f"cancelled (by {by})")
            out.append(task_id)
        if deps_cascade:
            for dep in self._dependent_on(task_id):
                d = self.get(dep)
                if d and d["status"] not in TERMINAL and status_transition(
                        d["status"], "cancelled"):
                    self._update(dep, status="cancelled", cancelled_by=by,
                                 completed_at=_now(),
                                 last_error=f"dependency {task_id} cancelled")
                    out.append(dep)
        return out

    def pause(self, task_id: int) -> bool:
        t = self.get(task_id)
        if not t or t["status"] != "ready":
            return False
        self.transition(task_id, "queued", last_error="paused")
        return True

    def resume(self, task_id: int) -> bool:
        t = self.get(task_id)
        if not t or t["status"] != "queued":
            return False
        self.transition(task_id, "ready", last_error=None)
        return True

    def _dependent_on(self, task_id: int) -> list[int]:
        con = self._connect()
        rows = con.execute("SELECT id, dependencies FROM tasks").fetchall()
        con.close()
        out = []
        for r in rows:
            try:
                deps = json.loads(r["dependencies"] or "[]")
            except json.JSONDecodeError:
                continue
            if int(task_id) in deps:
                out.append(r["id"])
        return out

    # -- retries / backoff --------------------------------------------------
    def retry(self, task_id: int, reset_attempts: bool = False) -> bool:
        t = self.get(task_id)
        if not t or not status_transition(t["status"], "ready"):
            return False
        if reset_attempts:
            self._update(task_id, attempts=0)
        self.transition(task_id, "ready", last_error="retry requested")
        self._update(task_id, backoff_until=None, completed_at=None,
                     worker=None, provider=None, model=None,
                     lease_expires_at=None)
        return True

    # -- dedup --------------------------------------------------------------
    def find_duplicate(self, dedup_hash: str) -> dict | None:
        if not dedup_hash:
            return None
        con = self._connect()
        r = con.execute("SELECT * FROM tasks WHERE dedup_hash=? AND status "
                        "NOT IN ('cancelled','dependency_failed') "
                        "ORDER BY id LIMIT 1", (dedup_hash,)).fetchone()
        con.close()
        return self._row(r) if r else None

    # -- usage / cost -------------------------------------------------------
    def record_usage(self, task_id: int, requests=0, tokens_in=0, tokens_out=0,
                     latency_s=0, failures=0, cost_usd=0.0, provider=None,
                     model=None, retries=0, deterministic_checks=0) -> None:
        t = self.get(task_id)
        if not t:
            return
        usage = dict(t.get("usage_json") or {})
        usage["requests"] = usage.get("requests", 0) + int(requests)
        usage["tokens_in"] = usage.get("tokens_in", 0) + int(tokens_in)
        usage["tokens_out"] = usage.get("tokens_out", 0) + int(tokens_out)
        usage["latency_s"] = usage.get("latency_s", 0.0) + float(latency_s)
        usage["failures"] = usage.get("failures", 0) + int(failures)
        usage["deterministic_checks"] = (usage.get("deterministic_checks", 0)
                                         + int(deterministic_checks))
        if requests:
            usage.setdefault("model_calls", []).append({
                "ts": _now(), "provider": provider, "model": model,
                "tokens_in": int(tokens_in), "tokens_out": int(tokens_out),
                "latency_s": float(latency_s), "ok": not failures,
            })
            if len(usage["model_calls"]) > 200:
                usage["model_calls"] = usage["model_calls"][-200:]
        if deterministic_checks:
            usage["checks"] = usage.get("checks", 0) + int(deterministic_checks)
        elif requests and "checks" not in usage:
            usage["checks"] = 0
        fields = {"usage_json": json.dumps(usage, default=str)}
        fields["cost_usd"] = round((t.get("cost_usd") or 0) + float(cost_usd), 6)
        if retries:
            fields["retries"] = int(t.get("retries") or 0) + int(retries)
        if deterministic_checks:
            fields["deterministic_checks"] = (int(t.get("deterministic_checks") or 0)
                                              + int(deterministic_checks))
        self._update(task_id, **fields)

    # -- resource metadata ---------------------------------------------------
    def set_resource_meta(self, task_id: int, resource_class: str | None = None,
                          priority_class: str | None = None,
                          privacy: str | None = None) -> None:
        """Persist a task's resource/priority/privacy classification."""
        fields = {}
        if resource_class is not None:
            fields["resource_class"] = resource_class
        if priority_class is not None:
            fields["priority_class"] = priority_class
        if privacy is not None:
            fields["privacy"] = privacy
        if fields:
            self._update(task_id, **fields)

    # -- queries ------------------------------------------------------------
    def counts(self) -> dict:
        con = self._connect()
        rows = con.execute(
            "SELECT status, COUNT(*) c FROM tasks GROUP BY status").fetchall()
        con.close()
        counts = {}
        for r in rows:
            counts[r["status"]] = r["c"]
        counts["total"] = sum(counts.values())
        for s in ALLOWED:
            counts.setdefault(s, 0)
        return counts

    def ready_tasks(self, limit: int = 50) -> list[dict]:
        """Ready tasks whose deps are all satisfied, ordered by priority."""
        con = self._connect()
        rows = con.execute(
            "SELECT * FROM tasks WHERE status='ready' "
            "AND (backoff_until IS NULL OR backoff_until <= ?) "
            "ORDER BY priority DESC, id ASC LIMIT ?",
            (_now(), limit)).fetchall()
        con.close()
        out = []
        for r in rows:
            t = self._row(r)
            if self._deps_ready(t.get("dependencies") or []):
                out.append(t)
        return out

    def _deps_ready(self, deps: list) -> bool:
        if not deps:
            return True
        # Both success terminal states satisfy a dependency: the canonical
        # executor completes tasks as "completed", while legacy callers
        # (taskboard CLI) finish them as "done".
        allowed = {"done", "completed"}
        placeholders = ",".join("?" for _ in deps)
        con = self._connect()
        rows = con.execute(
            f"SELECT id, status FROM tasks WHERE id IN ({placeholders})",
            deps).fetchall()
        con.close()
        if len(rows) != len(deps):
            return False
        return all(r["status"] in allowed for r in rows)

    def blocked_tasks(self) -> list[dict]:
        con = self._connect()
        rows = con.execute("SELECT * FROM tasks WHERE status='ready'").fetchall()
        con.close()
        return [self._row(r) for r in rows
                if not self._deps_ready(json.loads(r["dependencies"] or "[]"))]

    def failed_after_dependency(self, dep_id: int) -> list[int]:
        """Mark ready/queued tasks whose dependency failed as dependency_failed."""
        rows = [r for r in self.list()
                if r["status"] in ("ready", "queued")
                and dep_id in (r.get("dependencies") or [])]
        out = []
        for r in rows:
            if not status_transition(r["status"], "dependency_failed"):
                continue
            con = self._connect()
            con.execute("UPDATE tasks SET status='dependency_failed', "
                        "completed_at=?, last_error=?, lease_expires_at=NULL "
                        "WHERE id=?", (_now(), f"dependency {dep_id} failed", r["id"]))
            con.commit()
            con.close()
            out.append(r["id"])
        return out