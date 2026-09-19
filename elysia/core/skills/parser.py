"""Skill Parser — tolerant front-matter parser for SKILL.md files."""
from __future__ import annotations

import re
from typing import Any, Dict, Tuple


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML-ish front matter (--- ... ---) leniently.

    Returns (metadata_dict, body_text).
    """
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