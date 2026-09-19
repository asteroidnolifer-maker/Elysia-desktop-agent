"""Skill Security — risk assessment and blocked skill names."""
from __future__ import annotations

# High-risk intent markers (aggressive activities, tool names, destructive patterns)
# Neutral nouns that legitimate security skills legitimately use are intentionally NOT included.
HIGH_RISK_MARKERS = [
    "crack", "pentest", "exploit-development", "phishing-campaign",
    "credential-stuffing", "brute-force", "malware-dev", "reverse shell",
    "port scan", "rfid clone", "ddos", "social engineer", "0day exploit",
    "keylogger", "ransomware", "c2 server", "sqlmap", "metasploit",
    "hydra -l", "nmap -", "masscan", "hashcat", "john the ripper",
    "privilege escalation exploit", "weaponized", "payload delivery",
    ":(){ :|:& };:", "rm -rf /", "format c:", "mkfs.",
]

# Neutral vocabulary that should never alone trigger a high-risk verdict
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
    destructive = [
        "rm -rf /", ":(){ :|:& };:", "format c:", "mkfs.",
        "dd if=/dev/zero", "> /dev/sda", "> /dev/hda",
        "chmod -r /", "chmod 777 -r /", "yes > /dev/null"
    ]
    # Strip code-block lines so example payloads inside fenced blocks count
    lines = [ln for ln in text.splitlines()
             if ln.strip() and not ln.lstrip().startswith(("```", ">", "#"))]
    stripped = "\n".join(lines).lower()
    return any(m in low and m in stripped for m in destructive)


# Skills that are always blocked regardless of content
BLOCKED_SKILL_NAMES = {
    "port-scanner", "password-cracker", "pentest", "exploit-development",
    "phishing-campaign", "credential-stuffing", "brute-force", "malware-dev",
    "sqlmap", "metasploit", "hashcat", "hydra", "nmap", "ffuf", "aircrack",
    "wireshark-attack", "beef-xss",
}


RISK_SAFE = "safe"
RISK_LOW = "low"
RISK_MODERATE = "moderate"
RISK_HIGH = "high"


def assess_risk(name: str, description: str, body: str) -> str:
    """Assess the risk level of a skill."""
    blob = f"{name} {description}".lower()
    body_low = body.lower()

    # Blocked names always high risk
    if any(b in (name or "").lower() for b in BLOCKED_SKILL_NAMES):
        return RISK_HIGH

    # High-risk markers in name/description
    for marker in HIGH_RISK_MARKERS:
        if marker in blob:
            return RISK_HIGH

    # Destructive intent in body
    if _has_intent(body):
        return RISK_HIGH

    # Moderately risky: destructive/dangerous tool names discovered contextually
    if any(x in body_low for x in ("nmap", "masscan", "hydra", "sqlmap", "wireshark")) and _has_intent(body):
        return RISK_MODERATE

    return RISK_SAFE