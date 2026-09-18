"""Independent health dimensions — deliberately NOT one magic score.

A single number ("system health 87%") hides which subsystem is actually broken,
so ``dimensions()`` reports each one separately, with the evidence behind the
verdict and the metrics that produced it:

    providers      registered/healthy/unprobed, rate-limited, slots
    scheduler      running, resource budget, in-flight claims, stale leases
    task_store     counts, stuck (expired-lease) tasks, blocked tasks, size
    workspace      exists/writable, file count, symlinks that point outside
    resources      RAM pressure, load average, disk free (low-spec hardware)
    security       what is enabled: shell, desktop, high-risk tools, net egress
    tests          last real test run recorded on the event bus
    git            repo?, branch, dirty files, unresolved conflicts
    memory         memory store dir, namespaces, entries, bounded?
    installation   bootstrapper manifest + config presence

Verdicts are ``ok``/``warn``/``fail``/``unknown``. ``unknown`` is a first-class
answer: it means the evidence to judge that dimension does not exist yet (for
example: no test has been run since this process started).
"""
from __future__ import annotations

import json
import os

OK, WARN, FAIL, UNKNOWN = "ok", "warn", "fail", "unknown"


def _dim(status: str, detail: str, **metrics) -> dict:
    return {"status": status, "detail": detail, "metrics": metrics}


def _providers(providers) -> dict:
    if providers is None:
        return _dim(UNKNOWN, "no provider manager attached")
    rows = providers.health_report()
    if not rows:
        return _dim(FAIL, "no providers registered — no AI execution possible")
    healthy = [r for r in rows if r.get("status") == "healthy"]
    unprobed = [r for r in rows if not r.get("probed")]
    bad = [r for r in rows if r.get("status") in ("unavailable", "rate_limited")]
    quarantined = [r for r in rows if r.get("circuit") == "open"]
    probing = [r for r in rows if r.get("circuit") == "half_open"]
    detail = (f"{len(healthy)}/{len(rows)} healthy"
              + (f", {len(unprobed)} never contacted" if unprobed else "")
              + (f", {len(bad)} unavailable/rate-limited" if bad else "")
              + (f", {len(quarantined)} quarantined (circuit open)"
                 if quarantined else "")
              + (f", {len(probing)} half-open (probing recovery)"
                 if probing else ""))
    status = OK
    if not healthy and not probing:
        status = FAIL
    elif unprobed or bad or quarantined:
        status = WARN
    return _dim(status, detail, total=len(rows), healthy=len(healthy),
                unprobed=len(unprobed), degraded=len(bad),
                quarantined=len(quarantined), half_open=len(probing),
                slots_free=sum(max(0, (r.get("max_concurrency")
                                       or r.get("concurrency", 0))
                                   - r.get("current_concurrency", 0))
                               for r in rows))


def _scheduler(master, scheduler) -> dict:
    sched = scheduler or getattr(master, "scheduler", None)
    if sched is None:
        return _dim(UNKNOWN, "no scheduler attached")
    store = getattr(sched, "store", None)
    budget = sched.current_budget()
    running = bool(getattr(master, "running", False)) or bool(
        getattr(sched, "running", False))
    leases = []
    if store is not None:
        leases = [t for t in store.list(limit=1000)
                  if t.get("status") in ("claimed", "running")
                  and (t.get("lease_expires_at") or 0) < (t.get("now") or 0)]
    detail = f"running={running}, budget={budget} slot(s)"
    status = OK
    if not running:
        status = WARN
        detail += " — not claiming work"
    if budget <= 0:
        status = WARN
        detail += "; resource budget exhausted (tasks queue)"
    return _dim(status, detail, budget=budget, running=running,
                stale_leases=len(leases))


def _task_store(store) -> dict:
    if store is None:
        return _dim(UNKNOWN, "no task store attached")
    counts = store.counts()
    blocked = len(store.blocked_tasks() or [])
    size = 0
    path = getattr(store, "db_path", "")
    try:
        size = os.path.getsize(path)
    except OSError:
        pass
    detail = (", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
              + (f"; {blocked} blocked" if blocked else ""))
    status = OK
    if counts.get("failed"):
        status = WARN
    if blocked:
        status = WARN
    return _dim(status, detail, blocked=blocked, db_bytes=size, **counts)


