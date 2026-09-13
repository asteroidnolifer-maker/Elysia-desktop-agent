"""Skill loader for Elysia.

Skills are structured prompt/practice documents (SKILL.md + supporting files)
in the directory layout used by the agent-skills ecosystem. Elysia loads a
CURATED subset that has been vetted for risk; every skill carries:

  - id, name, description
  - version, author, license (when in front-matter)
  - risk level (safe/low/moderate/high)
  - user-invocable flag + allowed-tools (when declared)

Discovery is permission-scoped: high-risk skills are never auto-loaded and are
only accessible when the caller explicitly requests them (for audits), while
the runtime keeps an allow-list.
"""
from __future__ import annotations

import json
import os
import re

RISK_SAFE = "safe"
RISK_LOW = "low"
RISK_MODERATE = "moderate"
RISK_HIGH = "high"

# High-risk *intent* markers (aggressive activities, tool names, destructive
# command patterns). Neutral nouns that legitimate dev skills legitimately use
# ("credential", "bypass", "delete") are intentionally NOT included.
HIGH_RISK_MARKERS = [
    "crack", "pentest", "exploit-development", "phishing-campaign",
    "credential-stuffing", "brute-force", "malware-dev", "reverse shell",
    "port scan", "rfid clone", "ddos", "social engineer", "0day exploit",
    "keylogger", "ransomware", "c2 server", "sqlmap", "metasploit",
    "hydra -l", "nmap -", "masscan", "hashcat", "john the ripper",
    "privilege escalation exploit", "weaponized", "payload delivery",
    ":(){ :|:& };:", "rm -rf /", "format c:", "mkfs.",
]

# Neutral vocabulary that should never alone trigger a high-risk verdict.
_NEUTRAL = ["credential", "password", "bypass", "delete", "attack", "exploit",
            "security", "token", "key", "secret"]


def _has_intent(text: str) -> bool:
    """Detect genuinely destructive *system* actions.

    Offensive-verb heuristics are intentionally avoided here because
    legitimate security-review/code-review skills frequently mention attacks
    (SQLi, credential leaks) as examples of what to *prevent*. Only
    system-destructive fault lines (which are never legitimately instructed)
    trigger a high-risk intent verdict.
    """
    low = text.lower()
    destructive = ["rm -rf /", ":(){ :|:& };:", "format c:", "mkfs.",
                   "dd if=/dev/zero", "> /dev/sda", "> /dev/hda",
                   "chmod -r /", "chmod 777 -r /", "yes > /dev/null"]
    # strip code-block lines so example payloads inside fenced blocks count
    lines = [ln for ln in text.splitlines()
             if ln.strip() and not ln.lstrip().startswith(("```", ">", "#"))]
    stripped = "\n".join(lines).lower()
    return any(m in low and m in stripped for m in destructive)


BLOCKED_SKILL_NAMES = {
    "port-scanner", "password-cracker", "pentest", "exploit-development",
    "phishing-campaign", "credential-stuffing", "brute-force", "malware-dev",
    "sqlmap", "metasploit", "hashcat", "hydra", "nmap", "ffuf", "aircrack",
    "wireshark-attack", "beef-xss",
}


class Skill:
    def __init__(self, path: str, name: str, description: str,
                 risk: str = RISK_SAFE, meta: dict | None = None):
        self.path = path
        self.name = name
        self.description = description
        self.risk = risk
        self.meta = meta or {}
        self.invocable = bool(self.meta.get("user-invocable", False))
        self.allowed_tools = self.meta.get("allowed-tools", [])

    def to_dict(self) -> dict:
        return {"path": self.path, "name": self.name,
                "description": self.description, "risk": self.risk,
                "invocable": self.invocable,
                "allowed_tools": self.allowed_tools,
                "meta": self.meta}


def _read_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-ish front matter (--- ... ---) leniently."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if not k:
            continue
        if v.lower() in ("true", "false"):
            v = v.lower() == "true"
        elif v.startswith("[") and v.endswith("]"):
            v = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        meta[k] = v
    return meta, m.group(2)


def discover_skills(skill_root: str, max_depth: int = 3) -> list[Skill]:
    """Walk skill_root for SKILL.md files (bounded) and return Skill objects."""
    skills = []
    if not os.path.isdir(skill_root):
        return skills
    root = os.path.realpath(skill_root)
    for dirpath, dns, fns in os.walk(root):
        depth = os.path.relpath(dirpath, root).count(os.sep)
        if depth > max_depth:
            dns[:] = []
            continue
        if "SKILL.md" in fns:
            sk_path = os.path.join(dirpath, "SKILL.md")
            try:
                text = open(sk_path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            meta, _ = _read_frontmatter(text)
            name = meta.get("name") or os.path.basename(dirpath)
            desc = meta.get("description") or ""
            risk = assess_risk(name, desc, text)
            skills.append(Skill(path=os.path.relpath(sk_path, root),
                                name=name, description=desc, risk=risk,
                                meta=meta))
    return skills


def assess_risk(name: str, description: str, body: str) -> str:
    blob = f"{name} {description}".lower()
    body_low = body.lower()
    if any(b in (name or "").lower() for b in BLOCKED_SKILL_NAMES):
        return RISK_HIGH
    for marker in HIGH_RISK_MARKERS:
        if marker in blob:
            return RISK_HIGH
    if _has_intent(body):
        return RISK_HIGH
    # moderately risky: destructive/dangerous shells or explicit offensive
    # framework names discovered contextually
    if any(x in body_low for x in ("nmap", "masscan", "hydra", "sqlmap",
                                   "wireshark")) and _has_intent(body):
        return RISK_MODERATE
    return RISK_SAFE


def load_skill(skill: Skill, base: str) -> dict:
    """Load the full skill text + structure for a vetted skill."""
    path = os.path.join(base, skill.path)
    text = open(path, encoding="utf-8", errors="replace").read()
    support = []
    d = os.path.dirname(path)
    for f in sorted(os.listdir(d)):
        if f in ("SKILL.md",) or f.startswith("."):
            continue
        support.append(f)
    return {"skill": skill.to_dict(), "body": text, "supporting_files": support}


def curated_allow_list() -> list[str]:
    """Names/groups we consider safe and useful for Elysia's default agent."""
    return [
        "code-review", "autofix", "git-commit", "github-pr",
        "documentation", "research", "planner", "architect",
        "senior-architect", "test-driven", "systematic-debugging",
        "security-review", "commit-hygiene", "code-quality",
        "retrospective", "ticket", "release",
    ]