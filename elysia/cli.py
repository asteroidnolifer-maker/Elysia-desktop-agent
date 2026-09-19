#!/usr/bin/env python3
"""Elysia CLI.

All commands are safe to run read-only when possible; mutating commands
(excluding start/stop/status/checkpoint) require confirmation where destructive.

Usage:
    elysia start|stop|status [--host H] [--port P]
    elysia doctor
    elysia tasks [status-filter]
    elysia task <id>
    elysia task add <title> [--files a,b] [--priority N] [--deps 1,2]
                           [--template feature] [--dedup]
    elysia task cancel|cancel-cascade <id>
    elysia task retry <id>
    elysia task pause|resume <id>
    elysia workers
    elysia providers [--catalog]
    elysia login <provider> [--paste KEY] [--no-browser]
    elysia login --status | --load | --logout <provider>
    elysia hf models|datasets
    elysia hf model <repo>
    elysia hf recommend [available_mb]
    elysia knowledge list|search|show <query>
    elysia prompt [style]        (claude-code, hermes, openhands, research, elysia)
    elysia cost
    elysia resources
    elysia agents [role]
    elysia research "<question>"
    elysia research --deep --breadth 3 --depth 2 "<question>"  (openreacher)
    elysia orx "<question>" [--breadth N] [--depth N]
    elysia template <name>
    elysia checkpoint <message>
    elysia checkpoints [n]
    elysia rollback <sha> [--hard]
    elysia since-checkpoint
    elysia skills list|import <path>
    elysia memory search|recall|timeline|stats|compact|backup|forget|invalidate|correct
    elysia healing policies | report | classify "<error text>"
    elysia plugins list|load <name>
    elysia audit
    elysia test [--unit|--chaos|--e2e]
    elysia logs [n]
    elysia master run "<goal>" [--no-wait] [--timeout S] [--json]
    elysia master status | agents | simulate "<goal>" | route [--caps chat,coding]
    elysia health [--json]
    elysia tools [--registry [--role ROLE] | --check NAME | --missing]
    elysia db health | backup [DIR] | restore FILE | vacuum
    elysia workflow start --file nodes.json | tick | state NAME | approve|deny --node ID
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elysia.core.config import (Config, default_config, load_config, to_dict,
                                validate)
from elysia.core.doctor import do_doctor, print_doctor
from elysia.core.tasks import TaskStore


def _root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# -- bootstrap services --------------------------------------------------------
def cmd_start(args):
    script = os.path.join(_root(), "elysia-run.sh")
    if not os.path.exists(script):
        print("elysia-run.sh not found; run the server directly instead")
        return 1
    env = dict(os.environ)
    if args.port:
        env["ELYSIA_HTTP_ADDR"] = f":{args.port}"
    r = subprocess.run(["bash", script, "start"], env=env)
    return r.returncode


def cmd_stop(_args):
    script = os.path.join(_root(), "elysia-run.sh")
    if os.path.exists(script):
        return subprocess.run(["bash", script, "stop"]).returncode
    return 0


def cmd_status(_args):
    cfg = load_config()
    host, port = cfg.api.host, cfg.api.port
    from elysia.core.doctor import _port_open
    print(f"api       : {'UP' if _port_open(host, port) else 'down'} "
          f"({host}:{port})")
    for p in cfg.providers:
        from elysia.core.providers import Provider
        prov = Provider(p)
        print(f"provider  : {p.label:14} {prov.check_health()}  "
              f"(model={p.model})")
    return 0


# -- doctor -------------------------------------------------------------------
def cmd_doctor(_args):
    results = do_doctor()
    print_doctor(results)
    return 0 if results["ok"] else 1


# -- tasks --------------------------------------------------------------------
def _store():
    from elysia.core.tasks import TaskStore
    return TaskStore(os.path.join(_root(), "orchestrator", "taskboard.sqlite"))


def cmd_tasks(args):
    s = _store()
    if args.filter:
        rows = s.list(status=args.filter, limit=200)
    else:
        rows = s.list(limit=200)
    if not rows:
        print("(no tasks)")
    for t in rows:
        print(f"#{t['id']:<4} [{str(t['status']):>16}] "
              f"p{t['priority']} {t['agent_role'] or '':14} {t['title'][:50]}")
    print()
    print("counts:", json.dumps(s.counts()))


def cmd_task(args):
    s = _store()
    if args.action == "show":
        t = s.get(int(args.task_id))
        if not t:
            print("task not found")
            return 1
        print(json.dumps({k: (v if not isinstance(v, float) else round(v, 2))
                          for k, v in t.items() if k not in ("usage_json",)},
                         indent=1, default=str))
        return 0
    if args.action == "add":
        files = (args.files or "").split(",") if args.files else []
        deps = [int(x) for x in (args.deps or "").split(",") if x]
        kw = {"title": args.title, "owned_files": files, "priority": args.priority,
              "dependencies": deps}
        if args.template:
            from elysia.core.templates import expand_template
            ids = expand_template(args.template, args.title, store=s, **kw)
            if args.dedup:
                from elysia.core.templates import dedup_hash
                for tid in ids:
                    s._update(tid, dedup_hash=dedup_hash(args.title))
            s.list()
            print(f"expanded template {args.template}: task ids {ids}")
            return 0
        if args.dedup:
            from elysia.core.templates import dedup_hash
            kw["dedup_hash"] = dedup_hash(args.title)
            dup = s.find_duplicate(kw["dedup_hash"])
            if dup:
                print(f"duplicate (existing #{dup['id']} {dup['status']}), not "
                      f"added; use --no-verify to force")
                return 0
        tid = s.add_task(**kw)
        s.mark_ready(tid)
        print(f"added task #{tid}")
        return 0
    # state ops
    tid = int(args.task_id)
    if args.action == "cancel":
        affected = s.cancel(tid, by="cli")
        print("cancelled:", affected)
        return 0
    if args.action == "retry":
        s._update(tid, attempts=0)
        ok = s.retry(tid, reset_attempts=True)
        print("retried" if ok else "not retryable (not terminal)")
        return 0 if ok else 1
    if args.action == "pause":
        print(("paused" if s.pause(tid) else "not paused"))
        return 0
    if args.action == "resume":
        print(("resumed" if s.resume(tid) else "not resumed"))
        return 0
    print("unknown action")
    return 1


# -- workers / providers -------------------------------------------------------
def cmd_workers(_args):  # noqa: D401
    from elysia.core.scheduler import WorkerRegistry
    wr = WorkerRegistry()
    print("workers (in-memory registry, see run/pid for live ones):")
    for w in wr.list():
        print(" ", w)
    return 0


def cmd_providers(args):
    if getattr(args, "catalog", False):
        from elysia.core.provider_presets import describe
        print(f"{'provider':<16} {'kind':<7} {'ready':<6} model / what is missing")
        for row in describe():
            state = "yes" if row["ready"] else "no"
            detail = row["model"] if row["ready"] else "; ".join(row["missing"])
            print(f"{row['name']:<16} {row['kind']:<7} {state:<6} {detail}")
        print("\nactivate a cloud provider: elysia login <name>")
        print("cli agents reuse the login of their installed binary "
              "(claude, codex, gemini, opencode, openclaw)")
        return 0
    cfg = load_config()
    from elysia.core.providers import ProviderManager
    pm = ProviderManager()
    pm.register_many(cfg.providers)
    for p in pm.list():
        cp = p.capacity()
        rp = p.resource_profile()
        tag = "LOCAL" if rp["local"] else "remote"
        print(f"{cp['name']:20} [{tag}] status={cp['status']:12} "
              f"concurrency={cp['current_concurrency']}/{cp['max_concurrency']} "
              f"requests={cp['requests']} failures={cp['failures']} "
              f"avg_lat={cp['avg_latency_s']}s")
        print(f"{'':20} class={rp['resource_class']:<11} "
              f"cpu_cost={rp['cpu_cost']:<5} ram={rp['ram_cost_mb']} MB "
              f"privacy={rp['privacy']} circuit={rp['circuit']}")
        if cp["last_error"]:
            print(f"   last_error: {cp['last_error'][:100]}")
    summary = pm.resource_summary()
    print(f"\nfleet: {summary['providers']} provider(s), "
          f"{summary['local']} local / {summary['remote']} remote | "
          f"local slots={summary['local_concurrency']} "
          f"remote slots={summary['remote_concurrency']} | "
          f"est. local model RAM={summary['estimated_local_ram_mb']} MB | "
          f"quarantined={summary['quarantined']}")
    total = pm.usage_totals()
    print("\nestimated totals:", json.dumps(total, indent=1))
    return 0


# -- login (desktop-browser provider setup) ---------------------------------
def cmd_login(args):
    from elysia.core import browser_login
    if args.load:
        n = browser_login.load_env_file()
        print(f"loaded {n} credential(s) from {browser_login.ENV_FILE}")
        return 0
    if args.status:
        st = browser_login.stored_status()
        from elysia.core.provider_presets import describe
        env_ready = [row["name"] for row in describe() if row["ready"]]
        print("stored keys:", json.dumps(st["stored"], indent=1) if st["stored"]
              else f"none ({st['path']})")
        print("active providers:", ", ".join(env_ready) or "(local only)")
        return 0
    if args.logout:
        from elysia.core.provider_presets import CATALOG
        entry = CATALOG.get(args.provider or "")
        if not entry:
            print("unknown provider; see elysia providers --catalog")
            return 1
        removed_any = False
        for v in entry.get("env", ()) or ():
            if browser_login.remove_key(v):
                removed_any = True
        print(f"removed stored key(s) for {args.provider}" if removed_any
              else f"no stored key for {args.provider}")
        return 0
    if not args.provider:
        print("usage: elysia login <provider> [--paste KEY] [--no-browser]")
        print("       elysia login --status | --load | --logout <provider>")
        return 1
    res = browser_login.login(args.provider, paste_value=args.paste or None,
                              no_browser=args.no_browser)
    if res.get("url"):
        print("page:", res["url"])
    print("browser:  ", "opened" if res.get("opened") else
          "not opened (open the URL above manually)")
    print(res.get("message", ""))
    return 0 if res.get("ok") else 1


# -- huggingface --------------------------------------------------------------
def cmd_hf(args):
    from elysia.core import hf as hf_mod
    if args.action == "models":
        for m in [{"name": n, **m} for n, m in sorted(hf_mod.MODELS.items())]:
            print(f"{m['name']:<24} ~{m['size_mb']:>5}MB  "
                  f"[{','.join(m['capabilities'])}] {m['note']}")
            print(f"{'':<24} gguf: hf.co/{m['gguf']} ({m['file_hint']})")
        return 0
    if args.action == "datasets":
        for d in [ {"name": n, **d} for n, d in sorted(hf_mod.DATASETS.items())]:
            print(f"{d['name']:<24} [{d['task']:<11}] {d['note']}")
            print(f"{'':<24} {d['url']}")
        return 0
    if args.action == "model":
        info = hf_mod.resolve(args.repo)
        if not info.get("ok"):
            print(f"could not resolve {args.repo}: {info.get('error', 'offline')}")
            return 1
        print(json.dumps({k: v for k, v in info.items() if k != "ok"},
                         indent=1))
        return 0
    if args.action == "recommend":
        try:
            avail = int(args.repo)
        except (TypeError, ValueError):
            avail = 4000
        name = hf_mod.recommend(avail)
        m = hf_mod.MODELS[name]
        print(f"{name} (~{m['size_mb']}MB) — {m['note']}")
        print(f"gguf: hf.co/{m['gguf']}")
        return 0
    print("usage: elysia hf models|datasets|model <repo>|recommend <avail_mb>")
    return 1


# -- jarvis (one natural-language front door) --------------------------------------
def cmd_jarvis(args):
    from elysia.core.jarvis import classify, handle
    text = args.request or ""
    if not text:
        print("usage: elysia jarvis "
              "\"what's running?\" | \"which tool scans ports?\" | ...")
        return 1
    print(f"[route: {classify(text)}]", file=sys.stderr)
    r = handle(text, deep=bool(getattr(args, "deep", False)))
    print(r.get("text", ""))
    if r.get("report_path"):
        print("\n[report saved]", r["report_path"])
    return 0 if r.get("ok") else 1


# -- brief (Jarvis-style status fusion) -------------------------------------------
def cmd_brief(args):
    from elysia.core.briefing import brief
    from elysia.core.config import load_config
    from elysia.core.providers import ProviderManager
    from elysia.core.tasks import TaskStore
    import os
    store = None
    try:
        db = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "orchestrator", "taskboard.sqlite")
        if os.path.exists(db):
            store = TaskStore(db)
    except Exception:  # noqa: BLE001
        store = None
    pm = None
    try:
        cfg = load_config()
        pm = ProviderManager()
        if cfg.providers:
            pm.register_many(cfg.providers)
    except Exception:  # noqa: BLE001
        pm = None
    topic = getattr(args, "topic", None) or ""
    report = brief(topic, store=store, providers=pm)
    print(report["text"])
    return 0 if report["ok"] else 1


# -- tools (machine capability catalog) ------------------------------------------
def cmd_health(args):
    """Independent health dimensions — never one misleading aggregate score."""
    from elysia.core.health import dimensions, failing
    mc = _master_controller()
    rep = dimensions(mc, tools=getattr(mc, "tools", None), cfg=getattr(mc, "cfg", None))
    if args.json:
        print(json.dumps(rep, indent=1, default=str))
        return 0
    marks = {"ok": "ok  ", "warn": "warn", "fail": "FAIL", "unknown": "?   "}
    for name, dim in rep.items():
        if not isinstance(dim, dict) or "status" not in dim:
            continue
        print(f"[{marks.get(dim['status'], '?   ')}] {name:<13} {dim['detail']}")
    verdicts = rep["summary"]["verdicts"]
    print(f"dimensions: {verdicts['ok']} ok, {verdicts['warn']} warn, "
          f"{verdicts['fail']} fail, {verdicts['unknown']} unknown")
    return 1 if failing(rep) else 0


def cmd_tools(args):
    from elysia.core import toolcatalog as tc
    if getattr(args, "registry", False):
        from elysia.core.toolkit import build_tools, tool_audit
        from elysia.core.workspace import Workspace
        cfg = load_config()
        layer = build_tools(Workspace(cfg.workspace.root), cfg=cfg)
        role = getattr(args, "role", None)
        if role:
            audit = tool_audit(layer, role)
            if args.json:
                print(json.dumps(audit, indent=1, default=str))
                return 0
            print(f"role {role}: granted={', '.join(audit['granted']) or '-'}")
            for row in audit["rows"]:
                print(f"  [{'allow' if row['allowed'] else 'deny '}] "
                      f"{row['tool']:<20} {row['risk']:<9} {row['reason']}")
            return 0
        rows = layer.describe()
        if args.json:
            print(json.dumps({"tools": rows, "roles": layer.roles_report()},
                             indent=1, default=str))
            return 0
        print(f"runtime tool registry: {len(rows)} tool(s)")
        for r in rows:
            print(f"  {r['name']:<20} {r['risk']:<9} "
                  f"{','.join(r['permissions'])}")
        print("roles (write = may modify files):")
        for r in layer.roles_report():
            print(f"  {r['role']:<20} write={'yes' if r['can_write'] else 'no ':<3} "
                  f"{len(r['tools'])} tool(s)")
        return 0
    if getattr(args, "check", None):
        r = tc.detect(args.check)
        state = "INSTALLED" if r["installed"] else "not installed"
        print(f"{r['name']}: {state}" + (f" ({r['path']})" if r.get("path") else ""))
        print(f"  group: {r.get('group', '-')} | purpose: {r.get('purpose', '-')}")
        if not r["installed"]:
            doc = tc.knowledge_for(args.check)
            if doc:
                print("  knowledge:")
                for line in doc.splitlines()[:6]:
                    print("    " + line)
            print("  install policy: operator-run only "
                  "(docs/security/SECURITY_TOOLING.md)")
        return 0
    if getattr(args, "missing", False):
        rows = [r for r in tc.scan() if not r["installed"]]
        if not rows:
            print("nothing missing — full catalog present")
            return 0
        print(f"{len(rows)} catalog tool(s) not on this machine:")
        cur = None
        for r in rows:
            if r["group"] != cur:
                cur = r["group"]
                print(f"  [{cur}]")
            print(f"    {r['name']:<14} {r['purpose']}")
        return 0
    s = tc.summary()
    print(f"machine tool catalog: {s['installed']}/{s['total']} installed "
          f"(groups: {', '.join(s['groups']) or '-'})")
    if getattr(args, "group", None):
        rows = [r for r in s["rows"]
                if r["group"] == args.group]
    else:
        rows = s["rows"]
    cur = None
    for r in rows:
        if not getattr(args, "group", None) and r["group"] != cur:
            cur = r["group"]
            print(f"  [{cur}]")
        mark = "+" if r["installed"] else "-"
        print(f"  {mark} {r['name']:<14} {r['purpose']}")
    return 0


# -- knowledge (vendored security-tooling docs) --------------------------------
def cmd_knowledge(args):
    from elysia.core import knowledge as kb
    if args.action == "list":
        st = kb.stats()
        print(f"knowledge base: {st['entries']} entries in {st['dir']}")
        for cat, n in sorted(st["categories"].items()):
            print(f"  {cat:<20} {n}")
        return 0
    if args.action == "search":
        q = args.query or ""
        hits = kb.search(q)
        if not hits:
            print("no matches")
            return 0
        for h in hits:
            print(f"{h['name']:<16} [{h['category']}] risk={h['risk']} "
                  f"score={h['score']}")
            print(f"  {h['purpose'][:100]}")
        return 0
    if args.action == "show":
        hits = kb.search(args.query or "", limit=1)
        if not hits:
            print("no matches")
            return 1
        print(kb.for_context(args.query, max_entries=1))
        return 0
    return 1


# -- prompt styles -------------------------------------------------------------
def cmd_prompt(args):
    from elysia.core.prompts import get_style, list_styles, system_prompt
    if args.style_name:
        print(system_prompt(args.style_name))
        return 0
    active = get_style()
    for row in list_styles():
        mark = "*" if row["active"] else " "
        print(f"{mark} {row['name']:<14} {row['description']}")
    print(f"\nactive: {os.environ.get('ELYSIA_PROMPT_STYLE', 'elysia')} "
          f"(set ELYSIA_PROMPT_STYLE or pass --style)")
    return 0


def cmd_cost(_args):
    from elysia.core.telemetry import CostTracker
    ct = CostTracker()
    print(json.dumps({"grand_total": ct.grand_total(),
                      "by_provider_model": ct.totals()}, indent=1))
    return 0


def _resources_payload() -> dict:
    """One honest resource picture: system, slots, holders, waiting work."""
    from elysia.core.resources import ResourceManager
    cfg = load_config()
    rm = ResourceManager.from_config(cfg)
    out = {"system": rm.report(), "limits": {},
           "slots": {"held": [], "counts": {}, "waiting": {}},
           "tasks": {"running": [], "waiting": []},
           "local_model": {}, "providers": {}}
    try:
        mc = _master_controller()
        r = mc.resource_report()
        out["limits"] = r.get("limits") or {}
        out["slots"] = {"held": (r.get("ledger") or {}).get("held", []),
                        "counts": (r.get("ledger") or {}).get("counts", {}),
                        "waiting": (r.get("ledger") or {}).get("waiting", {})}
        snap = r.get("snapshot") or {}
        out["system"].update({
            "cpu_pct": snap.get("cpu_pct"),
            "memory_mb_available": snap.get("mem_available_mb", -1),
            "swap_used_mb": snap.get("swap_used_mb", -1),
            "disk_free_mb": snap.get("disk_free_mb", -1),
            "temperature_c": snap.get("temperature_c"),
            "active_local_inference": snap.get("active_local_inference", 0),
            "active_builds": snap.get("active_builds", 0),
            "heavy_in_use": snap.get("heavy_in_use", 0),
            "top_processes": snap.get("per_process") or [],
        })
        q = mc.queue_report()
        out["tasks"] = {"running": q["running"], "waiting": q["waiting"]}
        out["local_model"] = {"slots": (q["local_slot"] or {}).get("slots"),
                              "running": (q["local_slot"] or {}).get("running"),
                              "queued": (q["local_slot"] or {}).get("queued"),
                              "warm": (r.get("pool") or {}).get("warm", {}),
                              "stats": (r.get("pool") or {}).get("stats", {})}
        out["providers"] = r.get("providers") or {}
        out["router"] = (r.get("router") or {}).get("stats", {})
    except Exception as e:  # noqa: BLE001 — reporting must never crash the CLI
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _print_resources(rep: dict) -> None:
    sys_ = rep.get("system") or {}
    cpu = sys_.get("cpu_pct")
    print(f"CPU: {cpu if cpu is not None else '?'}%  "
          f"cores={sys_.get('cpu_count')}  load={sys_.get('load_avg')}")
    print(f"RAM: {sys_.get('memory_mb_available', -1)} MB free of "
          f"{sys_.get('memory_mb_total', -1)} MB   "
          f"swap used={sys_.get('swap_used_mb', -1)} MB")
    print(f"disk free={sys_.get('disk_free_mb', -1)} MB  "
          f"gpu={sys_.get('gpu_available')}  "
          f"temp={sys_.get('temperature_c')}C")
    lim = rep.get("limits") or {}
    if lim:
        print(f"\nthresholds: cpu busy={lim.get('cpu_busy_pct')}% "
              f"high={lim.get('cpu_high_pct')}% "
              f"critical={lim.get('cpu_critical_pct')}% | "
              f"ram min={lim.get('ram_min_free_mb')} MB "
              f"block-infer={lim.get('ram_block_infer_mb')} MB")
    counts = (rep.get("slots") or {}).get("counts") or {}
    if counts:
        active = {k: v for k, v in counts.items() if v}
        print(f"slots in use: {active or 'none'}")
    held = (rep.get("slots") or {}).get("held") or []
    for h in held:
        print(f"  held: {h['resource_class']:<12} by {h['owner']:<14} "
              f"priority={h['priority']} age={h['age_s']}s")
    lm = rep.get("local_model") or {}
    if lm.get("slots") is not None:
        print(f"\nlocal model: {lm.get('running')} running / "
              f"{lm.get('slots')} slot(s), {lm.get('queued')} queued")
    for name, st in (lm.get("warm") or {}).items():
        print(f"  warm: {name} loaded={st.get('loaded')} "
              f"idle={st.get('idle_s')}s loads={st.get('loads')} "
              f"unloads={st.get('unloads')}")
    prov = rep.get("providers") or {}
    if prov:
        print(f"\nproviders: {prov.get('providers')} total "
              f"({prov.get('local')} local / {prov.get('remote')} remote) | "
              f"local slots={prov.get('local_concurrency')} "
              f"remote slots={prov.get('remote_concurrency')} "
              f"quarantined={prov.get('quarantined')}")
    running = (rep.get("tasks") or {}).get("running") or []
    if running:
        print(f"\nRUNNING ({len(running)}):")
        for t in running[:12]:
            print(f"  #{t['task_id']} {t['title'][:44]:<44} "
                  f"{t['status']:<9} {t.get('resource_class') or '-':<12} "
                  f"provider={t.get('provider') or '-'}")
    waiting = (rep.get("tasks") or {}).get("waiting") or []
    print(f"\nWAITING ({len(waiting)}):")
    for t in waiting[:15]:
        print(f"  #{t['task_id']} {t['title'][:44]:<44} "
              f"class={t.get('resource_class') or '-':<12} "
              f"priority={t.get('priority_class')}")
        print(f"      reason: {t.get('reason') or 'not startable'}")
    if rep.get("error"):
        print(f"\nnote: {rep['error']}")


def cmd_resources(args):
    # `elysia queue` / `elysia models` are views of this one report.
    view = getattr(args, "view", None)
    if view == "queue":
        return cmd_queue(args)
    if view == "models":
        return cmd_models(args)
    if getattr(args, "watch", False):
        interval = max(0.5, float(getattr(args, "interval", 2.0) or 2.0))
        try:
            while True:
                print("\n" + "=" * 72)
                rep = _resources_payload()
                if getattr(args, "json", False):
                    print(json.dumps(rep, indent=1, default=str))
                else:
                    _print_resources(rep)
                import time as _t
                _t.sleep(interval)
        except KeyboardInterrupt:
            print("\nstopped")
            return 0
    rep = _resources_payload()
    if getattr(args, "json", False):
        print(json.dumps(rep, indent=1, default=str))
        return 0
    _print_resources(rep)
    return 0


def cmd_queue(args):
    mc = _master_controller()
    q = mc.queue_report()
    if getattr(args, "json", False):
        print(json.dumps(q, indent=1, default=str))
        return 0
    local = q["local_slot"]
    print(f"local model slot: {local['running']}/{local['slots']} running, "
          f"{local['queued']} queued, {local['not_held']} ledger-held")
    print(f"\nRUNNING ({len(q['running'])}):")
    for t in q["running"]:
        print(f"  #{t['task_id']} {t['title'][:44]:<44} {t['status']:<9} "
              f"priority={t.get('priority_class')} "
              f"class={t.get('resource_class') or '-'} "
              f"provider={t.get('provider') or '-'}")
    print(f"\nQUEUED / NOT STARTED ({len(q['waiting'])}):")
    if not q["waiting"]:
        print("  (nothing waiting)")
    for t in q["waiting"]:
        print(f"  #{t['task_id']} {t['title'][:44]:<44} status={t.get('status')}")
        print(f"      resource={t.get('resource_class')} "
              f"priority={t.get('priority_class')} "
              f"needs={','.join(t.get('needs') or [])}")
        print(f"      reason: {t.get('reason')}")
    return 0


def cmd_models(args):
    mc = _master_controller()
    rep = mc.resource_report()
    pool = rep.get("pool") or {}
    provider_rows = []
    for row in (mc.providers.resource_profiles()):
        provider_rows.append(row)
    payload = {"local_slots": pool.get("slots"),
               "running": pool.get("running"),
               "queued": pool.get("queued"),
               "stats": pool.get("stats"),
               "warm": pool.get("warm"),
               "batching": pool.get("batching"),
               "providers": provider_rows}
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=1, default=str))
        return 0
    print(f"local model slots: {payload['local_slots']} "
          f"(heavy_slots={rep.get('limits', {}).get('heavy_exclusive')})")
    for row in provider_rows:
        tag = "LOCAL" if row["local"] else "remote"
        print(f"\n{row['name']}  [{tag}]  {row['model']}")
        print(f"  class={row['resource_class']:<11} "
              f"cpu_cost={row['cpu_cost']:<5} ram={row['ram_cost_mb']} MB  "
              f"concurrency={row['concurrency']}  "
              f"latency={row['observed_latency_s']}s")
        print(f"  status={row['status']} circuit={row['circuit']} "
              f"privacy={row['privacy']} availability={row['availability']}")
        for note in row["notes"]:
            print(f"  note: {note}")
    for name, st in (payload.get("warm") or {}).items():
        print(f"warm: {name} loaded={st['loaded']} idle={st['idle_s']}s "
              f"loads={st['loads']} unloads={st['unloads']}")
    print("batching:", (payload.get("batching") or {}).get("note"))
    return 0


# -- agents -------------------------------------------------------------------
def cmd_agents(args):
    from elysia.core.agents import ROLES
    if args.role:
        if args.role not in ROLES:
            print("unknown role", args.role)
            return 1
        cfg = load_config()
        from elysia.core.providers import ProviderManager
        from elysia.core.tasks import TaskStore
        from elysia.core.agents import AgentPipeline
        pm = ProviderManager()
        pm.register_many(cfg.providers)
        store = TaskStore(os.path.join(_root(), "orchestrator", "taskboard.sqlite"))
        pipe = AgentPipeline(pm, store, cfg=cfg)
        fn = getattr(pipe, {"planner": "plan_task",
                            "architect": "architect"}.get(args.role,
                                                          "plan_task"), None)
        goal = args.prompt or "Describe the current repository structure."
        if args.role == "planner":
            from elysia.core.project import ProjectIntel
            intel = ProjectIntel(_root())
            res = pipe.plan_task(goal, intel.to_context())
        else:
            res = pipe.architect(goal)
        print(json.dumps(res, indent=1, default=str)[:4000])
        return 0 if res.get("ok") else 1
    print("available agent roles:")
    for r in ROLES:
        print(f"  {r}")
    return 0


# -- master control plane ------------------------------------------------------
def _master_controller():
    from elysia.core.master import MasterController
    from elysia.core.providers import ProviderManager
    from elysia.core.resources import ResourceManager
    from elysia.core.tasks import TaskStore
    cfg = load_config()
    pm = ProviderManager()
    if cfg.providers:
        pm.register_many(cfg.providers)
    store = TaskStore(os.path.join(_root(), "orchestrator", "taskboard.sqlite"))
    return MasterController(store, pm, cfg.workspace.root, cfg=cfg,
                            resources=ResourceManager.from_config(cfg),
                            max_tasks=2)


def cmd_master(args):
    mc = _master_controller()
    if args.action == "simulate":
        goal = (args.goal or "").strip()
        subs = None
        if getattr(args, "file", None):
            # analyse an explicit plan (offline: no model call needed)
            try:
                with open(args.file, encoding="utf-8") as f:
                    subs = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                print(f"cannot read plan file: {e}")
                return 1
            if not isinstance(subs, list):
                print("plan file must be a JSON list of task objects")
                return 1
            goal = goal or f"plan from {args.file}"
        if len(goal) < 3:
            print('usage: elysia master simulate "<goal>" [--file plan.json]')
            return 1
        sim = mc.simulate(goal, subs=subs,
                          plan_with_model=subs is None)
        if args.json:
            print(json.dumps(sim, indent=1, default=str))
            return 0 if sim.get("ok") else 1
        print(f"simulation of goal (nothing written): {goal[:120]}")
        if not sim.get("ok") and sim.get("error"):
            print(f"  {sim['error']}")
            return 1
        for n in sim["nodes"]:
            target = (f"{n['provider']} ({n['model']})" if n["provider"]
                      else "-- no provider --")
            print(f"  [{n['index']}] {n['agent_role']:<12} "
                  f"files={','.join(n['owned_files']) or '-'} -> {target}")
            print(f"       write={'yes' if n['can_write'] else 'NO'} | "
                  f"{n['routing_reason']}")
            for issue in n["issues"]:
                print(f"       ! {issue['kind']}: {issue['detail']}")
        for c in sim["conflicts"]:
            print(f"  ! file conflict: {c['file']} owned by tasks {c['tasks']}")
        for c in sim["circular_dependencies"]:
            print(f"  ! circular dependency: {c}")
        if sim.get("repairs", {}).get("changes"):
            print("  graph repairs the master would apply:")
            for c in sim["repairs"]["changes"]:
                print(f"    * {c}")
        if sim.get("suggested_repairs"):
            print("  repairs available (not applied to an explicit plan):")
            for c in sim["suggested_repairs"]:
                print(f"    - {c}")
        for i in sim.get("raw_issues") or []:
            print(f"  ! {i['severity']}: {i['kind']}: {i['detail']}")
        est = sim.get("estimates") or {}
        if est:
            print(f"  estimates (heuristic): ~{est.get('total_duration_s')}s, "
                  f"~{est.get('total_tokens_est')} tokens across "
                  f"{len(est.get('per_task') or [])} task(s)")
        print(f"would create {sim['would_create_tasks']} task(s) "
              f"(raw plan: {sim.get('raw_task_count')}); writes=0; "
              f"executor_started={sim['executor_started']}")
        return 0 if sim.get("ok") else 1
    if args.action == "route":
        caps = [c.strip() for c in (args.caps or "chat").split(",") if c.strip()]
        why = mc.explain_routing(caps)
        if args.json:
            print(json.dumps(why, indent=1, default=str))
            return 0
        print(f"requirements: {', '.join(why['requirements'])}")
        print(f"selected    : {why['selected']} ({why['model']})")
        print(f"why         : {why['reason']}")
        print(f"priority    : {' -> '.join(why['priority_order'])}")
        for row in why["trace"]:
            mark = "*" if row.get("selected") else " "
            print(f" {mark} {row['provider']:<16} {row['status']:<12} "
                  f"{row['requirement_pass']:<14} "
                  f"{row['reason'] or 'eligible'}")
        return 0
    if args.action == "efficiency":
        rep = mc.efficiency_report(
            task_id=int(args.goal) if (args.goal or "").isdigit() else None)
        if args.json:
            print(json.dumps(rep, indent=1, default=str))
            return 0
        print(f"{'task':<8} {'class':<12} {'prio':<12} {'AI':>4} {'checks':>6} "
              f"{'tokens':>8} {'ai_s':>7} {'retries':>7} {'fail':>4}")
        for row in rep["tasks"]:
            print(f"#{row['task_id']:<7} {row['resource_class'] or '-':<12} "
                  f"{row['priority_class'] or '-':<12} {row['ai_calls']:>4} "
                  f"{row['deterministic_checks']:>6} "
                  f"{row['tokens_in'] + row['tokens_out']:>8} "
                  f"{row['ai_seconds']:>7.1f} {row['retries']:>7} "
                  f"{row['failures']:>4}")
        print(f"\ntotals: AI calls={rep['totals']['ai_calls']} "
              f"deterministic checks={rep['totals']['deterministic_checks']} "
              f"tokens={rep['totals']['tokens_in'] + rep['totals']['tokens_out']} "
              f"ai_time={rep['totals']['ai_seconds']}s")
        print(rep["note"])
        return 0
    if args.action == "queue":
        q = mc.queue_report()
        if args.json:
            print(json.dumps(q, indent=1, default=str))
            return 0
        local = q["local_slot"]
        print(f"local model slot: {local['running']}/{local['slots']} running, "
              f"{local['queued']} queued")
        for t in q["running"]:
            print(f"  #{t['task_id']} RUNNING  {t['title'][:48]:<48} "
                  f"{t['status']} provider={t.get('provider') or '-'}")
        for t in q["waiting"]:
            print(f"  #{t['task_id']} WAITING  {t['title'][:48]:<48}")
            print(f"      reason: {t.get('reason')}")
        if not q["running"] and not q["waiting"]:
            print("  (board is quiet)")
        return 0
    if args.action == "agents":
        rows = mc.agents()
        if args.json:
            print(json.dumps(rows, indent=1))
            return 0
        print(f"{'role':<20} {'capabilities':<28} provider / model")
        for r in rows:
            target = (f"{r['provider']} ({r['model']})" if r["provider"]
                      else "-- no provider matches --")
            print(f"{r['role']:<20} {','.join(r['capabilities']):<28} {target}")
        return 0
    if args.action == "status":
        # interactive: probe providers so "healthy" is never assumed
        st = mc.status(probe=True)
        if args.json:
            print(json.dumps(st, indent=1, default=str))
            return 0
        print(f"master worker : {st['worker']} (max_tasks={st['max_tasks']}, "
              f"budget={st['budget']}, running={st['running']})")
        print(f"inflight      : {st['inflight'] or '-'}")
        print("counts        :", json.dumps(st["counts"]))
        print("executor      :", json.dumps(st["executor_stats"]))
        print("stages seen   :", ", ".join(st["stages_seen"]) or "-")
        print("providers     :")
        for p in st["providers"]:
            extra = ""
            if p.get("circuit") and p["circuit"] != "closed":
                extra = (f"  circuit={p['circuit']} "
                         f"({p.get('trips', 0)} trip(s), "
                         f"{p.get('cooldown_remaining_s', 0)}s left)")
            elif p.get("success_rate") is not None:
                extra = f"  success={p['success_rate']}"
            print(f"  {p['name']:<14} {p['status']:<12} "
                  f"{p['current_concurrency']}/{p['max_concurrency']} slots, "
                  f"{p['requests']} req, {p['failures']} fail{extra}")
        return 0
    goal = (args.goal or "").strip()
    if len(goal) < 3:
        print("usage: elysia master run \"<goal>\" [--no-wait] [--timeout S]")
        return 1
    run = mc.run(goal, timeout_s=args.timeout, start=not args.no_wait)
    if args.json:
        print(json.dumps(run, indent=1, default=str))
        return 0 if run.get("ok") else 1
    if not run.get("ok"):
        print(f"master: {run.get('status')} — {run.get('error')}")
        return 1
    rep = run.get("report") or {}
    print(f"goal #{run['goal_task']}: {goal[:120]}")
    print(f"sub-tasks: {len(run['subtasks'])} persisted on the board")
    for c in (run.get("repairs") or {}).get("changes", []):
        print(f"  graph repair: {c}")
    for t in rep.get("tasks") or []:
        files = ", ".join(t["files_written"]) or "-"
        print(f"  #{t['id']} [{t['status']}] {t['agent_role'] or 'agent'}: "
              f"{t['title'][:60]} -> {files}")
        if t.get("error"):
            print(f"      error: {t['error'][:160]}")
    print("logical agents :", " -> ".join(rep.get("stages") or []) or "-")
    print("files changed  :", ", ".join(rep.get("files_changed") or []) or "-")
    if rep.get("file_changes"):
        print("file events    :", ", ".join(rep["file_changes"][:8]))
    for p in rep.get("providers") or []:
        print(f"provider {p['name']}: {p['status']}, {p['requests']} req, "
              f"{p['failures']} fail")
    print(f"outcome: {rep.get('completed', 0)}/{len(rep.get('tasks') or [])} "
          f"completed")
    return 0 if rep.get("ok") else 1


# -- research -------------------------------------------------------------------
def cmd_research(args):
    cfg = load_config()
    from elysia.core.providers import ProviderManager
    from elysia.core.research import ResearchEngine, build_search
    from elysia.core.memory import Memory
    pm = ProviderManager()
    pm.register_many(cfg.providers)
    eng = ResearchEngine(pm, memory=Memory(os.path.join(_root(), "state", "memory"),
                                           max_entries=cfg.memory.max_entries),
                         search=build_search(cfg),
                         max_sources=cfg.research.max_sources,
                         output_dir=os.path.join(_root(), "workspace"))
    if getattr(args, "deep", False):
        res = eng.run_deep(args.query, format_spec=args.format or "",
                           breadth=args.breadth, depth=args.depth)
    else:
        res = eng.run(args.query, format_spec=args.format or "")
    print(res["report"][:6000])
    if res.get("report_path"):
        print("\n[report saved]", res["report_path"])
    print("\n[sources]", len(res["sources"]))
    return 0


# -- openreacher (deep research alias) ------------------------------------------
def cmd_orx(args):
    args.deep = True
    return cmd_research(args)


# -- db maintenance ----------------------------------------------------------------
def cmd_db(args):
    """TaskStore maintenance: health, backup, restore, vacuum (Phase 35)."""
    db = os.path.join(_root(), "orchestrator", "taskboard.sqlite")
    store = TaskStore(db)
    if args.action == "health":
        h = store.health_check()
        if args.json:
            print(json.dumps(h, indent=1, default=str))
            return 0 if h.get("ok") else 1
        print(f"board      : {h.get('path')}")
        print(f"exists     : {h.get('exists')}")
        print(f"integrity  : {h.get('integrity', h.get('error'))}")
        print(f"schema ver : {h.get('schema_version')}")
        print(f"journal    : {h.get('journal_mode')}")
        print(f"malformed  : {h.get('malformed_dependency_rows')} row(s)")
        print("counts     :", json.dumps(h.get("counts") or {}))
        return 0 if h.get("ok") else 1
    if args.action == "backup":
        out = store.backup(args.path or os.path.join(_root(), "state", "backups"))
        print(json.dumps(out, indent=1) if args.json else
              f"backup written: {out['path']} ({out['bytes']} bytes)")
        return 0 if out.get("ok") else 1
    if args.action == "restore":
        out = store.restore(args.path)
        if args.json:
            print(json.dumps(out, indent=1))
        else:
            print(out.get("error") or f"restored from {out['restored_from']}")
        return 0 if out.get("ok") else 1
    if args.action == "vacuum":
        out = store.vacuum()
        print(json.dumps(out, indent=1) if args.json else
              f"vacuum: {out['bytes_before']} -> {out['bytes_after']} bytes "
              f"(reclaimed {out['reclaimed']})")
        return 0 if out.get("ok") else 1
    return 1


def cmd_workflow(args):
    """Workflow engine: start / tick / state / approve / deny (Phase 2)."""
    from elysia.core.workflow import WorkflowEngine, WorkflowError
    db = os.path.join(_root(), "orchestrator", "taskboard.sqlite")
    store = TaskStore(db)
    eng = WorkflowEngine(store)
    if args.action == "start":
        if not args.file:
            print("usage: elysia workflow start --file nodes.json [--name NAME]")
            return 1
        try:
            with open(args.file, encoding="utf-8") as f:
                nodes = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"cannot read nodes: {e}")
            return 1
        try:
            run = eng.start(args.wf_name or args.name
                            or os.path.basename(args.file).rsplit(".", 1)[0],
                            nodes)
        except WorkflowError as e:
            print(f"invalid workflow: {e}")
            return 1
        eng.tick()
        print(json.dumps(run, indent=1) if args.json else
              f"workflow '{run['name']}' started: {run['total']} node(s) "
              f"ids={run['node_ids']}")
        return 0
    if args.action == "tick":
        out = eng.tick()
        if args.json:
            print(json.dumps(out, indent=1, default=str))
        else:
            rows = out["advanced"]
            print(f"{len(rows)} gate(s) advanced")
            for r in rows:
                print(f"  #{r['node']} [{r['kind']}] {r['state']}: {r['detail']}")
        return 0
    if args.action == "state":
        st = eng.run_state(args.name)
        if args.json:
            print(json.dumps(st, indent=1, default=str))
            return 0
        print(f"workflow '{st['name']}': {st['completed']}/{st['total']} done, "
              f"{st['failed']} failed, finished={st['finished']}")
        if st["awaiting_approval"]:
            print(f"awaiting approval: {st['awaiting_approval']}")
        for n in st["nodes"]:
            print(f"  #{n['id']:<4} [{n['type']:<9}] {n['status']:<12} "
                  f"{n['title'][:48]}")
        return 0 if st["ok"] else (1 if st["finished"] else 0)
    if args.action in ("approve", "deny"):
        ok = eng.resolve_approval(args.node, allow=args.action == "approve",
                                  by="operator", note=args.note or "")
        eng.tick()
        print(f"{args.action}d node {args.node}" if ok else
              f"node {args.node} is not an approval gate")
        return 0 if ok else 1
    return 1


# -- templates ------------------------------------------------------------------
def cmd_template(args):
    from elysia.core.templates import TEMPLATES, list_templates
    if args.name not in TEMPLATES:
        print("known templates:")
        for t in list_templates():
            print(f"  {t['name']:<14} {t['description']}")
        return 1
    print(json.dumps(TEMPLATES[args.name], indent=1))
    return 0


# -- git -------------------------------------------------------------------------
def cmd_checkpoint(args):
    from elysia.core.git import safe_checkpoint
    ok, msg = safe_checkpoint(_root(), args.message,
                              # never snapshot runtime state
                              never_commit=[".env", "*.key", "*.pem", "*.p12",
                                            "*.sqlite", "*.db", "*.log",
                                            "*.gguf", "*.onnx", "*.jar",
                                            "pool.lock", "pids", "state"])
    print(msg if ok else f"checkpoint failed: {msg}")
    return 0 if ok else 1


def cmd_checkpoints(args):
    from elysia.core.git import checkpoint_list
    for c in checkpoint_list(_root(), limit=args.n or 10):
        print(f"{c['sha']} {c['message'][:80]}")
    return 0


def cmd_rollback(args):
    from elysia.core.git import rollback_checkpoint
    ok, msg = rollback_checkpoint(_root(), args.sha, hard=args.hard)
    print(msg)
    return 0 if ok else 1


def cmd_since(_args):
    from elysia.core.git import since_last_checkpoint
    lines = since_last_checkpoint(_root())
    print("\n".join(lines) if lines else "(no changes since last commit)")
    return 0


# -- skills -----------------------------------------------------------------------
def cmd_skills(args):
    from elysia.core.skills import discover_skills, curated_allow_list, load_skill
    skill_root = args.path or os.path.join(_root(), "elysia", "skills")
    if args.command == "list":
        for s in discover_skills(skill_root):
            flag = "" if s.risk == "safe" else f"  <risk={s.risk}>"
            print(f"{s.name:32} {s.description[:60]}{flag}")
        return 0
    if args.command == "import":
        from scripts.import_skills import import_selected
        import_selected(args.path)
        return 0
    if args.command == "allow":
        print(", ".join(curated_allow_list()))
        return 0
    return 1


# -- memory / plugins ---------------------------------------------------------------
MEMORY_ACTIONS = {"search", "recall", "timeline", "stats", "compact",
                  "backup", "forget", "invalidate", "correct"}


def cmd_memory(args):
    """Layered memory: keyword search plus the maintenance operations.

    ``elysia memory <query>`` and ``elysia memory search <query>`` both search
    (the historical form keeps working); the other verbs are explicit.
    """
    from elysia.core.memory import Memory

    raw = getattr(args, "command", None)
    action = raw if raw in MEMORY_ACTIONS else "search"
    query = getattr(args, "query", None)
    if raw and raw not in MEMORY_ACTIONS:
        query = raw
    m = Memory(os.path.join(_root(), "state", "memory"))
    ns = getattr(args, "ns", None)
    as_json = bool(getattr(args, "json", False))

    if action in ("search", "recall"):
        if not query:
            print("usage: elysia memory <query> | elysia memory timeline [--ns NS]")
            return 1
        hits = (m.recall(query, limit=10) if action == "recall"
                else m.search(query, limit=10))
        if as_json:
            print(json.dumps(hits, indent=2, default=str))
            return 0
        if not hits:
            print("no memories matched")
            return 0
        for h in hits:
            print(f"[{h['namespace']}] {h['key']}  (score {h['score']}) "
                  f"conf={h.get('confidence')} src={h.get('provenance')}")
            print(f"    why: {h.get('why')}")
            print(f"    {json.dumps(h['value'], default=str)[:200]}")
        return 0
    if action == "timeline":
        rows = m.timeline(ns=ns, limit=30)
        if as_json:
            print(json.dumps(rows, indent=2, default=str))
            return 0
        for r in rows:
            flag = "INVALID " if r.get("invalidated") else ""
            print(f"{flag}[{r['namespace']}] {r['key']} kind={r.get('kind')} "
                  f"imp={r.get('importance')} src={r.get('provenance')}")
        return 0
    if action == "stats":
        print(json.dumps(m.stats(), indent=2))
        return 0
    if action == "compact":
        print(json.dumps(m.compact(), indent=2, default=str))
        return 0
    if action == "backup":
        path = getattr(args, "path", None) or os.path.join(
            _root(), "state", "memory-backup.json")
        out = m.backup(path)
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
    if action in ("forget", "invalidate", "correct"):
        key = getattr(args, "key", None)
        if not key or not ns:
            print(f"usage: elysia memory {action} --ns NS --key KEY "
                  f"[--value TEXT] [--reason WHY]")
            return 1
        if action == "forget":
            ok = m.forget(ns, key)
        elif action == "invalidate":
            ok = m.invalidate(ns, key, getattr(args, "reason", "") or "")
        else:
            value = getattr(args, "value", None)
            if value is None:
                print("usage: elysia memory correct --ns NS --key KEY --value TEXT")
                return 1
            ok = m.correct(ns, key, value,
                           getattr(args, "reason", "") or "")
        print(f"{action} {ns}/{key}: {'ok' if ok else 'not found'}")
        return 0 if ok else 1
    return 1


def cmd_healing(args):
    """Failure classification + recovery policy (diagnostics, no model call)."""
    from elysia.core.healing import Healer, classify, describe_policies

    action = args.action
    if action == "policies":
        rows = describe_policies()
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        print(f"{'kind':26} {'retryable':9} {'action':11} {'base':>6}  recovery")
        for r in rows:
            print(f"{r['kind']:26} {str(r['retryable']):9} {r['action']:11} "
                  f"{r['base_backoff_s']:6}  {r['recovery'] or '-'}")
        return 0
    if action == "report":
        print(json.dumps(Healer().report(), indent=2))
        return 0
    if action == "classify":
        text = args.message or ""
        if not text:
            print('usage: elysia healing classify "<error text>"')
            return 1
        out = classify(text, attempt=int(args.attempt or 1))
        if args.json:
            print(json.dumps(out, indent=2, default=str))
            return 0
        print(f"kind:       {out['kind']}")
        print(f"action:     {out['action']}")
        print(f"retryable:  {out['retryable']} (attempt {out['attempt']}/"
              f"{out['max_retries']})")
        print(f"backoff:    {out['backoff_s']}s")
        print(f"recovery:   {out['recovery'] or 'none'}")
        print(f"evidence:   {', '.join(out['evidence']) or 'none'}")
        if out.get("hint"):
            print(f"hint:       {out['hint']}")
        return 0
    return 1


def cmd_plugins(args):
    cfg = load_config()
    from elysia.core.plugins import PluginManager
    from elysia.core.tools import ToolRegistry
    pm = PluginManager(cfg.plugins.dir, allow_list=cfg.plugins.enabled)
    if args.command == "list":
        for p in pm.discover():
            print(f"{p.name:24} enabled={str(p.enabled):5} loaded={str(p.loaded):5}"
                  f"  {p.description[:50]}")
            if p.error:
                print(f"   error: {p.error[:100]}")
        return 0
    if args.command == "load":
        tools = ToolRegistry()
        p = pm.load(args.name, tools)
        print(f"loaded {p.name}: errors={p.error or 'none'}")
        return 0 if p.loaded else 1
    return 1


# -- audit / test / logs ----------------------------------------------------------------
def cmd_audit(args):
    """Scan executable/source files (not prose docs) for hardcoded paths to a
    deleted absolute tree (used only to keep the checker literal-free)."""
    HARD_CODE = "/data" + "/elysia"
    HARD_CODE_U = "/data" + "/Elysia"
    SKIP_DIRS = {".git", "node_modules", "__pycache__", "legacy", ".venv",
                 "venv", "dist", "build", ".agent_tmp"}
    PROSE_EXT = {".md", ".rst", ".adoc", ".readme", ".txt", "AGENTS"}
    CODE_EXT = {".py", ".sh", ".go", ".json", ".toml", ".cfg", ".yml", ".yaml",
                ".ts", ".tsx", ".js", ".jsx", ".rs", ".java", ".kt", ".rb",
                ".sql", ".ini", ".env.example"}
    COMMENT_LINE = "#"
    bad = []
    for dp, dns, fns in os.walk(_root()):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for f in fns:
            low = f.lower()
            if low.endswith(tuple(PROSE_EXT)):
                continue
            if not low.endswith(tuple(CODE_EXT)):
                continue
            p = os.path.join(dp, f)
            try:
                lines = open(p, "rb").read().splitlines()
            except OSError:
                continue
            if low.endswith(".sh"):
                lines = [l for l in lines if not l.lstrip().startswith(b"#")]
            blob = b"\n".join(lines)
            if HARD_CODE.encode() in blob or HARD_CODE_U.encode() in blob:
                bad.append(os.path.relpath(p, _root()))
    if bad:
        print("hardcoded absolute-legacy-path refs remain in source files:")
        for b in bad:
            print("  ", b)
        return 1
    print(f"audit passed: no hardcoded legacy absolute paths in source files "
          f"under {_root()} (legacy excluded)")
    return 0


def cmd_test(args):
    tests_dir = os.path.join(_root(), "tests")
    if args.mode == "unit":
        r = subprocess.run([sys.executable, "-m", "unittest", "discover",
                            "-s", tests_dir], cwd=_root())
        return r.returncode
    if args.mode == "chaos":
        r = subprocess.run([sys.executable, "tests/test_chaos.py"], cwd=_root())
        return r.returncode
    if args.mode == "e2e":
        r = subprocess.run([sys.executable, "tests/test_e2e.py"], cwd=_root())
        return r.returncode
    return 1


def cmd_logs(args):
    cfg = load_config()
    log_dir = cfg.logging.dir
    events_file = os.path.join(log_dir, cfg.logging.events_file)
    if not os.path.exists(events_file):
        print("no events journal yet:", events_file)
        return 0
    lines = open(events_file).read().splitlines()
    for line in lines[- (args.n or 50):]:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        print(f"{ev.get('ts'):20.2f} {ev.get('event_type'):20} "
              f"{ev.get('status','')} {ev.get('detail','')[:120]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="elysia", description="Elysia CLI")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("start").add_argument("--port", type=int, default=None)
    sub.add_parser("stop")
    sub.add_parser("status")
    sub.add_parser("doctor")
    sub.add_parser("cost")

    rsp = sub.add_parser("resources", help="live CPU/RAM/slot picture and why "
                                           "work is queued")
    rsp.add_argument("--watch", action="store_true",
                     help="sample continuously (Ctrl-C to stop)")
    rsp.add_argument("--interval", type=float, default=2.0)
    rsp.add_argument("--json", action="store_true")

    # `queue` and `models` are views of the ONE resources command, so the
    # report and the runtime can never disagree about why work is waiting.
    qp = sub.add_parser("queue", help="every task waiting and WHY it is waiting")
    qp.add_argument("--json", action="store_true")
    qp.set_defaults(cmd="resources", view="queue")

    mp = sub.add_parser("models", help="local model slots, warm state and "
                                        "unload policy")
    mp.add_argument("--json", action="store_true")
    mp.set_defaults(cmd="resources", view="models")

    sub.add_parser("workers")

    tp = sub.add_parser("tasks")
    tp.add_argument("filter", nargs="?", default=None)
    tp.set_defaults(action="list")

    task = sub.add_parser("task")
    task.add_argument("action", choices=["show", "add", "cancel", "retry",
                                         "pause", "resume"])
    task.add_argument("task_id", nargs="?")
    task.add_argument("--title")
    task.add_argument("--files", default="")
    task.add_argument("--priority", type=int, default=5)
    task.add_argument("--deps", default="")
    task.add_argument("--template")
    task.add_argument("--dedup", action="store_true")

    pr = sub.add_parser("providers")
    pr.add_argument("--catalog", action="store_true",
                    help="show the full provider preset catalog and "
                         "what each needs to activate")

    lg = sub.add_parser("login", help="set up a provider from the desktop "
                                      "browser")
    lg.add_argument("provider", nargs="?")
    lg.add_argument("--status", action="store_true",
                    help="show stored keys (no secrets) + active providers")
    lg.add_argument("--load", action="store_true",
                    help="load stored keys into this process environment")
    lg.add_argument("--logout", action="store_true",
                    help="remove the provider's stored key")
    lg.add_argument("--paste", default=None, metavar="KEY",
                    help="store the key locally (config/providers.env, 0600)")
    lg.add_argument("--no-browser", action="store_true")

    hf = sub.add_parser("hf", help="huggingface models/datasets/inference")
    hf.add_argument("action", choices=["models", "datasets", "model",
                                        "recommend"])
    hf.add_argument("repo", nargs="?", default=None)

    kn = sub.add_parser("knowledge", help="vendored security-tooling docs "
                                          "(defensive-first)")
    kn.add_argument("action", choices=["list", "search", "show"])
    kn.add_argument("query", nargs="?", default=None)

    hp = sub.add_parser("health", help="independent health dimensions "
                                       "(providers, scheduler, store, workspace, "
                                       "resources, security, tests, git, memory)")
    hp.add_argument("--json", action="store_true")

    tl = sub.add_parser("tools", help="machine tool catalog: what is installed "
                                      "and what it can do")
    tl.add_argument("--group", default=None,
                    help="filter by group (security, osint, dev, network, ...)")
    tl.add_argument("--check", default=None, metavar="TOOL",
                    help="probe one tool and show its knowledge doc")
    tl.add_argument("--missing", action="store_true",
                    help="list catalog tools NOT installed (gap report)")
    tl.add_argument("--registry", action="store_true",
                    help="show the runtime tool registry (permissions + risk), "
                         "not the machine catalog")
    tl.add_argument("--role", default=None,
                    help="with --registry: what this role may and may not invoke")
    tl.add_argument("--json", action="store_true")

    br = sub.add_parser("brief", help="Jarvis-style status briefing "
                                      "(capabilities, board, providers)")
    br.add_argument("topic", nargs="?", default=None,
                    help="optional topic for a focused knowledge digest")

    jv = sub.add_parser("jarvis", help="one natural-language front door: "
                                       "routes to briefing/knowledge/research/goal")
    jv.add_argument("request", nargs="?", default=None)
    jv.add_argument("--deep", action="store_true",
                    help="use the deep-research engine for research routes")

    pt = sub.add_parser("prompt", help="system-prompt styles")
    pt.add_argument("style_name", nargs="?", default=None)

    ag = sub.add_parser("agents")
    ag.add_argument("role", nargs="?", default=None)
    ag.add_argument("--prompt", default=None)

    mc = sub.add_parser("master", help="master control plane: drive a goal "
                                       "through the agent pipeline")
    mc.add_argument("action", choices=["run", "status", "agents", "simulate",
                                       "route", "efficiency", "queue"])
    mc.add_argument("goal", nargs="?", default=None)
    mc.add_argument("--file", default=None,
                    help="simulate: analyse an explicit plan (JSON task list) "
                         "without calling a model")
    mc.add_argument("--caps", default=None,
                    help="route: comma-separated capabilities, e.g. chat,coding")
    mc.add_argument("--timeout", type=float, default=180.0,
                    help="seconds to drive the workflow before reporting")
    mc.add_argument("--no-wait", action="store_true",
                    help="persist + start, return immediately")
    mc.add_argument("--json", action="store_true",
                    help="emit the full machine-readable run record")

    rs = sub.add_parser("research")
    rs.add_argument("query")
    rs.add_argument("--format", default="")
    rs.add_argument("--deep", action="store_true",
                    help="breadth/depth research (openreacher-style)")
    rs.add_argument("--breadth", type=int, default=2)
    rs.add_argument("--depth", type=int, default=1)

    orx = sub.add_parser(
        "orx", help="openreacher deep research (alias for research --deep)")
    orx.add_argument("query")
    orx.add_argument("--format", default="")
    orx.add_argument("--breadth", type=int, default=2)
    orx.add_argument("--depth", type=int, default=1)

    tmpl = sub.add_parser("template")
    tmpl.add_argument("name", nargs="?")

    cp = sub.add_parser("checkpoint")
    cp.add_argument("message")
    sub.add_parser("checkpoints").add_argument("n", nargs="?",
                                               type=int, default=None)
    rb = sub.add_parser("rollback")
    rb.add_argument("sha")
    rb.add_argument("--hard", action="store_true")
    sub.add_parser("since-checkpoint")

    sk = sub.add_parser("skills")
    sk.add_argument("command", choices=["list", "import", "allow"])
    sk.add_argument("path", nargs="?")

    mem = sub.add_parser("memory", help="layered memory: search, recall, "
                                         "timeline, stats, compact, backup, "
                                         "forget, invalidate, correct")
    mem.add_argument("command", nargs="?", default="search",
                     help="search (default) | recall | timeline | stats | "
                          "compact | backup | forget | invalidate | correct")
    mem.add_argument("query", nargs="?")
    mem.add_argument("--ns", default=None, help="namespace")
    mem.add_argument("--key", default=None)
    mem.add_argument("--value", default=None)
    mem.add_argument("--reason", default="")
    mem.add_argument("--path", default=None, help="backup destination")
    mem.add_argument("--json", action="store_true")

    heal = sub.add_parser("healing", help="failure classification and recovery "
                                           "policy (diagnostics)")
    heal.add_argument("action",
                      choices=["policies", "report", "classify"])
    heal.add_argument("message", nargs="?", default=None,
                      help="classify: the error text to classify")
    heal.add_argument("--attempt", type=int, default=1)
    heal.add_argument("--json", action="store_true")

    dbp = sub.add_parser("db", help="task board maintenance: health, backup, "
                                    "restore, vacuum")
    dbp.add_argument("action", choices=["health", "backup", "restore", "vacuum"])
    dbp.add_argument("path", nargs="?", default=None,
                     help="backup: destination dir; restore: source file")
    dbp.add_argument("--json", action="store_true")

    wf = sub.add_parser("workflow", help="workflow engine: start (from a JSON "
                                         "node list), tick, state, approve, deny")
    wf.add_argument("action", choices=["start", "tick", "state", "approve", "deny"])
    wf.add_argument("name", nargs="?", default=None,
                    help="state: workflow name; start: optional name")
    wf.add_argument("--name", dest="wf_name", default=None,
                    help="start: optional workflow name")
    wf.add_argument("--file", default=None, help="workflow nodes JSON")
    wf.add_argument("--node", type=int, default=None,
                    help="approval node id (approve/deny)")
    wf.add_argument("--note", default="")
    wf.add_argument("--json", action="store_true")

    pl = sub.add_parser("plugins")
    pl.add_argument("command", choices=["list", "load"])
    pl.add_argument("name", nargs="?")

    sub.add_parser("audit")
    te = sub.add_parser("test")
    te.add_argument("mode", choices=["unit", "chaos", "e2e"], default="unit",
                    nargs="?")
    lg = sub.add_parser("logs")
    lg.add_argument("n", nargs="?", type=int, default=None)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cmd = args.cmd
    if not cmd:
        print(build_parser().format_help())
        return 0
    handlers = {
        "start": cmd_start, "stop": cmd_stop, "status": cmd_status,
        "doctor": cmd_doctor, "tasks": cmd_tasks, "task": cmd_task,
        "workers": cmd_workers, "providers": cmd_providers,
        "login": cmd_login, "hf": cmd_hf, "knowledge": cmd_knowledge,
        "prompt": cmd_prompt, "tools": cmd_tools, "brief": cmd_brief,
        "health": cmd_health,
        "jarvis": cmd_jarvis,
        "cost": cmd_cost, "resources": cmd_resources, "agents": cmd_agents,
        "master": cmd_master,
        "research": cmd_research, "orx": cmd_orx, "template": cmd_template,
        "checkpoint": cmd_checkpoint, "checkpoints": cmd_checkpoints,
        "rollback": cmd_rollback, "since-checkpoint": cmd_since,
        "skills": cmd_skills, "memory": cmd_memory, "plugins": cmd_plugins,
        "audit": cmd_audit, "test": cmd_test, "logs": cmd_logs,
        "db": cmd_db, "workflow": cmd_workflow, "healing": cmd_healing,
    }
    return handlers[cmd](args)


if __name__ == "__main__":
    sys.exit(main())