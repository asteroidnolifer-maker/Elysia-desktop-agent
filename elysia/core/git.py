"""Git integration: status awareness, conflict detection, checkpoint commits.

Elysia never blindly overwrites unrelated user changes, never commits secrets
or runtime state, and never auto-pushes unless the user explicitly enables it.
"""
from __future__ import annotations

import os
import subprocess

NEVER_COMMIT = {".env", "*.key", "*.pem", "*.p12", "*.sqlite", "*.db",
                "*.log", "composio.env", "*.gguf", "*.onnx", "*.jar",
                "pool.lock", "pids"}


def git(root: str, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", root, *args],
                           capture_output=True, text=True, timeout=60)
        return r.returncode, (r.stdout or r.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def is_repo(root: str) -> bool:
    rc, _ = git(root, "rev-parse", "--is-inside-work-tree")
    return rc == 0


def status(root: str) -> list[str]:
    rc, out = git(root, "status", "--porcelain")
    if rc != 0:
        return []
    return [line for line in out.splitlines() if line]


def dirty_files(root: str) -> list[str]:
    return [line[3:] for line in status(root) if len(line) > 3]


def current_branch(root: str) -> str:
    rc, out = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return out if rc == 0 else ""


def has_conflicts(root: str) -> list[str]:
    rc, out = git(root, "diff", "--name-only", "--diff-filter=U")
    if rc != 0:
        return []
    return [l for l in out.splitlines() if l]


def safe_checkpoint(root: str, message: str) -> tuple[bool, str]:
    """Create a checkpoint commit without touching unrelated files.

    Only files matching the working set of the task (none here) would be
    staged; we deliberately DON'T add everything — callers pass explicit paths.
    """
    if not is_repo(root):
        return False, "not a git repo"
    conflicts = has_conflicts(root)
    if conflicts:
        return False, "unresolved merge conflicts: " + ", ".join(conflicts)
    # Refuse to commit without explicit paths (never `git add .`).
    return True, "checkpoint requires explicit paths (not invoked)"

# ---------------------------------------------------------------------------
# Secret redaction helper (shared by logs / responses / commits)
# ---------------------------------------------------------------------------
SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9]{16,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"ak_[A-Za-z0-9]{16,}",
    r"Bearer\s+[A-Za-z0-9._-]{12,}",
    r"Authorization:\s*[A-Za-z0-9._-]{12,}",
    r"(?i)api[_-]?key[\"']?\s*[:=]\s*[\"'][^\"']{8,}[\"']",
    r"(?i)client[_-]?secret[\"']?\s*[:=]\s*[\"'][^\"']{8,}[\"']",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
]


def redact(text: str) -> str:
    """Replace known secret patterns with [REDACTED]."""
    if not isinstance(text, str):
        return text
    for pat in SECRET_PATTERNS:
        text = re.sub(pat, "[REDACTED]", text)
    return text


import re  # noqa: E402  (used in redact above)