#!/usr/bin/env python3
"""
Elysia task board CLI — thin wrapper over the canonical TaskStore.

All schema, leases, heartbeats, and recovery logic live in
``elysia.core.tasks.TaskStore``. This file only provides a CLI for
manual inspection and testing.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from elysia.core.tasks import TaskStore  # noqa: E402

ORCH_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ORCH_DIR, "taskboard.sqlite")

_store = None


def store() -> TaskStore:
    global _store
    if _store is None:
        _store = TaskStore(DB_PATH)
    return _store


def add_task(title, description, files=None, priority=5, read_files=None,
             dependencies=None, max_attempts=3, kind="task", workflow=None,
             agent_role=None, dedup_hash=None, timeout_s=None):
    return store().add_task(
        title, description or title, owned_files=files or [],
        read_files=read_files or [], dependencies=dependencies or [],
        priority=priority, max_attempts=max_attempts, kind=kind,
        workflow=workflow, agent_role=agent_role, dedup_hash=dedup_hash,
        timeout_s=timeout_s, status="ready" if not (dependencies or []) else "queued")


def claim_task(worker, max_priority=None):
    """Claim the highest-priority ready task (dependencies satisfied)."""
    s = store()
    for t in s.ready_tasks():
        if max_priority is not None and t["priority"] > max_priority:
            continue
        if s.claim(t["id"], worker, None, None, lease_seconds=1200):
            return _legacy(s.get(t["id"]))
    return None


def _legacy(t):
    """Convert canonical store row -> legacy CLI dict shape."""
    if t is None:
        return None
    out = {k: v for k, v in t.items()}
    out["files"] = json.dumps(out.get("owned_files") or [])
    out["session"] = None
    from datetime import datetime, timezone
    for k in ("created_at", "claimed_at", "completed_at", "started_at",
              "scheduled_at"):
        v = out.get(k)
        if isinstance(v, float):
            out[k] = datetime.fromtimestamp(v, tz=timezone.utc).isoformat()
    return out


def finish_task(task_id, status, worker, result=None):
    s = store()
    if not s.get(int(task_id)):
        return
    test_status = None
    if result:
        import re
        m = re.search(r"jest rc=(\S+)", result)
        if m:
            test_status = "pass" if m.group(1) == "0" else "fail"
    s.complete(int(task_id), status, result, test_status)


def heartbeat_task(task_id, worker, lease_seconds=1200):
    """Extend a worker's lease while it is still alive (canonical path)."""
    return store().heartbeat(int(task_id), worker, lease_seconds)


def release_stale(worker):
    """Release all locks/tasks held by a given worker (used on worker death)."""
    s = store()
    s.release_all_for_worker(worker)


def release_stale_safe(worker):
    """Release expired leases AND stale worker claims (canonical path)."""
    store().release_expired()
    release_stale(worker)


def list_tasks(status=None):
    return [_legacy(t) for t in store().list(status=status)]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "init":
        _ = store()  # creates schema
        print("taskboard initialized:", DB_PATH)
    elif cmd == "add":
        _ = store()
        title = sys.argv[2]
        desc = sys.argv[3] if len(sys.argv) > 3 else title
        files = sys.argv[4].split(",") if len(sys.argv) > 4 and sys.argv[4] else []
        print("added task id:", add_task(title, desc, files))
    elif cmd == "list":
        _ = store()
        status_arg = sys.argv[2] if len(sys.argv) > 2 else None
        for t in list_tasks(status_arg):
            print(f"#{t['id']} [{str(t['status']):>12}] p{t['priority']} worker={t.get('worker')} :: {t['title']}")
    elif cmd == "claim":
        _ = store()
        t = claim_task(sys.argv[2])
        if t:
            print(json.dumps(t))
        else:
            print(json.dumps(None))
    elif cmd == "finish":
        finish_task(int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
        print("finished", sys.argv[2], sys.argv[3])
    elif cmd == "release":
        release_stale_safe(sys.argv[2])
        print("released stale for", sys.argv[2])
    elif cmd == "heartbeat":
        ok = heartbeat_task(int(sys.argv[2]), sys.argv[3],
                            int(sys.argv[4]) if len(sys.argv) > 4 else 1200)
        print("heartbeat", "ok" if ok else "lost")
        sys.exit(0 if ok else 1)