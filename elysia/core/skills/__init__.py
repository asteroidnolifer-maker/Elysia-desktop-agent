"""Elysia Skill Ecosystem — canonical skill registry and tooling.

Implements the open Agent Skills / SKILL.md format with:
- Tolerant front-matter parser (YAML-ish)
- SQLite-backed registry with all required metadata fields
- Progressive disclosure: metadata at startup, full body on selection
- Trust levels, risk assessment, dependency resolution
- Skill composer for multi-skill plans
- Evaluation framework with quarantine
- CLI integration
"""
from .registry import SkillRegistry, SkillEntry
from .loader import SkillLoader, discover_skills, load_skill, parse_frontmatter
from .router import SkillRouter, SkillMatch
from .composer import SkillComposer, SkillPlan
from .evaluator import SkillEvaluator, SkillTest, EvaluationResult
from .security import assess_risk, BLOCKED_SKILL_NAMES, HIGH_RISK_MARKERS, RISK_SAFE, RISK_LOW, RISK_MODERATE, RISK_HIGH
from .cache import SkillCache, CachedSkill

# Legacy alias for backward compatibility
_read_frontmatter = parse_frontmatter

__all__ = [
    "SkillRegistry",
    "SkillEntry",
    "SkillLoader",
    "discover_skills",
    "load_skill",
    "parse_frontmatter",
    "SkillRouter",
    "SkillMatch",
    "SkillComposer",
    "SkillPlan",
    "SkillEvaluator",
    "SkillTest",
    "EvaluationResult",
    "assess_risk",
    "BLOCKED_SKILL_NAMES",
    "HIGH_RISK_MARKERS",
    "RISK_SAFE",
    "RISK_LOW",
    "RISK_MODERATE",
    "RISK_HIGH",
    "SkillCache",
    "CachedSkill",
]