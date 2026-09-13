#!/usr/bin/env python3
"""
Elysia monitor.py — self-healing watcher for the agent pool.

Every 60s:
  1. Model health: if llama-server is down, try to start the stack.
  2. Zombie sweep: workers alive but silent > 15min get killed and their
     tasks released back to open.
  3. Failed-task requeue: requeue failed tasks (up to 3 attempts per task,
     tracked in .monitor/attempts.json). Old junk (id < 1303) is left dead.
  4. Pool watch: if tasks are open but no adaptive pool is running, relaunch
     it detached (cap 2).

Usage: monitor.py [interval_seconds]
Run:   setsid nohup python3 monitor.py </dev/null >/dev/null 2>&1 &
"""
import json
import os
import re
import subprocess
import sys
import time

ORCH_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(ORCH_DIR)
MON_DIR = os.path.join(ORCH_DIR, ".monitor")
os.makedirs(MON_DIR, exist_ok=True)
ATTEMPTS_PATH = os.path.join(MON_DIR, "attempts.json")
LOG_PATH = os.path.join(MON_DIR, "monitor.log")
TASKBOARD = os.path.join(ORCH_DIR, "taskboard.py")
WORKER = os.path.join(ORCH_DIR, "worker_local.py")
WS_DIR = os.environ.get("ELYSIA_WS",
                        os.path.realpath(os.path.join(REPO_ROOT, "workspace")))
STACK_SH = os.path.realpath(os.path.join(REPO_ROOT, "elysia-run.sh"))
NEW_TASK_FLOOR = 1303      # only ids >= this are real tasks worth requeueing
ARCHIVE_JUNK = True        # junk (id < floor) is never requeued, only archived
MAX_ATTEMPTS = 3
WORKER_STALE_SECS = 900    # 15min without a log update = zombie

sys.path.insert(0, ORCH_DIR)
import brain  # noqa: E402


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def tb(*args):
    r = subprocess.run([sys.executable, TASKBOARD, *args],
                       capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def load_attempts():
    try:
        with open(ATTEMPTS_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_attempts(a):
    with open(ATTEMPTS_PATH, "w") as f:
        json.dump(a, f)


def model_ok():
    return brain.health()


def start_stack():
    log("model DOWN; attempting stack start")
    subprocess.run(["bash", STACK_SH, "start"],
                   capture_output=True, text=True, timeout=120)
    ok = model_ok()
    log("stack restart " + ("OK" if ok else "FAILED"))
    return ok


def mtime_of(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0


def zombie_sweep():
    """Kill silent workers, release their claims. Only real python3 worker
    processes count (pgrep alone also matches unrelated command lines that
    merely contain the string 'worker_local.py')."""
    logs_dir = os.path.join(ORCH_DIR, "logs")
    killed = 0
    now = time.time()
    out = subprocess.run(["pgrep", "-f", "worker_local\\.py"],
                         capture_output=True, text=True).stdout
    for pid in out.split():
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        # must be an actual python3 process
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() != "python3":
                    continue
            with open(f"/proc/{pid}/cmdline") as f:
                cmd = f.read().replace("\0", " ")
        except OSError:
            continue
        m = re.search(r"worker_local\.py\s+(\S+)", cmd)
        if not m:
            continue
        wid = m.group(1)
        logf = os.path.join(logs_dir, f"worker-{wid}.log")
        if now - mtime_of(logf) > WORKER_STALE_SECS:
            log(f"zombie worker {wid} (pid {pid}) silent >15min; killing")
            subprocess.run(["kill", "-9", pid], capture_output=True)
            tb("release", wid)
            killed += 1
    return killed


def requeue_failed():
    attempts = load_attempts()
    requeued = 0
    for line in tb("list", "failed").splitlines():
        m = re.match(r"#(\d+)", line.strip())
        if not m:
            continue
        tid = int(m.group(1))
        if tid < NEW_TASK_FLOOR:
            # junk task failed again -> archive it permanently
            if ARCHIVE_JUNK:
                con = sqlite3.connect(con_path, timeout=30)
                con.execute("UPDATE tasks SET status='archived' WHERE id=?", (tid,))
                con.commit()
                con.close()
            continue
        n = attempts.get(str(tid), 0)
        if n >= MAX_ATTEMPTS:
            continue
        # move failed -> open
        con_path = os.path.join(ORCH_DIR, "taskboard.sqlite")
        import sqlite3
        con = sqlite3.connect(con_path, timeout=30)  # noqa: F811
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("UPDATE tasks SET status='open', worker=NULL, claimed_at=NULL "
                    "WHERE id=? AND status='failed'", (tid,))
        con.commit()
        con.close()
        attempts[str(tid)] = n + 1
        save_attempts(attempts)
        requeued += 1
        if requeued >= 5:  # per-cycle cap
            break
    return requeued


def live_worker_ids():
    """Set of worker IDs with a live python3 worker_local.py process."""
    ids = set()
    out = subprocess.run(["pgrep", "-f", "worker_local\\.py"],
                         capture_output=True, text=True).stdout
    for pid in out.split():
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            with open(f"/proc/{pid}/comm") as f:
                if f.read().strip() != "python3":
                    continue
            with open(f"/proc/{pid}/cmdline") as f:
                cmd = f.read().replace("\0", " ")
        except OSError:
            continue
        m = re.search(r"worker_local\.py\s+(\S+)", cmd)
        if m:
            ids.add(m.group(1))
    return ids


def release_orphan_claims():
    """Release tasks claimed by workers that no longer exist (crash recovery)."""
    live = live_worker_ids()
    released = 0
    for line in tb("list", "claimed").splitlines():
        m = re.match(r"#(\d+).*worker=(\S+)", line.strip())
        if not m:
            continue
        tid, wid = m.group(1), m.group(2)
        if wid not in live:
            tb("release", wid)
            log(f"released orphan claim on #{tid} (worker {wid} gone)")
            released += 1
    return released


def pool_running():
    return subprocess.run(["pgrep", "-f", "adaptive.sh up"],
                          capture_output=True).returncode == 0


def ensure_pool():
    open_count = len(tb("list", "open").splitlines())
    claimed_count = len(tb("list", "claimed").splitlines())
    if open_count == 0 and claimed_count == 0:
        return
    if not pool_running():
        log(f"{open_count} open + {claimed_count} claimed but pool dead; relaunching")
        subprocess.Popen(
            ["setsid", "bash", os.path.join(ORCH_DIR, "adaptive.sh"), "up", "1"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)


def cycle():
    if not model_ok():
        if not start_stack():
            return
    z = zombie_sweep()
    o = release_orphan_claims()
    r = requeue_failed()
    if r:
        log(f"requeued {r} failed task(s)")
    if o:
        log(f"released {o} orphan claim(s)")
    ensure_pool()
    if z or r:
        log(f"cycle summary: zombies_killed={z} requeued={r}")


def main():
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    log(f"monitor starting (interval={interval}s)")
    while True:
        try:
            cycle()
        except Exception as e:
            log(f"cycle error: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
