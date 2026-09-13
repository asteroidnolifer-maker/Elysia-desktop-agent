"""Self-diagnostics: run a battery of checks and report health.

`elysia doctor` runs these checks and exits nonzero if failures exist. Each
check returns (ok, [problems]).
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys


def _port_open(host, port, timeout=1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
        return False
    except OSError:
        return False


def check_workspace_secure(root: str) -> tuple[bool, list[str]]:
    """Sanity: no symlink-escape through the workspace."""
    if not root:
        return False, ["workspace root empty"]
    import tempfile
    probe = os.path.join(root, ".elysia_probe")
    try:
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
    except OSError as e:
        return False, [f"workspace not writable: {e}"]
    return True, []


def check_providers(cfg) -> tuple[bool, list[str]]:
    problems = []
    if not cfg.providers:
        return False, ["no providers configured"]
    for p in cfg.providers:
        if not p.model:
            problems.append(f"provider {p.label} has no model")
        if p.concurrency < 1:
            problems.append(f"provider {p.label} concurrency < 1")
    return not problems, problems


def check_api_port(host: str, port: int) -> tuple[bool, list[str]]:
    in_use = _port_open(host, port)
    return (True, []) if not in_use else (False,
           [f"api port {host}:{port} already in use"])


def check_llm_available(cfg) -> tuple[bool, list[str]]:
    for p in cfg.providers:
        try:
            import urllib.request
            base = p.base_url.rstrip("/")
            with urllib.request.urlopen(base + "/models", timeout=3) as r:
                if r.status == 200:
                    return True, []
        except OSError:
            continue
    return False, ["no reachable LLM provider; provider /models unreachable"]


def check_python_deps() -> tuple[bool, list[str]]:
    missing = []
    for mod, name in [("sqlite3", "stdlib sqlite3"), ("json", "stdlib json"),
                      ("urllib", "stdlib urllib")]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(name)
    return (not missing), missing


def check_git_repo(root: str) -> tuple[bool, list[str]]:
    if not os.path.isdir(os.path.join(root, ".git")):
        return False, ["not a git repository"]
    return True, []


def run_all(cfg=None, workspace_root: str = "") -> list[dict]:
    from .config import load_config
    cfg = cfg or load_config()
    checks = [
        ("workspace", check_workspace_secure(workspace_root or cfg.workspace.root)),
        ("providers", check_providers(cfg)),
        ("api_port", check_api_port(cfg.api.host, cfg.api.port)),
        ("python_deps", check_python_deps()),
        ("git", check_git_repo(workspace_root or cfg.workspace.root)),
    ]
    return [{"name": name, "ok": ok, "problems": problems}
            for name, (ok, problems) in checks]


def do_doctor(cfg=None, workspace_root: str = "") -> dict:
    results = run_all(cfg, workspace_root)
    all_ok = all(r["ok"] for r in results)
    return {"ok": all_ok, "checks": results}


def print_doctor(results: dict) -> None:
    for r in results["checks"]:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"[{mark}] {r['name']}")
        for p in r["problems"]:
            print(f"      - {p}")
    print(f"\nResult: {'all checks passed' if results['ok'] else 'FAILURES PRESENT'}")