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
    elysia memory search <query>
    elysia plugins list|load <name>
    elysia audit
    elysia test [--unit|--chaos|--e2e]
    elysia logs [n]
    elysia master run "<goal>" [--no-wait] [--timeout S] [--json]
    elysia master status | agents
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
def cmd_workers(_args):
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
        print(f"{cp['name']:20} status={cp['status']:12} "
              f"concurrency={cp['current_concurrency']}/{cp['max_concurrency']} "
              f"requests={cp['requests']} failures={cp['failures']} "
              f"avg_lat={cp['avg_latency_s']}s")
        if cp["last_error"]:
            print(f"   last_error: {cp['last_error'][:100]}")
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
def cmd_tools(args):
    from elysia.core import toolcatalog as tc
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


def cmd_resources(_args):
    from elysia.core.resources import ResourceManager
    rm = ResourceManager()
    print(json.dumps(rm.report(), indent=1))
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
                            resources=ResourceManager(), max_tasks=2)


def cmd_master(args):
    mc = _master_controller()
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
            print(f"  {p['name']:<14} {p['status']:<12} "
                  f"{p['current_concurrency']}/{p['max_concurrency']} slots, "
                  f"{p['requests']} req, {p['failures']} fail")
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
    for t in rep.get("tasks") or []:
        files = ", ".join(t["files_written"]) or "-"
        print(f"  #{t['id']} [{t['status']}] {t['agent_role'] or 'agent'}: "
              f"{t['title'][:60]} -> {files}")
        if t.get("error"):
            print(f"      error: {t['error'][:160]}")
    print("logical agents :", " -> ".join(rep.get("stages") or []) or "-")
    print("files changed  :", ", ".join(rep.get("files_changed") or []) or "-")
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
def cmd_memory(args):
    from elysia.core.memory import Memory
    m = Memory(os.path.join(_root(), "state", "memory"))
    hits = m.search(args.query, limit=10)
    for h in hits:
        print(f"[{h['namespace']}] {h['key']}  (score {h['score']})")
        print(f"    {json.dumps(h['value'], default=str)[:200]}")
    return 0


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
    sub.add_parser("resources")
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

    tl = sub.add_parser("tools", help="machine tool catalog: what is installed "
                                      "and what it can do")
    tl.add_argument("--group", default=None,
                    help="filter by group (security, osint, dev, network, ...)")
    tl.add_argument("--check", default=None, metavar="TOOL",
                    help="probe one tool and show its knowledge doc")
    tl.add_argument("--missing", action="store_true",
                    help="list catalog tools NOT installed (gap report)")

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
    mc.add_argument("action", choices=["run", "status", "agents"])
    mc.add_argument("goal", nargs="?", default=None)
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

    mem = sub.add_parser("memory")
    mem.add_argument("search", nargs="?")
    mem.add_argument("query", nargs="?")

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
        "jarvis": cmd_jarvis,
        "cost": cmd_cost, "resources": cmd_resources, "agents": cmd_agents,
        "master": cmd_master,
        "research": cmd_research, "orx": cmd_orx, "template": cmd_template,
        "checkpoint": cmd_checkpoint, "checkpoints": cmd_checkpoints,
        "rollback": cmd_rollback, "since-checkpoint": cmd_since,
        "skills": cmd_skills, "memory": cmd_memory, "plugins": cmd_plugins,
        "audit": cmd_audit, "test": cmd_test, "logs": cmd_logs,
    }
    return handlers[cmd](args)


if __name__ == "__main__":
    sys.exit(main())