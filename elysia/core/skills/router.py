"""Skill Router — select relevant skills for a task."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, List
from .registry import SkillRegistry


@dataclass
class SkillMatch:
    skill_id: str
    name: str
    relevance: float  # 0-1
    reason: str


class SkillRouter:
    """Select relevant skills for a task based on keyword overlap and domain."""

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def select_skills(self, task: dict, domain: str,
                      available_skills: list = None,
                      retrieved_context: list = None) -> list[SkillMatch]:
        """Select skills relevant to the task."""
        if available_skills is None:
            available_skills = self.registry.list(
                enabled_only=True, domain=domain, limit=50
            )

        matches = []
        task_text = (task.get("title", "") + " " + task.get("description", "")).lower()

        for skill in available_skills:
            skill_text = (skill.name + " " + skill.description + " " + " ".join(skill.tags)).lower()
            skill_words = set(w for w in re.split(r"\W+", skill_text) if len(w) > 2)
            task_words = set(w for w in re.split(r"\W+", task_text) if len(w) > 2)
            if not skill_words or not task_words:
                continue
            overlap = len(skill_words & task_words)
            total = len(skill_words | task_words)
            relevance = overlap / max(total, 1)

            if relevance > 0.1:
                matches.append(SkillMatch(
                    skill_id=skill.id,
                    name=skill.name,
                    relevance=relevance,
                    reason=f"keyword overlap: {overlap}/{total}"
                ))

        matches.sort(key=lambda m: m.relevance, reverse=True)
        return matches[:5]


import re