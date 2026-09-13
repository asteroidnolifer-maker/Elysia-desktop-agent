#!/usr/bin/env python3
"""
Elysia task board: shared coordination store for multiple opencode workers.

Prevents double-work by giving each task a unique lock and tracking which
files each worker has claimed. Workers claim a task atomically (SQLite
transaction), so two workers can never pick the same task.
"""
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taskboard.sqlite")


def _now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = connect()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        files TEXT NOT NULL DEFAULT '[]',   -- JSON list of owned files
        status TEXT NOT NULL DEFAULT 'open', -- open | claimed | done | failed
        priority INTEGER NOT NULL DEFAULT 5,
        worker TEXT,
        session TEXT,
        claimed_at TEXT,
        done_at TEXT,
        result TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS locks (
        path TEXT PRIMARY KEY,
        task_id INTEGER NOT NULL,
        worker TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    con.commit()
    con.close()


def add_task(title, description, files=None, priority=5):
    con = connect()
    cur = con.execute(
        "INSERT INTO tasks (title, description, files, priority, created_at) "
        "VALUES (?,?,?,?,?)",
        (title, description, json.dumps(files or []), priority, _now()),
    )
    con.commit()
    tid = cur.lastrowid
    con.close()
    return tid


## ---------------- atomically claim one open task, verifying file locks -----
def claim_task(worker, max_priority=None):
    """
    Atomically pick the highest-priority 'open' task whose files are not all
    locked by other workers, claim it for this worker, and lock its files.
    Returns a dict of the task, or None if no task is available.
    """
    con = connect()
    con.execute("BEGIN IMMEDIATE")
    try:
        rows = con.execute(
            "SELECT * FROM tasks WHERE status='open' "
            "ORDER BY priority DESC, id ASC"
        ).fetchall()
        for row in rows:
            files = json.loads(row["files"] or "[]")
            # Skip if any file is already locked by another task
            if files:
                q = ",".join("?" for _ in files)
                held = con.execute(
                    f"SELECT path FROM locks WHERE path IN ({q})", files
                ).fetchall()
                if held:
                    continue
            new_status = "claimed"
            con.execute(
                "UPDATE tasks SET status=?, worker=?, claimed_at=? WHERE id=?",
                (new_status, worker, _now(), row["id"]),
            )
            for f in files:
                con.execute(
                    "INSERT INTO locks (path, task_id, worker, created_at) "
                    "VALUES (?,?,?,?)",
                    (f, row["id"], worker, _now()),
                )
            con.commit()
            return dict(row, status=new_status, worker=worker)
        con.rollback()
        return None
    finally:
        con.close()


def finish_task(task_id, status, worker, result=None):
    con = connect()
    con.execute("BEGIN IMMEDIATE")
    try:
        files = json.loads(
            con.execute("SELECT files FROM tasks WHERE id=?", (task_id,)).fetchone()["files"] or "[]"
        )
        con.execute(
            "UPDATE tasks SET status=?, done_at=?, result=? WHERE id=? AND worker=?",
            (status, _now(), result, task_id, worker),
        )
        for f in files:
            con.execute("DELETE FROM locks WHERE path=? AND task_id=?", (f, task_id))
        con.commit()
    finally:
        con.close()


def release_stale(worker):
    """Release all locks/tasks held by a given worker (used on worker death)."""
    con = connect()
    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute("DELETE FROM locks WHERE worker=?", (worker,))
        con.execute(
            "UPDATE tasks SET status='open', worker=NULL "
            "WHERE worker=? AND status='claimed'",
            (worker,),
        )
        con.commit()
    finally:
        con.close()


def list_tasks(status=None):
    con = connect()
    if status:
        rows = con.execute("SELECT * FROM tasks WHERE status=?", (status,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    con.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "init":
        init_db()
        print("taskboard initialized:", DB_PATH)
    elif cmd == "add":
        init_db()
        title = sys.argv[2]
        desc = sys.argv[3] if len(sys.argv) > 3 else title
        files = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else []
        print("added task id:", add_task(title, desc, files))
    elif cmd == "list":
        init_db()
        status_arg = sys.argv[2] if len(sys.argv) > 2 else None
        for t in list_tasks(status_arg):
            print(f"#{t['id']} [{t['status']:>7}] p{t['priority']} worker={t['worker']} :: {t['title']}")
    elif cmd == "claim":
        init_db()
        t = claim_task(sys.argv[2])
        if t:
            print(json.dumps(t))
        else:
            print(json.dumps(None))
    elif cmd == "finish":
        finish_task(int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
        print("finished", sys.argv[2], sys.argv[3])
    elif cmd == "release":
        release_stale(sys.argv[2])
        print("released stale for", sys.argv[2])
