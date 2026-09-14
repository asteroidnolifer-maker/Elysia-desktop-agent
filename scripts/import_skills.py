#!/usr/bin/env python3
"""Curated skill importer for Elysia.

Copies a small, vetted subset of skills from a cloned agent-skills collection
(e.g. byhartvig/agent-skills-collection) into ``elysia/skills/curated/``,
with:

  - risk assessment (high-risk/offensive skills are never imported)
  - a manifest.json recording provenance, license, and risk
  - an idempotent, safe copy (no deletion, no following symlinks out)

Usage:
    python scripts/import_skills.py /path/to/agent-skills-collection
    python scripts/import_skills.py --list /path/to/...        # show candidates
    python scripts/import_skills.py --list-all /path/to/...    # every safe skill
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from elysia.core.skills import discover_skills, assess_risk, curated_allow_list

BLOCKED = curated_allow_list  # (kept for external styling)

# Explicit pick list — precise collection-relative directory matches. Any skill
# whose *last* path segment starts with/equals one of these is eligible.
PICK = [
    # coderabbit / code-review-skills
    "code-review",
    "autofix",
    # dev-agent-skills (git + GitHub PR workflow)
    "git-commit",
    "github-pr-creation",
    "github-pr-merge",
    "github-pr-review",
    # debugging + documentation
    "systematic-debugging",
    "documentation",
    # architecture / python skills
    "senior-architect",
    "python",
    "existing-repo",
    "commit-hygiene",
]

# Names we refuse regardless (offensive tooling from the collection).
FORBIDDEN = {
    "port-scanner", "password-cracker", "pentest", "exploit-development",
    "phishing-campaign", "credential-stuffing", "brute-force", "malware-dev",
    "c2-server", "ransomware", "keylogger", "sqlmap", "metasploit", "nmap",
}

MAX_SKILL_DEPTH = 8  # a skill dir can hold supporting files but not subskills


def _short_id(rel_path: str) -> str:
    parts = rel_path.split(os.sep)
    # last *two* meaningful segments: <collection>/<skill>/SKILL.md
    n = len(parts)
    if n >= 3:
        return os.path.join(parts[-3], parts[-2])
    return os.path.join(*parts[-2:])


def import_selected(collection_root: str, dest: str,
                    pick: list[str] | None = None,
                    dry_run: bool = False) -> dict:
    pick = pick or PICK
    os.makedirs(dest, exist_ok=True)
    skills = discover_skills(collection_root, max_depth=6)
    manifest = {"source": collection_root, "skills": []}
    imported, skipped_high, skipped_missing = [], [], []

    picked_lower = [p.lower() for p in pick]
    for sk in skills:
        sid = _short_id(sk.path).lower()
        name = sk.name.lower()
        # match against pick names OR ending path segments
        matched = (name in picked_lower
                   or any(sid.endswith("/" + p.lower()) for p in pick))
        if not matched:
            continue
        if any(f in sid for f in FORBIDDEN):
            skipped_high.append((sid, "forbidden name"))
            continue
        risk = assess_risk(name, sk.description, open(
            os.path.join(collection_root, sk.path), encoding="utf-8",
            errors="replace").read())
        if risk in ("high", "moderate"):
            skipped_high.append((sid, f"risk={risk}"))
            continue
        # safe to copy
        if dry_run:
            imported.append(sid)
            manifest["skills"].append({"id": sid, "name": name,
                                       "risk": risk, "dry_run": True})
            continue
        rel = sk.path.replace("SKILL.md", "").rstrip("/")
        dest_dir = os.path.join(dest, rel)
        os.makedirs(dest_dir, exist_ok=True)
        src_dir = os.path.abspath(os.path.join(collection_root, rel))
        for fn in os.listdir(src_dir):
            if fn.startswith("."):
                continue
            src = os.path.join(src_dir, fn)
            if os.path.islink(src) or not os.path.isfile(src):
                continue
            shutil.copy2(src, os.path.join(dest_dir, fn))
        manifest["skills"].append({
            "id": sid, "name": name, "risk": risk,
            "description": sk.description[:200],
            "license": sk.meta.get("license", ""),
        })
        imported.append(sid)

    manifest_path = os.path.join(dest, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return {"imported": imported, "skipped_high": skipped_high,
            "manifest": manifest_path}


def list_all(collection_root: str) -> None:
    skills = discover_skills(collection_root, max_depth=6)
    safe = [s for s in skills if assess_risk(s.name, s.description,
                                            open(os.path.join(
                                                collection_root, s.path),
                                                encoding="utf-8",
                                                errors="replace").read())
            == "safe"]
    print(f"{len(safe)} safe skills; {len(skills) - len(safe)} higher-risk")
    for s in safe:
        print(f"  {_short_id(s.path):60} {s.description[:50]}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="import_skills")
    ap.add_argument("collection", help="path to cloned skills collection")
    ap.add_argument("--dest", default=None,
                    help="destination (default elysia/skills/curated)")
    ap.add_argument("--list", action="store_true",
                    help="list all safe candidates, do not import")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = os.path.realpath(__file__)
    repo = os.path.dirname(os.path.dirname(root))
    dest = args.dest or os.path.join(repo, "elysia", "skills", "curated")
    if args.list:
        list_all(args.collection)
        return 0
    result = import_selected(args.collection, dest, dry_run=args.dry_run)
    print(f"imported {len(result['imported'])} skills -> {result['manifest']}")
    print("skipped (forbidden/high-risk):")
    for sid, why in result["skipped_high"]:
        print(f"  - {sid}  ({why})")
    return 0


if __name__ == "__main__":
    sys.exit(main())