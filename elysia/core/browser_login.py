"""Desktop-browser login + local credential store for Elysia providers.

``elysia login openrouter`` (or ``elysia login claude-code`` for CLI agents):
  1. opens the provider's console/signup page in your desktop browser
     (xdg-open / open / start; the plain URL is always printed too)
  2. you create a key in the browser, then run the printed ``export`` line —
     or paste the key here and Elysia stores it locally
  3. stored keys live in ``config/providers.env`` (git-ignored pattern) with
     0600 permissions, and are loaded into the process environment on demand

Nothing is ever committed: ``config/*.env`` is blocked by .gitignore, and the
redaction helpers in ``elysia.core.git``/``config`` keep keys out of logs.
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import webbrowser

from .config import repo_root
from .provider_presets import CATALOG, missing_requirements

ENV_FILE = os.path.join(repo_root(), "config", "providers.env")


# ---------------------------------------------------------------------------
# Browser opening (desktop-first, headless-safe)
# ---------------------------------------------------------------------------

def open_browser(url: str) -> bool:
    """Try to open ``url`` in the desktop browser. True if a browser launched."""
    if not url or not url.startswith(("http://", "https://")):
        return False
    try:
        if webbrowser.open(url, new=2):
            return True
    except Exception:  # noqa: BLE001 — headless boxes have no browser
        pass
    for cmd in (["xdg-open", url], ["open", url], ["cmd", "/c", "start",
                                                   "", url]):
        try:
            if subprocess.run(cmd, capture_output=True, timeout=5).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def login_url(name: str) -> str:
    entry = CATALOG.get(name)
    if not entry:
        return ""
    docs = entry.get("docs", "")
    # CLI agents: docs is an install page, still useful to open
    return docs if docs.startswith("http") else ""


# ---------------------------------------------------------------------------
# Local credential store (config/providers.env, git-ignored)
# ---------------------------------------------------------------------------

def _shellsafe(v: str) -> str:
    v = (v or "").strip()
    if v.startswith("'") and v.endswith("'"):
        v = v[1:-1]
    return "'" + v.replace("'", "'\\''") + "'"


def load_env_file(path: str = ENV_FILE, into_environ: bool = True) -> int:
    """Load KEY=value lines into the environment. Returns count loaded.

    Values may be shell-quoted (KEY='v v'); quotes are stripped on load.
    Existing environment values always win (export beats stored key), so an
    operator can always override a stored credential for one session.
    """
    if not os.path.isfile(path):
        return 0
    loaded = 0
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if v.startswith("'") and v.endswith("'") and len(v) >= 2:
                v = v[1:-1].replace("'\\''", "'")  # undo shellsafe()
            elif v.startswith('"') and v.endswith('"') and len(v) >= 2:
                v = v[1:-1]
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k) or not v:
                continue
            if not into_environ and k in os.environ:
                continue
            if into_environ and os.environ.get(k):
                continue  # real environment wins
            os.environ[k] = v
            loaded += 1
    except OSError:
        return loaded
    return loaded


def save_key(provider: str, env_var: str, value: str,
             path: str = ENV_FILE) -> str:
    """Persist one credential line under 0600 permissions. Returns the path."""
    if not value or not value.strip():
        raise ValueError("empty credential value")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", env_var):
        raise ValueError(f"invalid env var name: {env_var}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    value = value.strip()
    lines = []
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            if line.strip() and not line.strip().startswith(f"{env_var}="):
                lines.append(line.rstrip("\n"))
    lines.append(f"{env_var}={_shellsafe(value)}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return path


def remove_key(env_var: str, path: str = ENV_FILE) -> bool:
    if not os.path.isfile(path):
        return False
    kept = [l.rstrip("\n") for l in open(path, encoding="utf-8")
            if l.strip() and not l.strip().startswith(f"{env_var}=")]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(kept) + ("\n" if kept else ""))
    return True


def stored_status(path: str = ENV_FILE) -> dict:
    """Which known provider env vars already have a stored value (no secrets)."""
    known = {}
    for name, e in CATALOG.items():
        for v in e.get("env", ()) or ():
            known.setdefault(v, name)
    found = {}
    if os.path.isfile(path):
        for line in open(path, encoding="utf-8"):
            k = line.split("=", 1)[0].strip()
            if k in known and k not in found:
                found[k] = known[k]
    return {"path": path, "stored": found}


def login(name: str, paste_value: str | None = None,
          no_browser: bool = False) -> dict:
    """Interactive login for provider ``name`` (browser + paste/store flow).

    Returns a structured result for the CLI to render. Never raises for
    normal failure modes; ValueError only for an empty pasted key.
    """
    entry = CATALOG.get(name)
    if not entry:
        return {"ok": False, "message": f"unknown provider: {name} (see "
                                        f"elysia providers --catalog)"}
    url = login_url(name)
    opened = False
    if url and not no_browser:
        opened = open_browser(url)
    if entry["kind"] == "cli":
        missing = missing_requirements(name)
        return {"ok": not missing, "opened": opened, "url": url,
                "message": (f"{entry['bin']} is installed — its existing "
                            f"login is reused."
                            if not missing else
                            f"install {entry['bin']} and finish its own "
                            f"login once; Elysia will then reuse it "
                            f"({entry['docs']})")}
    env_vars = entry["env"]
    instructions = (
        f"1) sign in / create an API key at: {url or entry['docs']}\n"
        f"2) run the export line below in this shell (or re-run with the key "
        f"pasted to store it in config/providers.env):\n"
        + "\n".join(f"   export {v}=_your_key_" for v in env_vars[:1]))
    if paste_value:
        if not str(paste_value).strip():
            return {"ok": False, "opened": opened, "url": url,
                    "message": "empty key; nothing stored"}
        path = save_key(name, env_vars[0], str(paste_value).strip(),
                        path=ENV_FILE)
        return {"ok": True, "opened": opened, "url": url,
                "message": f"stored {env_vars[0]} in {path} (0600, "
                           f"git-ignored); start a new shell or run "
                           f"`elysia login --load` to use it",
                "stored": env_vars[0]}
    return {"ok": False, "opened": opened, "url": url,
            "message": instructions, "needs_value": env_vars[0]}
