"""Task model + persistence.

The canonical task schema replaces the old minimal SQLite row. It adds
dependencies, read files, provider/model assignment, lease/heartbeat lifecycle,
attempt counts and test status.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',      -- open|claimed|in_progress|review|done|failed
    priority INTEGER NOT NULL DEFAULT 5,
    dependencies TEXT NOT NULL DEFAULT '[]',  -- JSON list of task ids
    owned_files TEXT NOT NULL DEFAULT '[]',
    read_files TEXT NOT NULL DEFAULT '[]',
    worker TEXT,
    provider TEXT,
    model TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    created_at REAL NOT NULL,
    claimed_at REAL,
    heartbeat_at REAL,
    lease_expires_at REAL,
    completed_at REAL,
    last_error TEXT,
    result TEXT,
    test_status TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_deps ON tasks(dependencies);
"""


def _now() -> float:
    return time.time()


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


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
        con.executescript(SCHEMA)
        con.commit()
        con.close()

    # -- create -------------------------------------------------------------
    def add_task(self, title, description="", owned_files=None, read_files=None,
                 dependencies=None, priority=5, max_attempts=3) -> int:
        con = self._connect()
        cur = con.execute(
            "INSERT INTO tasks (title, description, owned_files, read_files, "
            "dependencies, priority, max_attempts, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (title, description, json.dumps(owned_files or []),
             json.dumps(read_files or []), json.dumps([int(d) for d in (dependencies or [])]),
             int(priority), int(max_attempts), _now()),
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

    def list(self, status: str | None = None, limit: int = 500) -> list[dict]:
        con = self._connect()
        if status:
            rows = con.execute(
                "SELECT * FROM tasks WHERE status=? ORDER BY id DESC LIMIT ?",
                (status, limit)).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        con.close()
        return [self._row(r) for r in rows]

    def _row(self, r: sqlite3.Row) -> dict:
        t = dict(r)
        for col in ("dependencies", "owned_files", "read_files"):
            try:
                t[col] = json.loads(t.get(col) or "[]")
            except json.JSONDecodeError:
                t[col] = []
        return t

    # -- updates -------------------------------------------------------------
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

    def set_status(self, task_id: int, status: str) -> None:
        self._update(task_id, status=status)

    def claim(self, task_id: int, worker: str, provider: str | None,
              model: str | None, lease_seconds: int) -> bool:
        """Atomically claim an open task (or re-claim an expired lease).

        Returns True on success. Fails if the task is already claimed by
        another live worker (lease unexpired).
        """
        con = self._connect()
        con.execute("BEGIN IMMEDIATE")
        try:
            r = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not r:
                con.rollback()
                return False
            if r["status"] == "claimed" and r["lease_expires_at"] and \
                    time.time() < r["lease_expires_at"] and r["worker"] != worker:
                con.rollback()
                return False
            now = time.time()
            con.execute(
                "UPDATE tasks SET status='claimed', worker=?, provider=?, model=?, "
                "attempts=attempts+1, claimed_at=?, heartbeat_at=?, lease_expires_at=? "
                "WHERE id=?",
                (worker, provider, model, now, now, now + lease_seconds, task_id),
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
            "WHERE id=? AND worker=?",
            (now, now + lease_seconds, task_id, worker))
        con.commit()
        ok = cur.rowcount > 0
        con.close()
        return ok

    def complete(self, task_id: int, status: str, result: str | None,
                 test_status: str | None = None) -> None:
        self._update(task_id, status=status, result=result, test_status=test_status,
                     completed_at=_now(), lease_expires_at=None)

    def release_expired(self, max_attempts: int = 3) -> list[int]:
        """Reopen tasks whose lease expired without a heartbeat.

        Increments attempts naturally (claim() does that). A task that has hit
        max_attempts is failed instead of reopened.
        """
        con = self._connect()
        now = time.time()
        rows = con.execute(
            "SELECT id, attempts FROM tasks WHERE status='claimed' "
            "AND lease_expires_at IS NOT NULL AND lease_expires_at < ?",
            (now,)).fetchall()
        retried: list[int] = []
        for r in rows:
            if r["attempts"] >= max_attempts:
                con.execute(
                    "UPDATE tasks SET status='failed', last_error=?, completed_at=? "
                    "WHERE id=?",
                    ("lease expired too many times", now, r["id"]))
            else:
                con.execute(
                    "UPDATE tasks SET status='open', worker=NULL, provider=NULL, "
                    "model=NULL, claimed_at=NULL, lease_expires_at=NULL, "
                    "last_error='lease expired; released' WHERE id=?",
                    (r["id"],))
                retried.append(r["id"])
        con.commit()
        con.close()
        return retried

    # -- query helpers -------------------------------------------------------
    def counts(self) -> dict:
        con = self._connect()
        rows = con.execute("SELECT status, COUNT(*) c FROM tasks GROUP BY status").fetchall()
        con.close()
        counts = {"open": 0, "claimed": 0, "in_progress": 0, "review": 0,
                  "done": 0, "failed": 0}
        for r in rows:
            counts[r["status"]] = r["c"]
        counts["total"] = sum(counts.values())
        return counts

    def ready_tasks(self) -> list[dict]:
        """Open tasks whose dependencies are all satisfied, ordered by priority."""
        con = self._connect()
        rows = con.execute(
            "SELECT * FROM tasks WHERE status='open' ORDER BY priority DESC, id ASC"
        ).fetchall()
        con.close()
        out = []
        for r in rows:
            t = self._row(r)
            if self._deps_done(t.get("dependencies") or []):
                out.append(t)
        return out

    def _deps_done(self, deps: list) -> bool:
        if not deps:
            return True
        allowed = {"done", "failed"}
        placeholders = ",".join("?" for _ in deps)
        con = self._connect()
        rows = con.execute(
            f"SELECT status FROM tasks WHERE id IN ({placeholders})", deps).fetchall()
        con.close()
        if len(rows) != len(deps):
            return False
        return all(r["status"] in allowed for r in rows)