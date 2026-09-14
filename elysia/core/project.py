"""Project intelligence: what repository are we working in, and how is it built?

Scans a repo root (cheap, cacheable) for:
  - languages + primary framework
  - dependency files
  - build/test/lint/format commands (detected or configured)
  - entry points, CI config, module layout
  - git status summary

Used to seed the agent context layer so tools don't guess the test command.
"""
from __future__ import annotations

import json
import os
import subprocess
import time

COMMANDS = {
    "pytest": ["python -m pytest -q", "pytest -q", "mix test", "go test ./...",
               "cargo test", "npm test -- --runInBand", "pnpm test"],
    "test": ["python -m pytest -q", "pytest -q", "go test ./...", "mix test",
             "cargo test", "npm test", "pnpm test", "yarn test"],
    "build": ["python -m build", "npm run build", "pnpm build", "cargo build",
              "go build ./...", "mix compile"],
    "lint": ["python -m ruff check .", "flake8", "npm run lint", "golangci-lint run"],
    "format": ["python -m ruff format .", "black .", "npm run format",
               "gofmt -w ."],
    "typecheck": ["mypy .", "tsc --noEmit"],
}

EXTENSIONS = {
    "py": "Python", "go": "Go", "ts": "TypeScript", "tsx": "TypeScript",
    "js": "JavaScript", "jsx": "JavaScript", "rs": "Rust", "java": "Java",
    "kt": "Kotlin", "rb": "Ruby", "sh": "Shell", "c": "C", "h": "C",
    "cpp": "C++", "hpp": "C++", "cs": "C#", "php": "PHP", "swift": "Swift",
    "sql": "SQL", "html": "HTML", "css": "CSS", "vue": "Vue", "svelte": "Svelte",
}


class ProjectIntel:
    def __init__(self, root: str, cache_ttl_s: int = 120):
        self.root = os.path.realpath(root)
        self.cache_ttl = cache_ttl_s
        self._cache: dict | None = None
        self._at = 0.0

    def _fresh(self) -> bool:
        return (self._cache is not None
                and time.time() - self._at < self.cache_ttl)

    def detect(self) -> dict:
        if self._fresh():
            return self._cache
        info = self._detect_impl()
        self._cache = info
        self._at = time.time()
        return info

    def _detect_impl(self) -> dict:
        langs: dict[str, int] = {}
        dep_files = []
        entry_points = []
        by_ext: dict[str, str] = {}

        # top-level file scan (bounded)
        try:
            entries = os.listdir(self.root)
        except OSError:
            entries = []
        for name in entries[:500]:
            if name.startswith("."):
                continue
            low = name.lower()
            if low in {"requirements.txt", "pyproject.toml", "go.mod",
                       "package.json", "Cargo.toml", "build.gradle",
                       "pom.xml", "composer.json", "Gemfile", "mix.exs",
                       "pixi.toml", "uv.lock", "poetry.lock", "yarn.lock",
                       "pnpm-lock.yaml", "go.sum", "package-lock.json",
                       "pubspec.yaml", "setup.py"}:
                dep_files.append(name)

        # extension tally over a bounded walk
        for dp, dns, fns in os.walk(self.root):
            dns[:] = [d for d in dns if not d.startswith(".") and d not in
                      ("node_modules", "__pycache__", ".git", "build",
                       "dist", ".gradle", "target", "vendor")]
            for f in fns:
                ext = f.rsplit(".", 1)[-1].lower() if "." in f else ""
                if ext in EXTENSIONS:
                    langs[EXTENSIONS[ext]] = langs.get(EXTENSIONS[ext], 0) + 1
                    by_ext.setdefault(ext, os.path.join(dp, f))

        primary = max(langs, key=langs.get) if langs else "Unknown"
        entry_points = self._find_entry_points(primary, by_ext)

        commands = self._commands(langs, dep_files)
        git = self._git_summary()
        return {
            "root": self.root,
            "languages": dict(sorted(langs.items(), key=lambda x: -x[1])),
            "primary_language": primary,
            "dep_files": dep_files,
            "entry_points": entry_points,
            "commands": commands,
            "git": git,
            "detected_at": time.time(),
        }

    def _find_entry_points(self, primary, by_ext):
        candidates = {
            "Python": ["main.py", "manage.py", "app.py", "server.py",
                       "elysia/cli.py"],
            "Go": ["main.go", "cmd"],
            "TypeScript": ["src/main.ts", "src/index.ts", "index.ts"],
            "JavaScript": ["src/main.js", "src/index.js", "index.js"],
            "Rust": ["src/main.rs"],
        }.get(primary, [])
        found = [c for c in candidates
                 if os.path.exists(os.path.join(self.root, c))] or \
                [v for e, v in list(by_ext.items())[:3]]
        return found

    def _commands(self, langs, dep_files):
        out = {}
        lower_deps = [d.lower() for d in dep_files]
        has = lambda *names: any(n in lower_deps for n in names)
        if "pytest" in [d for d in lower_deps] or has("pyproject.toml",
                                                      "requirements.txt",
                                                      "setup.py"):
            out["test"] = "python -m pytest -q"
            out["build"] = "python -m build"
        elif has("package.json"):
            out["test"] = "npm test -- --runInBand"
            out["build"] = "npm run build"
            out["lint"] = "npm run lint"
        elif has("go.mod"):
            out["test"] = "go test ./..."
            out["build"] = "go build ./..."
        elif has("Cargo.toml"):
            out["test"] = "cargo test"
            out["build"] = "cargo build"
        elif has("pom.xml"):
            out["test"] = "mvn -q test"
            out["build"] = "mvn -q package"
        elif has("mix.exs"):
            out["test"] = "mix test"
        return out

    def _git_summary(self) -> dict:
        if not os.path.isdir(os.path.join(self.root, ".git")):
            return {}
        info = {"repo": True}
        for key, args in [
            ("branch", ["git", "-C", self.root, "rev-parse", "--abbrev-ref", "HEAD"]),
            ("head", ["git", "-C", self.root, "rev-parse", "--short", "HEAD"]),
        ]:
            try:
                r = subprocess.run(args, capture_output=True, text=True,
                                   timeout=8)
                info[key] = (r.stdout or r.stderr).strip()[:120] if r.returncode == 0 else ""
            except (OSError, subprocess.TimeoutExpired):
                info[key] = ""
        return info

    def to_context(self) -> str:
        info = self.detect()
        lines = [f"# Project: {info['root']}",
                 f"- primary language: {info['primary_language']}"]
        if info.get("languages"):
            top = ", ".join(f"{k} ({v})" for k, v in
                            list(info["languages"].items())[:4])
            lines.append(f"- languages: {top}")
        if info.get("dep_files"):
            lines.append("- dependency files: " + ", ".join(info["dep_files"]))
        if info.get("entry_points"):
            lines.append("- entry points: " + ", ".join(info["entry_points"]))
        if info.get("commands"):
            body = "; ".join(f"{k}: {v}" for k, v in info["commands"].items())
            lines.append(f"- detected commands: {body}")
        g = info.get("git") or {}
        if g.get("repo"):
            lines.append(f"- git: {g.get('branch')} @ {g.get('head')}")
        return "\n".join(lines)