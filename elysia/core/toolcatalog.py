"""Tool-catalog & machine-capability detection for Elysia (Jarvis layer).

Answers "what can this machine actually DO right now?" by probing the PATH
for known tools (security, dev, network, containers, forensics...) and
cross-referencing the vendored knowledge base (``elysia.core.knowledge``).

Design:
  - stdlib-only, offline, never raises; each probe is a shutil.which()
  - every entry is DEFENSIVE-FIRST and mirrors the vendored docs: Elysia
    recommends, documents and audits — it never auto-installs anything
    (operator consent is required; see docs/security/SECURITY_TOOLING.md)
  - capability groups let agents answer "which tools do I have for X?"

CLI: ``elysia tools`` (list), ``elysia tools --group security``,
``elysia tools --check <name>``, ``elysia tools --missing`` (gap report).
"""
from __future__ import annotations

import shutil

# name -> (group, purpose, knowledge-lookup hint, optional extra probe names)
TOOL_CATALOG: dict[str, dict] = {
    # --- security / recon ---------------------------------------------------
    "nmap":        {"group": "security", "purpose": "network & port discovery"},
    "wireshark":   {"group": "security", "purpose": "packet capture & analysis",
                    "also": ["tshark"]},
    "burpsuite":   {"group": "security", "purpose": "web proxy & app testing",
                    "also": ["burpsuite-pro"]},
    "sqlmap":      {"group": "security", "purpose": "SQL-injection testing"},
    "metasploit":  {"group": "security", "purpose": "exploitation framework",
                    "also": ["msfconsole"]},
    "ghidra":      {"group": "security", "purpose": "binary reverse engineering",
                    "also": ["analyzeHeadless"]},
    "john":        {"group": "security", "purpose": "password auditing",
                    "also": ["unshadow"]},
    "hydra":       {"group": "security", "purpose": "login auditing"},
    "aircrack-ng": {"group": "security", "purpose": "wifi auditing",
                    "also": ["airodump-ng"]},
    "feroxbuster": {"group": "security", "purpose": "content discovery"},
    "nuclei":      {"group": "security", "purpose": "template vuln scanning"},
    "gobuster":    {"group": "security", "purpose": "dir/vhost discovery"},
    "sherlock":    {"group": "osint", "purpose": "username footprint"},
    "theharvester": {"group": "osint", "purpose": "public surface inventory",
                     "also": ["theHarvester"]},
    "volatility3": {"group": "forensics", "purpose": "memory forensics",
                    "also": ["vol"]},
    "testdisk":    {"group": "forensics", "purpose": "recovery & carving",
                    "also": ["photorec"]},
    "radare2":     {"group": "reverse-engineering", "purpose": "binary analysis",
                    "also": ["r2"]},
    "yara":        {"group": "reverse-engineering", "purpose": "pattern rules"},
    # --- development ---------------------------------------------------------
    "git":         {"group": "dev", "purpose": "version control"},
    "python3":     {"group": "dev", "purpose": "python runtime"},
    "go":          {"group": "dev", "purpose": "go toolchain", "also": ["gofmt"]},
    "node":        {"group": "dev", "purpose": "js runtime", "also": ["npm"]},
    "tsc":         {"group": "dev", "purpose": "typescript compiler"},
    "rustc":       {"group": "dev", "purpose": "rust compiler"},
    "cargo":       {"group": "dev", "purpose": "rust build system"},
    "docker":      {"group": "dev", "purpose": "containers"},
    "shellcheck":  {"group": "dev", "purpose": "shell script linting"},
    # --- system / network ops --------------------------------------------------
    "curl":        {"group": "network", "purpose": "http client"},
    "ssh":         {"group": "network", "purpose": "remote shell"},
    "dig":         {"group": "network", "purpose": "dns lookup"},
    "nc":          {"group": "network", "purpose": "tcp/udp swiss army knife"},
    "tcpdump":     {"group": "network", "purpose": "packet dump"},
    "systemctl":   {"group": "system", "purpose": "service control"},
    "llama-server": {"group": "ai", "purpose": "local model server"},
    "ollama":      {"group": "ai", "purpose": "local model runtime",
                    "also": ["ollama serve"]},
}

GROUPS = ["security", "osint", "web-security", "forensics",
          "reverse-engineering", "dev", "network", "system", "ai"]


def detect(name: str) -> dict:
    """Probe one catalog tool. Returns a status dict (never raises)."""
    entry = TOOL_CATALOG.get(name)
    if entry is None:
        return {"name": name, "installed": False, "error": "not in catalog"}
    candidates = [name] + list(entry.get("also", []))
    path = None
    found = None
    for c in candidates:
        path = shutil.which(c)
        if path:
            found = c
            break
    return {"name": name, "group": entry["group"],
            "purpose": entry["purpose"], "installed": bool(path),
            "binary": found, "path": path}


def scan() -> list[dict]:
    """Probe the whole catalog (sorted by group, then name)."""
    rows = [detect(n) for n in TOOL_CATALOG]
    rows.sort(key=lambda r: (r.get("group", ""), r["name"]))
    return rows


def by_group() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in scan():
        out.setdefault(r.get("group", "?"), []).append(r)
    return out


def summary() -> dict:
    rows = scan()
    installed = [r for r in rows if r["installed"]]
    groups = sorted({r["group"] for r in installed})
    return {"total": len(rows), "installed": len(installed),
            "missing": len(rows) - len(installed), "groups": groups,
            "rows": rows}


def capability_brief() -> str:
    """A short 'this machine can currently do X' digest for the agent/HUD."""
    s = summary()
    if not s["installed"]:
        return "No catalog tools detected on this machine."
    lines = [f"Machine capabilities: {s['installed']}/{s['total']} catalog "
             f"tools present ({', '.join(s['groups'])})."]
    for r in s["rows"]:
        if r["installed"]:
            lines.append(f"  + {r['name']}: {r['purpose']}")
    return "\n".join(lines)


def knowledge_for(name: str) -> str:
    """The vendored knowledge doc for a tool, if one exists."""
    from .knowledge import load_all
    for e in load_all():
        if e.name.lower() == name.lower() or name.lower() in e.aliases:
            return e.summary()
    return ""