def _workspace(root) -> dict:
    if not root:
        return _dim(UNKNOWN, "no workspace root configured")
    if not os.path.isdir(root):
        return _dim(WARN, f"workspace does not exist yet: {root}")
    files = 0
    bytes_ = 0
    outside = []
    real_root = os.path.realpath(root)
    for dp, dn, fn in os.walk(real_root):
        dn[:] = [d for d in dn if d not in (".git", "node_modules", "__pycache__")]
        for f in fn:
            p = os.path.join(dp, f)
            files += 1
            try:
                bytes_ += os.path.getsize(p)
            except OSError:
                pass
            if os.path.islink(p):
                target = os.path.realpath(p)
                if not (target == real_root or target.startswith(real_root + os.sep)):
                    outside.append(os.path.relpath(p, real_root))
    writable = os.access(real_root, os.W_OK)
    status = OK if writable else FAIL
    detail = (f"{files} file(s), {bytes_ // 1024} KiB"
              + ("" if writable else "; NOT writable"))
    if outside:
        status = FAIL
        detail += f"; {len(outside)} symlink(s) escape the workspace"
    return _dim(status, detail, files=files, bytes=bytes_, writable=writable,
                escaping_symlinks=outside[:5])


def _resources(resources) -> dict:
    if resources is None:
        return _dim(UNKNOWN, "no resource manager attached")
    try:
        report = resources.report()
        pressure = bool(report.get("memory_pressure"))
        disk = int(report.get("disk_free_mb") or 0)
        free = int(report.get("memory_mb_available") or 0)
        total = int(report.get("memory_mb_total") or 0)
    except Exception as e:  # noqa: BLE001 — diagnostics must never raise
        return _dim(UNKNOWN, f"resource probe failed: {e}"[:200])
    status = OK
    detail = (f"{free} MiB free of {total} MiB, "
              f"budget={report.get('local_worker_budget')} local worker(s) "
              f"({report.get('active_workers')} active), "
              f"disk={disk} MiB free, load={report.get('load_avg')}")
    if pressure:
        status = WARN
        detail += " — memory pressure: expensive work is queued"
    if disk and disk < 2048:
        status = FAIL if disk < 512 else WARN
        detail += " — disk pressure"
    metrics = {k: v for k, v in report.items()
               if isinstance(v, (int, float, str, bool)) and k != "disk_free_mb"}
    return _dim(status, detail, disk_free_mb=disk, **metrics)


def _security(cfg, tools) -> dict:
    tools_cfg = getattr(cfg, "tools", None)
    shell = bool(getattr(tools_cfg, "enable_shell", False))
    high = bool(getattr(tools_cfg, "allow_high_risk", False))
    desktop = bool(tools is not None and getattr(tools, "desktop", None) is not None
                   and tools.desktop.available())
    # The *effective* grants (after the config ceiling) are what the runtime
    # actually enforces, so report those rather than the raw config list.
    grants = list(getattr(tools, "roles", {}).values()) if tools is not None else \
        list(getattr(tools_cfg, "default_permissions", None) or [])
    ceiling = sorted({t for g in grants for t in g}) if tools is not None else \
        list(getattr(tools_cfg, "default_permissions", None) or [])
    write = any("workspace:write" in g for g in grants)
    net = any("net:http" in g for g in grants)
    detail = (f"shell={'on' if shell else 'off'}, high-risk tools="
              f"{'on' if high else 'off'}, desktop="
              f"{'available' if desktop else 'unavailable'}, "
              f"workspace write={'granted' if write else 'denied'}, "
              f"network={'granted' if net else 'denied'}")
    status = WARN if (shell or high) else OK
    if shell or high:
        detail += " — elevated capabilities are enabled by config"
    return _dim(status, detail, shell=shell, high_risk=high, desktop=desktop,
                workspace_write=write, network=net,
                permissions=sorted(ceiling))


def _tests(events) -> dict:
    if events is None:
        return _dim(UNKNOWN, "no event bus attached")
    runs = [e for e in events.recent(2000)
            if e.get("event_type") in ("test.completed", "test.started")]
    if not runs:
        return _dim(UNKNOWN, "no test run recorded in this process")
    last = runs[-1]
    ok = last.get("status") == "ok"
    return _dim(OK if ok else WARN,
                f"last test run: {last.get('status')} {last.get('detail') or ''}".strip(),
                runs=len(runs), last_status=last.get("status"))


