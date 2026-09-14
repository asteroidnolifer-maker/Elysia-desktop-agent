#!/usr/bin/env python3
"""
Elysia JARVIS HUD server (Phase 4) — the control layer for the whole system.

User gives a goal -> the LOCAL model divides it into concrete file-owning
subtasks -> subtasks land on the shared SQLite board -> the adaptive pool of
worker_local.py agents picks them up -> the HUD watches live progress.

Endpoints (JSON unless noted):
  GET  /                     HUD page (HTML, orchestrator/hud.html)
  GET  /jarvis.jpg           theme image (~/Downloads/jarvis.jpg), if present
  GET  /api/state            one-shot HUD poll: health, counts, recent tasks, agents
  GET  /api/tasks?status=&n= filtered task listing (+?id= for one task full detail)
  GET  /api/agents           live agent list with last log line
  GET  /api/agent-log?worker=<id>&n=   tail of a worker's log
  POST /api/ask              {goal, files?} -> divide via local model -> add to board -> auto-launch pool
  POST /api/pool             {action: start|stop, cap?}   control the adaptive pool
  POST /api/task             {title, description, files}  manual task add

Stdlib only. Pure local (default bind 127.0.0.1). Run:
  setsid nohup python3 server.py --port 8087 </dev/null >>logs/server.log 2>&1 &
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import parse_qs
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ORCH_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ORCH_DIR)
sys.path.insert(0, os.path.dirname(ORCH_DIR))
REPO_ROOT = os.path.dirname(ORCH_DIR)
WS_DIR = os.path.realpath(os.path.join(REPO_ROOT, "workspace"))
DB_PATH = os.path.join(ORCH_DIR, "taskboard.sqlite")
LOGS_DIR = os.path.join(ORCH_DIR, "logs")
HUD_PATH = os.path.join(ORCH_DIR, "hud.html")
JARVIS_JPG = os.path.expanduser("~/Downloads/jarvis.jpg")
STACK_SH = os.path.realpath(os.path.join(REPO_ROOT, "elysia-run.sh"))
ADAPTIVE = os.path.join(ORCH_DIR, "adaptive.sh")
MONITOR = os.path.join(ORCH_DIR, "monitor.py")

import brain  # noqa: E402
import taskboard  # noqa: E402
from elysia.core.config import load_config  # noqa: E402
from elysia.core.events import EventBus  # noqa: E402
from elysia.core.providers import Provider, ProviderManager  # noqa: E402
from elysia.core.paths import validate_file_list  # noqa: E402
from elysia.core.resources import ResourceManager  # noqa: E402
from elysia.core.scheduler import Scheduler  # noqa: E402
from elysia.core import git as elysia_git  # noqa: E402

# Structured event bus + provider manager wired from the new core.
EVENTS = EventBus(run_id="hud")
PROVIDERS = ProviderManager()
for _pc in load_config().providers:
    PROVIDERS.register(_pc)


def _load_rules():
    try:
        with open(os.path.join(ORCH_DIR, "INSTRUCTIONS.md"),
                  encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


AGENT_RULES = _load_rules()

# Each subtask cap per /api/ask is no longer a hard global limit. The
# scheduler/concurrency is resource- and provider-aware (elysia.core.scheduler).
MAX_DIVISION = 6          # subtask cap per single /api/ask call
DIV_PROMPT = None         # built lazily with the workspace inventory


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg):
    # stdout is redirected to logs/server.log by the launch command.
    print(f"{time.strftime('%H:%M:%S')} [server] {msg}", flush=True)


## ----------------------------- board -----------------------------

def db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def board_counts():
    con = db()
    rows = con.execute("SELECT status, COUNT(*) c FROM tasks GROUP BY status").fetchall()
    con.close()
    counts = {"open": 0, "claimed": 0, "done": 0, "failed": 0, "archived": 0}
    for r in rows:
        counts[r["status"]] = r["c"]
    counts["total"] = sum(counts.values())
    return counts


def recent_tasks(limit=40, status=None):
    con = db()
    q = "SELECT * FROM tasks"
    if status:
        q += " WHERE status=?"
        rows = con.execute(q + " ORDER BY id DESC LIMIT ?", (status, limit)).fetchall()
    else:
        rows = con.execute(q + " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return [task_json(r) for r in rows]


def task_by_id(tid):
    con = db()
    r = con.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
    con.close()
    return task_json(r) if r else None


def task_json(r):
    t = dict(r)
    try:
        t["files"] = json.loads(t.get("files") or "[]")
    except Exception:
        t["files"] = []
    # keep payloads small for the HUD poll
    if t.get("result"):
        t["result"] = t["result"][:400]
    if t.get("description"):
        t["description"] = t["description"][:300]
    return t


## ----------------------------- health -----------------------------

def model_ok():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/v1/models", timeout=4):
            return True
    except Exception:
        return False


def agent_ok():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8085/health", timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def proc_up(pattern):
    return subprocess.run(["pgrep", "-f", pattern],
                          stdout=subprocess.DEVNULL).returncode == 0


def stack_health():
    h = {
        "model": model_ok(),
        "agent": agent_ok(),
        "pool": proc_up("adaptive\\.sh up"),
        "monitor": proc_up("monitor\\.py"),
        "stack_up": agent_ok() and model_ok(),
    }
    # provider manager health (any provider not just the default model port)
    h["providers"] = PROVIDERS.health_report()
    for p in PROVIDERS.list():
        if p.name == "local" or p.cfg.model:
            p.check_health()
    h["providers"] = PROVIDERS.health_report()
    h["provider_healthy"] = any(p.status == "healthy"
                                for p in PROVIDERS.list()) if PROVIDERS.list() else False
    return h


## ----------------------------- agents -----------------------------

def live_agents():
    """[(worker_id, pid, started)] from /proc, python3 worker_local.py only."""
    agents = []
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
            started = os.path.getmtime(f"/proc/{pid}")  # proc dir mtime = start
        except OSError:
            continue
        m = re.search(r"worker_local\.py\s+(\S+)", cmd)
        if not m:
            continue
        agents.append({"id": m.group(1), "pid": int(pid),
                       "started": int(started)})
    return agents


def tail(path, n=15):
    try:
        with open(path, "rb") as f:
            data = f.read()
        lines = data.decode("utf-8", "replace").splitlines()
        return lines[-n:]
    except OSError:
        return []


def agents_payload():
    agents = []
    for a in live_agents():
        logf = os.path.join(LOGS_DIR, f"worker-{a['id']}.log")
        a["log"] = tail(logf, 1)[0] if tail(logf, 1) else "(no log yet)"
        a["uptime_s"] = int(time.time() - a["started"])
        agents.append(a)
    return agents


## ---------------------- task division (local model) ----------------------

def inventory(limit=130):
    """Relevant existing files across the whole repo, to ground division."""
    skip = {"node_modules", "dist", "coverage", ".git", "runtime",
            "store", "quarantine", "build", ".cache", "logs",
            ".adaptive", ".monitor", "__pycache__"}
    out = []
    for root in ("workspace/src", "workspace/docs", "workspace/agent-core",
                 "orchestrator", "agent-core"):
        base = os.path.join(REPO_ROOT, root)
        if not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d not in skip]
            for f in fn:
                if f.endswith((".ts", ".tsx", ".go", ".md", ".json",
                               ".py", ".sh")):
                    out.append(os.path.relpath(os.path.join(dp, f), REPO_ROOT))
    for f in ("elysia-run.sh",):
        p = os.path.join(REPO_ROOT, f)
        if os.path.isfile(p):
            out.append(f)
    return sorted(set(out))[:limit]


def division_prompt(goal, files):
    inv = "\n".join(inventory())
    hint = (f"\nFiles the user explicitly wants touched: {', '.join(files)}\n"
            if files else "\n")
    rules = ("BINDING RULES (agents you split work for will apply these; "
             "honor them):\n" + AGENT_RULES + "\n\n") if AGENT_RULES else ""
    return (
        rules +
        "You are the task-division engine of an offline multi-agent build system. "
        "Coding agents will each own the file(s) of ONE subtask and write complete "
        "content for them, so divide work by FILE OWNERSHIP.\n\n"
        f"USER GOAL:\n{goal}\n"
        f"{hint}"
        "The writable workspace has these existing files (full relative paths "
        "under the workspace root, paths below may omit the root):\n"
        f"{inv}\n\n"
        "Rules:\n"
        "- Produce 1 to 6 subtasks that fully cover the goal.\n"
        "- Each subtask lists the SPECIFIC file(s) it owns: existing paths from "
        "the inventory when relevant, or sensible new paths (e.g. docs/x.md, "
        "src/common/.../x.ts). Full relative paths, no '..'.\n"
        "- description must be a self-contained spec (what + constraints) so an "
        "agent with no other context can complete it.\n"
        "- description MUST also name every existing file the implementer needs "
        "to READ to do the job (e.g. 'read orchestrator/server.py and "
        "orchestrator/hud.html, then document them in docs/...md'). Agents only "
        "receive the real content of files whose paths appear in the task.\n"
        "- Different subtasks must not share files.\n"
        "- OWNERSHIP: a subtask owns files it CREATES or REWRITES. If the goal "
        "documents or creates something new, own a NEW path (e.g. docs/x.md, "
        "not yet in the inventory) and READ existing inventory files only for "
        "grounding. Never make an existing config/source file an owned file "
        "unless the goal explicitly says to modify that exact file.\n\n"
        "Output ONLY a JSON array, one object per subtask:\n"
        '[{"title":"Short imperative title","description":"Self-contained spec",'
        '"files":["rel/path.ts","rel/path.md"]}]\n'
        "No markdown fences, no commentary. Valid JSON only."
    )


def extract_json(text):
    """Lenient JSON-array extraction from a model reply."""
    if not text:
        return None
    # strip one surrounding code fence
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    # locate the outermost [...] block by bracket counting
    start = text.find("[")
    if start < 0:
        return None
    depth, i = 0, start
    while i < len(text):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        return None
    cand = text[start:i + 1]
    try:
        return json.loads(cand)
    except Exception:
        pass
    # salvage: try each brace-pair window that starts with '{'
    for mm in re.finditer(r"\{", cand):
        depth2, j = 0, mm.start()
        while j < len(cand):
            if cand[j] == "{":
                depth2 += 1
            elif cand[j] == "}":
                depth2 -= 1
                if depth2 == 0:
                    break
            j += 1
        if depth2 == 0:
            try:
                obj = json.loads(cand[mm.start():j + 1])
                if isinstance(obj, dict) and obj.get("title"):
                    # not a full array — return a single-element list
                    return [obj]
            except Exception:
                continue
    return None


def sanitize_subtasks(items, files_hint):
    """Validate/clean division output into taskboard-ready entries."""
    out = []
    seen_files = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        desc = str(it.get("description") or "").strip()
        raw = it.get("files")
        files = []
        if isinstance(raw, str):
            raw = re.split(r"[,\n]+", raw)
        if isinstance(raw, list):
            for f in raw:
                f = str(f).strip().strip("`").lstrip("/")
                if f and ".." not in f and not f.startswith("/"):
                    files.append(f)
        files = files[:4] or files_hint[:4]
        files = [f for f in files if f not in seen_files]
        seen_files.update(files)
        if not files:
            continue  # malformed task without owned files is never allowed
        if not title:
            title = (desc or "untitled")[:80]
        out.append({"title": title[:160], "description": desc[:1500], "files": files})
    return out[:MAX_DIVISION]


## --------------------------- JARVIS chat ------------------------------

# Deterministic intent detection — the 1.5B model can't classify reliably, so
# we do it cheaply and accurately here, and only call the model for content.
BUILD_VERBS = ["write", "rewrite", "create", "add", "build", "implement",
               "fix", "refactor", "document", "update", "modify", "extend",
               "cover", "test", "make", "develop", "generate", "migrate",
               "convert", "change", "debug", "remove", "delete", "improve",
               "produce", "split", "draft"]
STATUS_KEYS = ["status", "how many", "how much", "count", "done task",
               "open task", "failed task", "task board", "taskboard",
               "what's done", "what is done", "agent", "worker", "health",
               "running", "logs", "board", "report", "progress", "live"]
EXPLAIN_ONLY = ["what is", "what are", "how does", "how do", "how should",
                "why", "explain", "meaning", "difference", "compare"]


def classify_intent(msg):
    """-> 'build' | 'status' | 'pool' | 'general'
    Phrase-based on purpose: bare words like 'agent' or 'open' collide with
    filenames (agent-core) and verbs, so we only trust multi-word tell-tales."""
    m = (msg or "").strip()
    if not m:
        return "general"
    low = re.sub(r"[’']", " ", m.lower())
    # pool control: (start|stop|...)(...)(pool|workers|agents)
    if re.search(r"\b(start|launch|spawn|open|run|resume)\b.{0,25}"
                 r"\b(pool|workers|agents)\b", low) or \
       re.search(r"\b(stop|kill|close|pause|shut down|halt)\b.{0,25}"
                 r"\b(pool|workers|agents)\b", low):
        return "pool"
    # a specific task reference (#123) is always a lookup, not a chat topic
    if re.search(r"#\d+", low):
        return "status"
    # 1) strong ask-for-status phrasing (numbers/state) wins
    status_strong = ["status", "how many", "how much", "count", "report",
                     "progress", "health", "running", "online",
                     "done tasks", "failed tasks", "open tasks",
                     "claimed tasks", "latest done", "latest failed",
                     "last done", "last failed", "what's done",
                     "what is done", "current state"]
    if any(p in low for p in status_strong):
        return "status"
    # 1.5) elysia agent tasks - check BEFORE general questions
    elysia_triggers = ["upload", "youtube", "search for", "find me", "research",
                       "analyze", "create video", "post to", "automate",
                       "stock", "trade", "buy", "sell", "meme", "generate",
                       "bitcoin", "crypto", "ethereum", "price of", "should i",
                       "dropship", "product", "trending", "best", "latest"]
    if any(t in low for t in elysia_triggers):
        return "elysia"
    # 2) conceptual questions go to the model, never to the board
    explain = ["what is", "what are", "how does", "how do", "how should",
               "how would", "why", "explain", "difference", "compare",
               "does it mean", "does that mean", "do you mean",
               "tell me about", "describe"]
    if any(e in low for e in explain):
        return "general"
    # 3) secondary status nouns (commands like "agents", "show the board")
    if any(p in low for p in ("task board", "taskboard", "board state",
                              "the board", "agents", "workers", "logs",
                              "live")):
        return "status"
    # 4) build goals ("write a guide…", "can you add tests…")
    if any(re.search(r"\b" + v + r"\w*\b", low) for v in BUILD_VERBS):
        return "build"
    return "general"


def start_or_stop_from(msg):
    low = msg.lower()
    if re.search(r"(start|launch|open|run).{0,20}(pool|worker|agent)", low):
        return start_pool(cap=2)
    return stop_pool()


def status_summary(msg=""):
    h = stack_health()
    c = board_counts()
    ag = agents_payload()
    ids = ", ".join(a["id"] for a in ag) or "none"
    L = []
    L.append("SYSTEM STATUS")
    L.append(f"  model   : {'UP' if h['model'] else 'DOWN'}   "
             f"agent-core: {'UP' if h['agent'] else 'DOWN'}")
    L.append(f"  pool    : {'RUNNING' if h['pool'] else 'stopped'}   "
             f"monitor: {'RUNNING' if h['monitor'] else 'stopped'}")
    L.append(f"  board   : {c['open']} open · {c['claimed']} claimed · "
             f"{c['done']} done · {c['failed']} failed "
             f"({c['archived']} archived, {c['total']} total)")
    L.append(f"  agents  : {len(ag)} online ({ids})")
    m = re.search(r"#(\d+)", msg or "")
    if m:
        t = task_by_id(int(m.group(1)))
        if t:
            L.append(f"  task #{t['id']}: {t['status']} "
                     f"{t['title'][:60]}")
            L.append(f"    files: {', '.join(t['files'][:6])}")
            if t["result"]:
                L.append(f"    result: {t['result'][:160]}")
            return "\n".join(L)
    if c["failed"]:
        f = recent_tasks(limit=4, status="failed")
        if f:
            L.append("  last failed:")
            for t in f:
                L.append(f"    #{t['id']} {t['title'][:60]}")
    if c["open"]:
        o = recent_tasks(limit=3, status="open")
        if o:
            L.append("  open now:")
            for t in o:
                L.append(f"    #{t['id']} {t['title'][:60]}")
    if c["done"]:
        d = recent_tasks(limit=3, status="done")
        if d:
            L.append("  latest done:")
            for t in d:
                L.append(f"    #{t['id']} {t['title'][:60]} "
                          f"by {t['worker']}")
    return "\n".join(L)


def general_chat(message, history):
    """A conversational answer from the local model."""
    hist = (history or [])[-8:]
    msgs = [{"role": "system", "content":
             "You are JARVIS, the operator assistant of the Elysia offline "
             "multi-agent coding system on this machine. Answer concisely in "
             "plain text (no markdown). If asked about live system state "
             "(counts, health, agents) tell the user to type 'status'. "
             "Be honest about limits: you run on a small local model."}]
    for h in hist:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant"):
            msgs.append({"role": h["role"],
                         "content": str(h.get("content", ""))[:1500]})
    # the client already includes the latest user message in history
    if not hist or not (hist[-1].get("role") == "user"
                        and str(hist[-1].get("content", "")).strip()
                        == (message or "").strip()):
        msgs.append({"role": "user", "content": message})
    text, err = brain.chat(msgs, max_tokens=768, temperature=0.4, timeout=600)
    if err:
        return f"[model error: {err[:200]}]"
    return (text or "(no reply)").strip()


CHAT_SYSTEM_HINT = (
    "I can answer questions, report live system status, or split a goal into "
    "concrete file-owning tasks that local agents then implement."
)


def _repo_path_exists(rel):
    for base in (REPO_ROOT, WS_DIR):
        if os.path.isfile(os.path.join(base, rel)):
            return True
    return False


def apply_output_target(goal, subs):
    """Safety net for the splitter: when the user names a NEW markdown file in
    the goal but a subtask was given only existing files to own, re-own that
    subtask with the user's file. A worker must never rewrite an existing
    config/source by accident on a "document this" goal."""
    m = re.search(r"(?:^|[\s\"'`])([\w./-]+\.md)", goal or "")
    if not m:
        return subs
    t = m.group(1).lstrip("./")
    if ".." in t or not t.endswith(".md"):
        return subs
    for s in subs:
        owned = s.get("files") or []
        if t in owned:
            continue
        all_existing = bool(owned) and all(_repo_path_exists(o) for o in owned)
        if all_existing or len(subs) == 1:
            s["files"] = [t]
    return subs


def queue_goal(goal, files_hint=None):
    """Shared goal pipeline: divide -> add tasks -> auto-start pool.
    Returns (added, err, pool_msg)."""
    subs, err = divide_goal(goal, files_hint or [])
    if subs is None:
        return None, err, None
    subs = apply_output_target(goal, subs)
    added = []
    store = taskboard.store()
    for s in subs:
        tid = taskboard.add_task(s["title"], s["description"], s["files"],
                                 priority=5)
        added.append({"id": tid, **s})
        EVENTS.emit("task.created", task_id=tid, status="queued",
                    detail=s["title"][:200],
                    files=s["files"])
    log(f"queue_goal -> added {len(added)}: " +
        ", ".join(f"#{a['id']}" for a in added))
    # Durable workflow: the task rows ARE the state; the canonical scheduler
    # (started with the server) owns recovery. Keep the legacy adaptive pool
    # for local-model execution.
    try:
        start_scheduler_thread()
    except Exception as e:  # noqa: BLE001
        log(f"scheduler start failed (non-fatal): {e}")
    pool_msg = start_pool(cap=2).get("msg") if model_ok() else None
    return added, "", pool_msg


def divide_goal(goal, files_hint=None):
    """Ask the local model to split a goal into subtasks. -> (subtasks, err)"""
    if not model_ok():
        return None, "local model is DOWN (start it with elysia-run.sh start)"
    prompt = division_prompt(goal, files_hint or [])
    text, err = brain.chat(
        [{"role": "system", "content":
          "You output strictly valid JSON. No markdown fences, no prose."},
         {"role": "user", "content": prompt}],
        max_tokens=1536, temperature=0.2, timeout=600)
    if err:
        return None, f"model call failed: {err[:200]}"
    items = extract_json(text)
    if items is None:
        return None, ("could not parse a JSON task list from the model "
                      f"(raw {len(text)} chars). Retry or add tasks manually.")
    subs = sanitize_subtasks(items, files_hint or [])
    if not subs:
        return None, "division produced no valid subtasks (each needs owned files)."
    return subs, ""


## ----------------------------- scheduler -----------------------------
# The canonical scheduler (elysia.core.scheduler.Scheduler) runs IN this server
# process. Its maintenance loop is the single authority for lease expiry,
# timeout enforcement, dependency-failure propagation and stale-worker release
# — so a crashed worker's task is recovered automatically instead of blocking
# the board for the full lease duration.
SCHEDULER = None
_SCHEDULER_T = None
_SCHED_STOP = None


def ensure_scheduler():
    """Start the canonical scheduler (idempotent). Returns the scheduler."""
    global SCHEDULER, _SCHEDULER_T, _SCHED_STOP
    if SCHEDULER is not None:
        return SCHEDULER
    from elysia.core.resources import ResourceManager as _RM
    from elysia.core.scheduler import Scheduler as _Sched
    from elysia.core.config import load_config as _load_cfg
    SCHEDULER = _Sched(taskboard.store(), PROVIDERS, EVENTS,
                       cfg=_load_cfg(), worker_id="hud-server",
                       resources=_RM())
    _SCHED_STOP = SCHEDULER._stop
    SCHEDULER.start()
    EVENTS.emit("scheduler", status="started")
    log("canonical scheduler started (leases, timeouts, dep-failure recovery)")
    return SCHEDULER


def scheduler_maintenance_now():
    """Run one maintenance pass synchronously (used by tests and /api/scheduler)."""
    s = ensure_scheduler()
    s.maintenance()
    return s


## ----------------------------- scheduler thread (managed lifecycle) ---
def _scheduler_loop():
    """Managed maintenance loop with restart-on-crash (server-owned lifetime)."""
    backoff = 1.0
    while not (_SCHED_STOP and _SCHED_STOP.is_set()):
        try:
            SCHEDULER.maintenance()
            backoff = 1.0
        except Exception as e:  # noqa: BLE001
            log(f"scheduler maintenance error: {e}; restarting in {backoff:.0f}s")
            EVENTS.emit("scheduler", status="error", error=str(e)[:300])
            _SCHED_STOP.wait(backoff)
            backoff = min(backoff * 2, 30)
        _SCHED_STOP.wait(5)


def start_scheduler_thread():
    """Server-owned maintenance thread (daemon but supervised by _loop)."""
    s = ensure_scheduler()
    s._stop.clear()          # allow start/stop/start cycles (tests, restarts)
    global _SCHEDULER_T
    if _SCHEDULER_T is None or not _SCHEDULER_T.is_alive():
        _SCHEDULER_T = threading.Thread(target=_scheduler_loop,
                                        name="elysia-scheduler", daemon=True)
        _SCHEDULER_T.start()
    return _SCHEDULER_T


def stop_scheduler():
    """Stop the scheduler cleanly (used by tests and shutdown)."""
    if SCHEDULER is not None:
        SCHEDULER.stop()
        EVENTS.emit("scheduler", status="stopped")


## ----------------------------- pool -----------------------------

def start_pool(cap=2):
    if proc_up("adaptive\\.sh up"):
        return {"ok": True, "msg": "pool already running"}
    # Pin workers to the unified workspace even if the server's own
    # environment has a stale ELYSIA_WS (or none) from the old layout.
    env = dict(os.environ, ELYSIA_WS=WS_DIR)
    subprocess.Popen(
        ["setsid", "bash", ADAPTIVE, "up", str(cap)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True, env=env)
    log(f"pool start requested (cap={cap})")
    return {"ok": True, "msg": f"pool starting (cap={cap})"}


def stop_pool():
    subprocess.run(["bash", ADAPTIVE, "down"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log("pool stop requested")
    return {"ok": True, "msg": "pool stopping"}


## ----------------------------- HTTP -----------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "ElysiaHUD/1.0"

    # ---- helpers ----
    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 1_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode())
        except Exception:
            return {}

    def log_message(self, *a):
        pass  # silence default per-request noise

    # ---- routing ----
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        q = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
        if path == "/":
            return self._page()
        if path == "/jarvis.jpg":
            return self._jarvis()
        if path == "/api/state":
            return self._send(200, self._api_state())
        if path == "/api/tasks":
            return self._send(200, self._api_tasks(q))
        if path == "/api/agents":
            return self._send(200, {"ok": True, "agents": agents_payload()})
        if path == "/api/providers":
            return self._send(200, self._api_providers())
        if path == "/api/events":
            return self._send(200, self._api_events(q))
        if path == "/api/scheduler":
            s = SCHEDULER
            counts = taskboard.store().counts()
            blocked = len(taskboard.store().blocked_tasks())
            return self._send(200, {
                "ok": True,
                "running": bool(s),
                "workers": s.workers.list() if s else [],
                "max_concurrency": s.max_concurrency if s else None,
                "budget": s.current_budget() if s else None,
                "counts": counts,
                "blocked": blocked,
            })
        if path == "/api/agent-log":
            wid = (q.get("worker") or [""])[0]
            n = int((q.get("n") or ["30"])[0])
            if wid == "__pool":
                logf = os.path.join(ORCH_DIR, ".adaptive", "adaptive.log")
            elif wid == "__server":
                logf = os.path.join(LOGS_DIR, "server.log")
            else:
                logf = os.path.join(LOGS_DIR, f"worker-{wid}.log")
            return self._send(200, {"ok": True, "worker": wid,
                                    "lines": tail(logf, n)})
        return self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        body = self._body()
        if path == "/api/ask":
            return self._api_ask(body)
        if path == "/api/pool":
            return self._api_pool(body)
        if path == "/api/task":
            return self._api_task(body)
        if path == "/api/task/cancel":
            tid = int(body.get("id") or 0)
            if tid <= 0:
                return self._send(400, {"ok": False, "error": "id required"})
            affected = (SCHEDULER.cancel(tid, by="user")
                        if SCHEDULER else taskboard.store().cancel(tid))
            return self._send(200, {"ok": True, "cancelled": affected})
        if path == "/api/chat":
            return self._api_chat(body)
        if path == "/api/agent":
            return self._api_agent(body)
        return self._send(404, {"ok": False, "error": "not found"})

    # ---- handlers ----
    def _page(self):
        try:
            with open(HUD_PATH) as f:
                html = f.read()
        except OSError:
            return self._send(500, "hud.html missing", "text/plain")
        return self._send(200, html, "text/html; charset=utf-8")

    def _jarvis(self):
        try:
            with open(JARVIS_JPG, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self._send(404, {"ok": False, "error": "jarvis.jpg not found"})

    def _api_state(self):
        counts = board_counts()
        agents = agents_payload()
        EVENTS.emit("api_state", status="ok")
        return {
            "ok": True,
            "time": now_iso(),
            "health": stack_health(),
            "counts": counts,
            "tasks": recent_tasks(limit=25),
            "agents": agents,
        }

    def _api_tasks(self, q):
        if q.get("id"):
            return {"ok": True, "task": task_by_id(int(q["id"][0]))}
        status = (q.get("status") or [""])[0] or None
        n = min(int((q.get("n") or ["50"])[0]), 200)
        return {"ok": True, "status": status,
                "tasks": recent_tasks(limit=n, status=status),
                "counts": board_counts()}

    def _api_agents(self):
        return {"ok": True, "agents": agents_payload()}

    def _api_providers(self):
        return {"ok": True, "providers": stack_health().get("providers", [])}

    def _api_events(self, q):
        n = min(int((q.get("n") or ["100"])[0]), 500)
        et = ((q.get("type") or [""])[0]) or None
        return {"ok": True, "events": EVENTS.recent(n=n, event_type=et)}

    def _api_ask(self, body):
        goal = str(body.get("goal") or "").strip()
        if len(goal) < 8:
            return self._send(400, {"ok": False,
                                    "error": "goal too short (>=8 chars)"})
        files_hint = body.get("files") or []
        if isinstance(files_hint, str):
            files_hint = [f.strip() for f in files_hint.split(",") if f.strip()]
        log(f"/api/ask goal: {goal[:120]}")
        added, err, pool_msg = queue_goal(goal, files_hint)
        if added is None:
            return self._send(502, {"ok": False, "error": err})
        EVENTS.emit("goal_queued", status="ok", detail=f"{len(added)} tasks")
        return self._send(200, {"ok": True, "added": added, "pool": pool_msg,
                                "note": "subtasks queued on the board; "
                                        "agents will pick them up"})

    def _api_pool(self, body):
        action = body.get("action")
        if action == "start":
            cap = max(1, min(int(body.get("cap") or 2), 4))
            EVENTS.emit("pool_start", status="ok", detail=f"cap={cap}")
            return self._send(200, start_pool(cap))
        if action == "stop":
            EVENTS.emit("pool_stop", status="ok")
            return self._send(200, stop_pool())
        return self._send(400, {"ok": False,
                                "error": "action must be start|stop"})

    def _api_task(self, body):
        title = str(body.get("title") or "").strip()
        desc = str(body.get("description") or title).strip()
        files = body.get("files") or []
        if isinstance(files, str):
            files = [f.strip() for f in files.split(",") if f.strip()]
        # SECURITY: validate every owned path canonically (traversal/abs rejected).
        try:
            files = validate_file_list(WS_DIR, files)
        except Exception as e:
            return self._send(400, {"ok": False,
                                    "error": f"invalid file path: {e}"})
        if not title or not files:
            return self._send(400, {"ok": False,
                                    "error": "title and >=1 owned file required"})
        tid = taskboard.add_task(title, desc, files, priority=5)
        EVENTS.emit("task_added", task_id=tid, status="open")
        log(f"/api/task -> added #{tid} {title[:60]}")
        return self._send(200, {"ok": True, "added": [task_by_id(tid)]})

    def _api_chat(self, body):
        message = str(body.get("message") or "").strip()
        history = body.get("history") or []
        if len(message) < 2:
            return self._send(400, {"ok": False, "error": "message too short"})
        if len(message) > 4000:
            return self._send(400, {"ok": False,
                                    "error": "message too long (max 4000)"})
        intent = classify_intent(message)
        log(f"/api/chat ({intent}): {message[:100]}")
        if intent == "status":
            return self._send(200, {"ok": True, "type": "text",
                                    "intent": "status",
                                    "reply": status_summary(message)})
        if intent == "pool":
            r = start_or_stop_from(message)
            return self._send(200, {"ok": True, "type": "text",
                                    "intent": "pool",
                                    "reply": "POOL: " + r.get("msg", "") +
                                             "\n\n" + status_summary()})
        if intent == "build":
            added, err, pool_msg = queue_goal(message, body.get("files") or [])
            if added is None:
                return self._send(200, {"ok": True, "type": "text",
                                        "intent": "build_failed",
                                        "reply": "I read that as a build goal "
                                                 "but couldn't produce a valid "
                                                 "task plan.\n" + (err or "") +
                                                 "\nRephrase it concretely (name "
                                                 "the files to touch) or use the "
                                                 "manual task form below."})
            return self._send(200, {"ok": True, "type": "tasks",
                                    "intent": "build", "added": added,
                                    "pool": pool_msg,
                                    "reply": f"Goal split into {len(added)} "
                                              f"task(s) and queued — agents "
                                              f"({pool_msg})."})
        if intent in ("elysia", "research"):
            from elysia.core import server_api
            if intent == "research" or message.lower().startswith(
                    ("research ", "deep research", "investigate", "find out about")):
                res = server_api.deep_research(message)
            else:
                res = server_api.run_chat(message)
            return self._send(200, {"ok": True, "type": "text",
                                    "intent": intent,
                                    "reply": res.get("reply", ""),
                                    "status": res.get("status", "done")})
        # general question -> local model
        reply = general_chat(message, history)
        return self._send(200, {"ok": True, "type": "text",
                                "intent": "general", "reply": reply})


    def _api_agent(self, body):
        """Elysia master agent endpoint - runs a goal through the core engine."""
        task = str(body.get("task") or body.get("message") or "").strip()
        if len(task) < 3:
            return self._send(400, {"ok": False, "error": "task too short"})
        log(f"/api/agent task: {task[:120]}")
        try:
            from elysia.core import server_api
            res = server_api.run_agent(task, timeout_s=20)
            return self._send(200, {"ok": True, "status": res.get("status", "done"),
                                    "reply": res.get("reply", ""),
                                    "result": res.get("detail"),
                                    "scheduler": {
                                        "workers": SCHEDULER.workers.list() if SCHEDULER else [],
                                        "counts": taskboard.store().counts(),
                                    }})
        except Exception as e:
            EVENTS.emit("agent_error", status="error", error=str(e)[:200])
            return self._send(200, {"ok": False, "status": "error",
                                    "reply": f"Agent error: {str(e)[:200]}"})


def main():
    ap = argparse.ArgumentParser(description="Elysia JARVIS HUD server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8087)
    args = ap.parse_args()
    taskboard.init_db()
    os.makedirs(LOGS_DIR, exist_ok=True)
    # Canonical scheduler: lease expiry / timeouts / dep-failure recovery run
    # for the server's whole lifetime (restart-safe: state is in SQLite).
    try:
        start_scheduler_thread()
    except Exception as e:  # noqa: BLE001
        log(f"scheduler failed to start (server continues): {e}")
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    log(f"HUD listening on http://{args.host}:{args.port}  "
        f"(workspace={WS_DIR}, model={'UP' if model_ok() else 'DOWN'})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
