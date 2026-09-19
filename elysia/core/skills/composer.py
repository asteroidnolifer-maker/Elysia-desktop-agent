"""Skill Composer — multi-skill SkillPlan for complex tasks."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, List
from .registry import SkillRegistry, SkillEntry


@dataclass
class SkillPlan:
    """A composed plan using multiple skills."""
    objective: str
    skills: list[str] = field(default_factory=list)  # skill IDs in execution order
    dependencies: list[list[int]] = field(default_factory=list)  # indices of dependencies
    tools: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)


class SkillComposer:
    """Compose multiple skills into an executable plan."""

    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def compose(self, objective: str, skills: List[SkillEntry] = None,
                available_skills: List[SkillEntry] = None) -> SkillPlan:
        """Compose a plan using multiple skills."""
        if skills is None and available_skills is None:
            available_skills = self.registry.list(enabled_only=True, limit=50)

        # Simple heuristic: select skills whose domains match the objective
        obj_lower = objective.lower()
        selected = []

        if available_skills is None:
            available_skills = self.registry.list(enabled_only=True, limit=50)

        for skill in available_skills:
            score = 0
            if skill.domain and skill.domain in obj_lower:
                score += 10
            if any(tag in obj_lower for tag in skill.tags):
                score += 5
            if skill.name.lower() in obj_lower:
                score += 8
            if score > 0:
                selected.append((score, skill))

        selected.sort(key=lambda x: x[0], reverse=True)
        top_skills = [s for _, s in selected[:5]]

        # Resolve dependencies
        skill_ids = [s.id for s in top_skills]
        ordered, missing = self.registry.resolve_dependencies(skill_ids)

        plan = SkillPlan(
            objective=objective,
            skills=ordered,
            tools=[t for s in top_skills for t in s.required_tools],
            permissions=[p for s in top_skills for p in s.required_credentials],
        )
        return plan