def _git(root) -> dict:
    if not root:
        return _dim(UNKNOWN, "no workspace root")
    from .git import current_branch, dirty_files, has_conflicts, is_repo
    if not is_repo(root):
        return _dim(WARN, "workspace is not a git repository — checkpoints unavailable")
    dirty = dirty_files(root)
    conflicts = has_conflicts(root)
    status = WARN if conflicts else OK
    detail = (f"branch={current_branch(root)}, {len(dirty)} dirty file(s)"
              + (f", {len(conflicts)} UNRESOLVED conflict(s)" if conflicts else ""))
    return _dim(status, detail, branch=current_branch(root), dirty=len(dirty),
                conflicts=conflicts)


def _memory(state_dir) -> dict:
    """Memory dimension — reported through the CANONICAL store.

    Counting files by hand here used to disagree with the store (it treated the
    store's dedup index as data and looked one directory too high), which made
    the dimension report a phantom store. Whatever `Memory` says is the truth.
    """
    if not state_dir:
        return _dim(UNKNOWN, "no memory directory configured")
    if not os.path.isdir(state_dir):
        return _dim(WARN, f"memory store not created yet: {state_dir}")
    try:
        from .memory import Memory
        stats = Memory(state_dir).stats()
    except Exception as e:  # noqa: BLE001 — diagnostics must never raise
        return _dim(UNKNOWN, f"memory probe failed: {e}"[:200])
    namespaces = len(stats.get("namespaces") or {})
    entries = int(stats.get("entries") or 0)
    cap = int(stats.get("max_entries") or 0)
    if not namespaces:
        return _dim(WARN, f"memory store empty: {state_dir}",
                    namespaces=0, entries=0)
    status = OK
    detail = (f"{namespaces} namespace(s), {entries} entr(y|ies)"
              f" (cap {cap})")
    if cap and entries > cap * 0.9:
        status = WARN
        detail += " — near the entry cap: compaction will compress old records"
    return _dim(status, detail, namespaces=namespaces, entries=entries,
                max_entries=cap,
                namespaces_detail=stats.get("namespaces"))


def _installation(root) -> dict:
    manifest = os.path.join(root, "state", "install.json")
    if os.path.isfile(manifest):
        try:
            with open(manifest, encoding="utf-8") as f:
                data = json.load(f)
            return _dim(OK, f"install manifest: {data.get('platform', '?')} / "
                            f"{data.get('python', '?')}", manifest=manifest)
        except (OSError, ValueError):
            return _dim(WARN, "install manifest present but unreadable")
    return _dim(WARN, "no install manifest — run ./install.sh (or install.ps1) to "
                      "normalise this checkout", manifest=manifest)


def dimensions(master=None, *, store=None, providers=None, workspace_root=None,
               cfg=None, events=None, resources=None, tools=None,
               memory_dir=None, repo_root=None) -> dict:
    """Every health dimension, resolved independently (never a magic score)."""
    master = master
    store = store if store is not None else getattr(master, "store", None)
    providers = providers if providers is not None else getattr(master, "providers", None)
    workspace_root = workspace_root or getattr(master, "workspace_root", None)
    cfg = cfg if cfg is not None else getattr(master, "cfg", None)
    events = events if events is not None else getattr(master, "events", None)
    tools = tools if tools is not None else getattr(master, "tools", None)
    if resources is None:
        try:
            from .resources import ResourceManager
            resources = ResourceManager.from_config(cfg)
        except Exception:  # noqa: BLE001 — a broken probe must not break health
            resources = None
    if repo_root is None:
        here = os.path.dirname(os.path.abspath(__file__))       # <root>/elysia/core
        repo_root = os.path.dirname(os.path.dirname(here))      # <root>
    if memory_dir is None:
        memory_dir = (getattr(getattr(cfg, "memory", None), "dir", "")
                      or os.path.join(repo_root, "state", "memory"))

    report = {
        "providers": _providers(providers),
        "scheduler": _scheduler(master, getattr(master, "scheduler", None)),
        "task_store": _task_store(store),
        "workspace": _workspace(workspace_root),
        "resources": _resources(resources),
        "security": _security(cfg, tools),
        "tests": _tests(events),
        "git": _git(workspace_root),
        "memory": _memory(memory_dir),
        "installation": _installation(repo_root),
    }
    tally = {OK: 0, WARN: 0, FAIL: 0, UNKNOWN: 0}
    for d in report.values():
        tally[d["status"]] = tally.get(d["status"], 0) + 1
    report["summary"] = {"dimensions": len(report), "verdicts": tally,
                         "note": "no aggregate score by design — read each dimension"}
    return report


def failing(report: dict) -> list[str]:
    """Names of dimensions that are unusable (fail) — never warn/unknown."""
    return sorted(k for k, v in report.items()
                  if isinstance(v, dict) and v.get("status") == FAIL)
