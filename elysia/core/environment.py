"""Real environment inspection for the front door: repos, remotes, workspace.

Answers questions like "what github repos do i own?", "where is the repo?",
"what machine is this?" from ACTUAL local state — the git remotes of this
checkout, the ``gh`` CLI when it is authenticated, and the workspace tree —
instead of handing them to a small local model that used to invent refusals
("I don't have access to your GitHub repositories... contact your
administrator").

Design: stdlib only, every call bounded and failure-tolerant. When something is
genuinely unavailable it is reported as unavailable (with the exact command to
fix it); it is never guessed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

from .git import git as _git


def _run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or r.stderr or "").strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def remotes(root: str) -> list[dict]:
    """Named git remotes of ``root`` (real, no guessing)."""
    if not os.path.isdir(root):
        return []
    rc, out = _git(root, "remote", "-v")
    if rc != 0 or not out:
        return []
    seen: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            seen.setdefault(parts[0], parts[1])
    return [{"name": n, "url": u} for n, u in seen.items()]


def branch(root: str) -> str:
    rc, out = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return out if rc == 0 else ""


def gh_available() -> bool:
    return shutil.which("gh") is not None


def gh_authenticated() -> bool:
    if not gh_available():
        return False
    rc, _ = _run(["gh", "auth", "status"], timeout=15)
    return rc == 0


def github_repos(limit: int = 50) -> dict:
    """The operator's GitHub repositories via the authenticated ``gh`` CLI.

    Returns ``{"ok": bool, "repos": [...], "error": str}``. Never raises and
    never fabricates a list.
    """
    if not gh_available():
        return {"ok": False, "repos": [],
                "error": "the `gh` CLI is not installed (https://cli.github.com)"}
    if not gh_authenticated():
        return {"ok": False, "repos": [],
                "error": "`gh` is installed but not authenticated "
                         "(run `gh auth login`)"}
    rc, out = _run(["gh", "repo", "list", "--limit", str(int(limit)),
                    "--json", "nameWithOwner,visibility,isPrivate,"
                    "updatedAt,description"], timeout=25)
    if rc != 0:
        return {"ok": False, "repos": [], "error": (out or "gh failed")[:200]}
    try:
        repos = json.loads(out or "[]")
    except json.JSONDecodeError:
        return {"ok": False, "repos": [], "error": "gh returned invalid JSON"}
    return {"ok": True, "repos": repos, "error": ""}


def local_repos(workspace: str) -> list[dict]:
    """Git repositories under ``workspace`` (one level deep + the root)."""
    out: list[dict] = []
    if not os.path.isdir(workspace):
        return out
    if os.path.isdir(os.path.join(workspace, ".git")):
        out.append({"path": workspace, "remote": _first_remote(workspace)})
    try:
        entries = sorted(os.listdir(workspace))
    except OSError:
        return out
    for name in entries:
        p = os.path.join(workspace, name)
        if os.path.isdir(os.path.join(p, ".git")):
            out.append({"path": p, "remote": _first_remote(p)})
    return out


def _first_remote(root: str) -> str:
    rs = remotes(root)
    return rs[0]["url"] if rs else ""


def environment_report(root: str = "", workspace: str = "") -> str:
    """A grounded, human-readable answer about this machine and its repos."""
    from .config import repo_root
    root = root or repo_root()
    workspace = workspace or os.path.join(root, "workspace")
    lines: list[str] = ["ENVIRONMENT"]

    # 1) this checkout
    lines.append(f"  checkout : {root}")
    br = branch(root)
    if br:
        lines.append(f"  branch   : {br}")
    rs = remotes(root)
    if rs:
        for r in rs:
            lines.append(f"  remote   : {r['name']} -> {r['url']}")
    else:
        lines.append("  remote   : (none configured for this checkout)")

    # 2) the operator's GitHub repositories (real, only if gh can answer)
    lines.append("")
    lines.append("GITHUB REPOSITORIES")
    if gh_available():
        gh = github_repos()
        if gh["ok"]:
            repos = gh["repos"]
            lines.append(f"  {len(repos)} repository(ies) for the authenticated "
                         "gh account:")
            for r in repos[:40]:
                name = r.get("nameWithOwner") or r.get("name") or "?"
                vis = r.get("visibility") or ("private"
                                              if r.get("isPrivate") else "public")
                desc = (r.get("description") or "").strip()
                line = f"    - {name} [{vis}]"
                if desc:
                    line += f" — {desc[:70]}"
                lines.append(line)
        else:
            lines.append(f"  unavailable: {gh['error']}")
    else:
        lines.append("  unavailable: the `gh` CLI is not installed "
                     "(https://cli.github.com)")

    # 3) local repositories in the workspace
    lines.append("")
    lines.append("LOCAL REPOSITORIES (workspace)")
    lr = local_repos(workspace)
    if lr:
        for r in lr:
            rel = os.path.relpath(r["path"], root)
            lines.append(f"    - {rel}"
                         + (f"  ({r['remote']})" if r["remote"] else ""))
    else:
        lines.append("    (no git repositories found in the workspace)")
    return "\n".join(lines)


def environment_dict(root: str = "", workspace: str = "") -> dict:
    """Structured form of :func:`environment_report` for API callers."""
    from .config import repo_root
    root = root or repo_root()
    workspace = workspace or os.path.join(root, "workspace")
    gh = github_repos() if gh_available() else {
        "ok": False, "repos": [], "error": "gh not installed"}
    return {
        "root": root,
        "branch": branch(root),
        "remotes": remotes(root),
        "github": gh,
        "local_repos": local_repos(workspace),
    }
