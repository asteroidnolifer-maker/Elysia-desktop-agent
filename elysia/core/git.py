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


def safe_checkpoint(root: str, message: str, paths=None,
                    never_commit=None) -> tuple[bool, str]:
    """Create a checkpoint commit without touching unrelated files.

    ``paths`` (optional) restricts staging to explicit paths; when None, only
    tracked changes are staged via ``git add -u`` plus untracked files that are
    NOT in never_commit. Never runs ``git add .``.
    """
    if not is_repo(root):
        return False, "not a git repo"
    conflicts = has_conflicts(root)
    if conflicts:
        return False, "unresolved merge conflicts: " + ", ".join(conflicts)
    never = set(never_commit or NEVER_COMMIT)
    if paths:
        for p in paths:
            rc, err = git(root, "add", "--", p)
            if rc != 0:
                return False, f"git add {p}: {err}"
    else:
        rc, out = git(root, "add", "-u")  # tracked changes only
        if rc != 0:
            return False, f"git add -u: {out}"
        # add untracked files that pass the never_commit filter
        rc, out = git(root, "ls-files", "--others", "--exclude-standard")
        if rc == 0:
            for rel in out.splitlines():
                if _matches_never(rel, never):
                    continue
                rc2, err2 = git(root, "add", "--", rel)
                if rc2 != 0:
                    return False, f"git add {rel}: {err2}"
    rc, out = git(root, "diff", "--cached", "--quiet")
    if rc == 0:
        return False, "nothing to checkpoint"
    clean_msg = redact(message)[:200]
    rc, out = git(root, "commit", "-m", clean_msg)
    if rc != 0:
        return False, f"git commit: {out}"
    return True, out


def _matches_never(rel: str, never: set[str]) -> bool:
    import fnmatch
    base = os.path.basename(rel)
    for pat in never:
        if fnmatch.fnmatch(rel, pat) or (pat.startswith("*")
                                         and fnmatch.fnmatch(base, pat)):
            return True
    return False


def checkpoint_list(root: str, limit: int = 10, prefix: str = "") -> list[dict]:
    rc, out = git(root, "log", "--oneline", "-n", str(limit))
    if rc != 0:
        return []
    commits = []
    for line in out.splitlines():
        sha, _, rest = line.partition(" ")
        commits.append({"sha": sha, "message": rest})
    return commits


def since_last_checkpoint(root: str, branch: str = "") -> list[str]:
    rc, out = git(root, "diff", "--name-status", "HEAD~1", "HEAD", "--")
    if rc != 0:
        return []
    return [l for l in out.splitlines() if l]


def last_checkpoint(root: str, prefix: str = "") -> dict | None:
    rc, out = git(root, "log", "-1", "--oneline")
    if rc != 0 or not out:
        return None
    sha, _, rest = out.partition(" ")
    return {"sha": sha, "message": rest}


def rollback_checkpoint(root: str, sha: str, hard: bool = False) -> tuple[bool, str]:
    """Reset working tree/commits to a checkpoint. Only ``hard=False`` by
    default (preserves working files, resets the index to the checkpoint)."""
    if not is_repo(root):
        return False, "not a git repo"
    flag = "--hard" if hard else "--soft"
    rc, out = git(root, "reset", flag, sha)
    if rc != 0:
        return False, f"reset: {out}"
    if not hard:
        # keep uncommitted changes, only move HEAD back
        rc2, out2 = git(root, "reset", "HEAD", "--")
        if rc2 == 0:
            return True, "index reset to " + sha
    return True, "hard reset to " + sha

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