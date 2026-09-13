"""Workspace manager: enforce secure file ownership.

All writes go through path validation (elysia.core.paths). A model-generated
path that escapes the workspace is an error reported back — never silently
remapped into an owned file.
"""
from __future__ import annotations

import os

from .paths import PathEscapeError, resolve_path, workspace_file


class Workspace:
    def __init__(self, root: str, max_read_chars: int = 9000):
        self.root = os.path.realpath(root)
        self.max_read_chars = max_read_chars
        os.makedirs(self.root, exist_ok=True)

    def resolve(self, rel: str) -> str:
        return resolve_path(self.root, rel)

    def resolve_or_none(self, rel: str) -> str | None:
        return workspace_file(self.root, rel)

    # -- read (reference files) ----------------------------------------------
    def read(self, rel: str, max_chars: int | None = None, surface=False) -> str:
        path = self.resolve(rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            raise FileNotFoundError(f"{rel}: {e}") from e
        limit = max_chars or self.max_read_chars
        if len(content) <= limit:
            return content
        if surface:
            return self._surface(rel, content)[:limit]
        return content[:limit]

    @staticmethod
    def _surface(rel: str, text: str) -> str:
        import re
        lines = text.splitlines()
        ext = rel.rsplit(".", 1)[-1].lower()
        out = []
        if ext == "md":
            out = [l.strip() for l in lines if l.lstrip().startswith("#")]
        elif ext == "py":
            pat = re.compile(r"^\s*(async\s+def|def|class|@[a-zA-Z_])[^:]*")
            out = [l.rstrip() for l in lines if pat.match(l)]
        elif ext == "go":
            pat = re.compile(r"^\s*(func|type|var|const)\s+")
            out = [l.rstrip() for l in lines if pat.match(l)]
        elif ext in ("ts", "tsx", "js", "jsx"):
            pat = re.compile(r"^\s*(export\s+)?(default\s+)?(async\s+)?"
                             r"(function|class|const|let|interface|type|enum)\s+")
            out = [l.rstrip() for l in lines if pat.match(l)]
        else:
            out = [l.rstrip() for l in lines[:60]]
        return "\n".join(out)[:limit]

    # -- write (owned files) ---------------------------------------------------
    def write_owned(self, rel: str, content: str) -> str:
        """Write a file owned by a task. Validates the path strictly.

        Returns the canonical absolute path. Raises PathEscapeError or OSError.
        """
        try:
            path = self.resolve(rel)
        except PathEscapeError:
            # Re-raise with the same message but include which input it was.
            raise
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def exists(self, rel: str) -> bool:
        p = self.resolve_or_none(rel)
        return p is not None and os.path.isfile(p)

    def list_files(self, subdir: str = "", max_depth: int = 4) -> list[str]:
        base = self.resolve(subdir or ".")
        out = []
        for dp, dn, fn in os.walk(base):
            depth = os.path.relpath(dp, self.root).count(os.sep)
            dn[:] = [d for d in dn if not d.startswith(".") and
                     d not in ("node_modules", "__pycache__", ".gradle", "build")]
            if depth >= max_depth:
                dn[:] = []
            for f in fn:
                out.append(os.path.relpath(os.path.join(dp, f), self.root))
        return sorted(out)