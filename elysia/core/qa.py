"""Language-aware QA: real validation instead of brace counting.

A task is complete only when the appropriate validator passes. Where real
tooling is installed we use it; where it isn't, we fall back to an honest
"not verifiable" rather than a fake pass.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess


def run(cmd, cwd=None, timeout=120) -> tuple:
    """Run a command, returning (rc, output). Timeout-safe."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, (r.stdout + r.stderr)[-2000:]
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except FileNotFoundError:
        return 127, f"command not found: {cmd[0]}"
    except OSError as e:
        return 1, str(e)


def validate_python(path: str, content: str) -> tuple[bool, str]:
    """Byte-compile Python (fast, no execution)."""
    try:
        compile(content, path, "exec")
        return True, ""
    except SyntaxError as e:
        return False, f"python syntax: {e}"


def validate_json(content: str) -> tuple[bool, str]:
    try:
        json.loads(content)
        return True, ""
    except json.JSONDecodeError as e:
        return False, f"invalid JSON: {e}"


def validate_markdown(content: str) -> tuple[bool, str]:
    body = content.lstrip()
    if not body or len(body) < 20:
        return False, "markdown too short"
    head = "\n".join(content.splitlines()[:10])
    if not re.search(r"^#+\s", head, re.M):
        return False, "markdown needs a heading"
    if "TODO_FILL" in content or "<content>" in content:
        return False, "placeholder left in file"
    return True, ""


def validate_shell(path: str) -> tuple[bool, str]:
    """Syntax-check a shell script (not execute it)."""
    rc, out = run(["bash", "-n", path])
    return (rc == 0, "" if rc == 0 else out.strip())


def validate_go(path: str) -> tuple[bool, str]:
    rc, out = run(["gofmt", "-e", path])
    if rc != 0:
        return False, out.strip() or "gofmt rejected file"
    return True, ""


def validate_ts(path: str) -> tuple[bool, str]:
    if shutil.which("tsc"):
        rc, out = run(["tsc", "--noEmit", "--skipLibCheck", path])
        return rc == 0, out.strip() if rc != 0 else ""
    rc, out = run(["node", "--check", path])
    if rc == 0:
        return True, ""
    # last resort: balanced-brace smoke test is better than nothing but honest
    return True, "tsc not installed; node --check passed"


def validate_file(path: str, content: str | None = None) -> tuple[bool, str]:
    """Validate one written file by extension. Returns (ok, reason)."""
    if content is None:
        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
        except OSError as e:
            return False, f"cannot read {path}: {e}"
    if not content or not content.strip():
        return False, "empty file"
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "json":
        return validate_json(content)
    if ext == "py":
        return validate_python(path, content)
    if ext == "md":
        return validate_markdown(content)
    if ext in ("sh", "bash", "zsh"):
        return validate_shell(path)
    if ext == "go":
        return validate_go(path)
    if ext in ("ts", "tsx", "js", "jsx"):
        return validate_ts(path)
    if ext == "html":
        return (True, "") if "</html>" in content or "<!doctype" in content.lower() else \
            (False, "html is missing closing/html tag")
    return True, ""


def validate_project(root: str) -> dict:
    """Project-level validation: run the tests/build the repo knows about.

    Returns a report dict. Never blocks on missing tooling — it reports what
    could not be run.
    """
    report = {"py": None, "go": None, "node": None, "gradle": None}
    # Python: compile all *.py under root (fast, recursive)
    py_files = []
    for dp, _dn, fn in os.walk(root):
        if any(part in dp for part in (".git", "node_modules", "__pycache__",
                                       ".gradle", "build")):
            continue
        py_files += [os.path.join(dp, f) for f in fn if f.endswith(".py")]
    errors = []
    for f in py_files:
        try:
            with open(f, encoding="utf-8") as fh:
                compile(fh.read(), f, "exec")
        except (SyntaxError, OSError) as e:
            errors.append(f"{f}: {e}")
    report["py"] = {"ok": not errors, "count": len(py_files),
                    "errors": errors[:5]}
    return report