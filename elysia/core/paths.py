"""Secure workspace path resolution.

Unlike the old string-mangling approach (`path.lstrip("/").replace("..", "_")`),
every path is canonicalized and verified to remain inside the workspace root.
Traversal, absolute escapes and symlink escapes are rejected with an error —
never silently "fixed".
"""
from __future__ import annotations

import os


class PathEscapeError(ValueError):
    """Raised when a requested path escapes the workspace root."""


def resolve_path(root: str, rel: str) -> str:
    """Canonically resolve ``rel`` (a workspace-relative path) inside ``root``.

    Returns the absolute, symlink-resolved path. Raises PathEscapeError if the
    result is outside ``root`` or if any component is a ``..`` escape or a
    symlink pointing outside the root.
    """
    root = os.path.realpath(root)
    if not isinstance(rel, str) or rel == "":
        raise PathEscapeError("empty path")
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or os.path.isabs(rel):
        raise PathEscapeError(f"absolute path not allowed: {rel}")
    parts = rel.split("/")
    if any(p in ("", "..", ".") for p in parts):
        raise PathEscapeError(f"path must not contain '.', '..' or empty parts: {rel}")

    # Fast lexical guard BEFORE any filesystem access.
    cand = os.path.join(root, *parts)
    if not is_within(root, cand):
        raise PathEscapeError(f"path escapes workspace: {rel}")

    # Resolve symlinks component by component so a link inside the tree that
    # points outside (or a link to a link) is rejected, not followed silently.
    current = root
    for part in parts:
        current = os.path.join(current, part)
        # lstat: if it is a symlink, resolve and verify target stays inside.
        if os.path.islink(current):
            target = os.path.realpath(current)
            if not is_within(root, target):
                raise PathEscapeError(f"symlink escapes workspace: {rel}")
            current = target
        elif os.path.exists(current):
            rl = os.path.realpath(current)
            if not is_within(root, rl):
                raise PathEscapeError(f"path resolves outside workspace: {rel}")
            current = rl
    final = os.path.realpath(current)
    if not is_within(root, final):
        raise PathEscapeError(f"path escapes workspace: {rel}")
    return final


def is_within(root: str, cand: str) -> bool:
    """True if ``cand`` is inside ``root`` (both absolute, cleaned)."""
    root = os.path.abspath(root)
    cand = os.path.abspath(cand)
    return cand == root or cand.startswith(root + os.sep)


def safe_join(root: str, *parts: str) -> str:
    """Join parts into a validated workspace path (for writing new files)."""
    rel = "/".join(str(p) for p in parts if p != "")
    return resolve_path(root, rel)


def workspace_file(root: str, rel: str) -> str | None:
    """Like resolve_path but returns None instead of raising (convenience)."""
    try:
        return resolve_path(root, rel)
    except PathEscapeError:
        return None


def validate_file_list(root: str, files) -> list:
    """Validate and canonicalize a list of owned file paths.

    Returns a list of canonical relative paths (POSIX separators, relative to
    root). Raises PathEscapeError if any entry is invalid.
    """
    out = []
    for f in files or []:
        if not isinstance(f, str) or not f.strip():
            continue
        f = f.strip()
        abs_path = resolve_path(root, f)
        rel = os.path.relpath(abs_path, os.path.realpath(root))
        out.append(rel.replace(os.sep, "/"))
    return out