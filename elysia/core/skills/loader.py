"""Skill Loader — load full SKILL.md + supporting files on demand."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional
from .registry import SkillEntry
from .security import assess_risk


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-ish front matter (--- ... ---) leniently."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if not k:
            continue
        if v.lower() in ("true", "false"):
            v = v.lower() == "true"
        elif v.startswith("[") and v.endswith("]"):
            v = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        meta[k] = v
    return meta, m.group(2)


class Skill:
    """Represents a loaded skill with full content and supporting files."""
    def __init__(self, path: str, entry=None):
        self.path = path
        self.entry = entry
        self.body = ""
        self.supporting_files = []

    def to_dict(self) -> dict:
        return {
            "skill": self.entry.to_dict() if self.entry else {},
            "body": self.body,
            "supporting_files": self.supporting_files
        }


class SkillLoader:
    """Load full skill content on demand (progressive disclosure)."""

    def __init__(self, skills_root: str, registry=None):
        self.skills_root = Path(skills_root).resolve()
        self.registry = registry

    def load_skill(self, skill: SkillEntry) -> dict:
        """Load full skill text + supporting files for a vetted skill."""
        skill_path = self.skills_root / skill.path
        if not skill_path.exists():
            raise FileNotFoundError(f"SKILL.md not found: {skill_path}")

        text = skill_path.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)

        supporting = []
        skill_dir = skill_path.parent
        for f in sorted(os.listdir(skill_dir)):
            if f in ("SKILL.md",) or f.startswith("."):
                continue
            fpath = skill_dir / f
            if fpath.is_file() and fpath.stat().st_size < 500_000:
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    supporting.append({"name": f, "content": content})
                except OSError:
                    pass

        return {
            "skill": skill.to_dict() if hasattr(skill, "to_dict") else {"id": "unknown"},
            "body": body,
            "supporting_files": supporting
        }

    def load_skill_by_id(self, skill_id: str, registry) -> dict:
        """Load skill by registry ID."""
        entry = registry.get(skill_id)
        if not entry:
            raise KeyError(f"Skill not found: {skill_id}")
        return self.load_skill(entry)

    def discover_skills(self, max_depth: int = 3) -> list[SkillEntry]:
        """Walk skill_root for SKILL.md files and return SkillEntry objects."""
        skills = []
        if not self.skills_root.is_dir():
            return skills

        for dirpath, dnames, fnames in os.walk(self.skills_root):
            depth = Path(dirpath).relative_to(self.skills_root).parts
            if len(depth) > max_depth:
                dnames[:] = []
                continue
            if "SKILL.md" in fnames:
                sk_path = Path(dirpath) / "SKILL.md"
                try:
                    text = sk_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                meta, body = parse_frontmatter(text)
                name = meta.get("name") or Path(dirpath).name
                desc = meta.get("description") or ""
                risk = assess_risk(name, desc, body)
                skills.append(SkillEntry(
                    local_path=os.path.relpath(sk_path, self.skills_root),
                    name=name, description=desc, risk_level=risk,
                ))
        return skills


# Module-level convenience functions
_default_loader: "SkillLoader" = None


def _get_loader() -> SkillLoader:
    global _default_loader
    if _default_loader is None:
        skills_root = os.path.join(os.getcwd(), "elysia", "skills")
        _default_loader = SkillLoader(skills_root)
    return _default_loader


def discover_skills(skills_root: str = None, max_depth: int = 3) -> list:
    """Discover skills in the given root (or default)."""
    if skills_root:
        loader = SkillLoader(skills_root)
    else:
        loader = _get_loader()
    return loader.discover_skills(max_depth)


def load_skill(skill_id: str, registry) -> dict:
    """Load a skill by ID using the default loader."""
    return _get_loader().load_skill_by_id(skill_id, registry)


from datetime import datetime
from typing import Optional