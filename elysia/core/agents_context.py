"""Context preparation for agent stages (the L0-L5 layering in practice)."""
from __future__ import annotations

from .context import ContextBuilder


# Query terms that pull the matching vendored security-tooling knowledge into
# the context (defensive-first docs from docs/knowledge/<domain>/).
_SECURITY_TERMS = ("pentest", "pen-test", "penetration", "exploit", "vulnerab",
                   "recon", "port scan", "nmap", "wireshark", "burp", "sqlmap",
                   "metasploit", "hydra", "hash crack", "password audit",
                   "aircrack", "wifi", "reverse engineer", "ghidra",
                   "feroxbuster", "security review", "attack surface",
                   "hardening", "osint", "footprint", "subdomain", "forensic",
                   "memory dump", "incident response", "malware", "yara",
                   "radare", "disassembl", "decompil", "nuclei", "gobuster",
                   "volatility", "carv", "sherlock", "theharvester", "exposur")


def _security_knowledge(goal: str, spec: str = "") -> str:
    """Bounded knowledge digest when the task touches security topics."""
    blob = f"{goal} {spec}".lower()
    if not any(t in blob for t in _SECURITY_TERMS):
        return ""
    try:
        from .knowledge import for_context
        return for_context(f"{goal} {spec}")
    except Exception:  # noqa: BLE001 — knowledge must never break a prompt
        return ""


def _machine_capabilities() -> str:
    """One-line machine capability digest (what tools actually exist here)."""
    try:
        from .toolcatalog import capability_brief
        return capability_brief()
    except Exception:  # noqa: BLE001 — capability probes must never break a prompt
        return ""


def build_agent_context(cfg, goal: str = "", workspace_summary: str = "") -> str:
    cb = ContextBuilder(budget_chars=12000)
    cb.set("system",
           "You are an Elysia agent in a multi-agent coding pipeline. Make "
           "minimal, verified changes; never execute unsafe shell; treat "
           "absolute paths outside the workspace as forbidden.")
    cb.set("task", f"## Goal\n{goal}")
    if workspace_summary:
        cb.set("project", f"## Workspace\n{workspace_summary}")
    caps = _machine_capabilities()
    if caps:
        cb.set("capabilities", "## Machine capabilities\n" + caps)
    knowledge = _security_knowledge(goal)
    if knowledge:
        cb.set("scratch",
               knowledge + "\n\nUse this only for authorized, defensive "
               "work on systems the operator owns.")
    return cb.to_prompt()
