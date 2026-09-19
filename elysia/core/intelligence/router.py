"""Intelligence Router — unify knowledge, skills, adapters, provider routing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, List

from .knowledge import KnowledgeRegistry
from elysia.core.skills import discover_skills, Skill  # from elysia.core.skills
from .adapters import AdapterRegistry, AdapterRouter
from elysia.core.providers import ProviderManager  # from elysia.core.providers


@dataclass
class KnowledgeSource:
    id: str
    title: str
    source_type: str
    domain: str
    trust_level: str
    retrieval_strategy: str = "hybrid"  # keyword, semantic, hybrid
    filters: dict = field(default_factory=dict)
    context_budget: int = 2000


@dataclass
class SkillMatch:
    skill_id: str
    name: str
    relevance: float  # 0-1
    reason: str


@dataclass
class AdapterMatch:
    adapter_id: str
    name: str
    compatibility: dict
    reason: str


class KnowledgeRouter:
    """Select relevant knowledge sources for a task."""

    def __init__(self, knowledge: KnowledgeRegistry):
        self.knowledge = knowledge

    def select_sources(self, task: dict, domain: str, query: str,
                       user_context: dict = None, skills: list = None,
                       provider_capabilities: list = None) -> list[KnowledgeSource]:
        """Determine what knowledge sources are relevant."""
        sources = []

        # Search knowledge registry
        entries = self.knowledge.search(
            query=query,
            domain=domain,
            limit=10
        )

        for e in entries:
            sources.append(KnowledgeSource(
                id=e.id,
                title=e.title,
                source_type=e.source_type,
                domain=e.domain,
                trust_level=e.trust_level,
                filters={"source": e.source}
            ))

        return sources


class SkillRouter:
    """Select relevant skills for a task."""

    def __init__(self):
        # Skills are discovered from elysia.core.skills at runtime
        self._skill_cache: list = None

    def _get_skills(self) -> list:
        if self._skill_cache is None:
            self._skill_cache = discover_skills(os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "skills"
            ))
        return self._skill_cache

    def select_skills(self, task: dict, domain: str,
                      available_skills: list = None,
                      retrieved_context: list = None) -> list[SkillMatch]:
        """Select skills relevant to the task."""
        if available_skills is None:
            available_skills = self._get_skills()

        matches = []
        task_text = (task.get("title", "") + " " + task.get("description", "")).lower()

        for skill in available_skills:
            skill_text = (skill.name + " " + skill.description).lower()
            # Simple keyword overlap scoring
            skill_words = set(skill_text.split())
            task_words = set(task_text.split())
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


class IntelligenceRouter:
    """Unified router for knowledge, skills, adapters, and providers."""

    def __init__(self, knowledge: KnowledgeRegistry,
                 adapter_registry: AdapterRegistry, provider_manager):
        self.knowledge_router = KnowledgeRouter(knowledge)
        self.skill_router = SkillRouter()
        self.adapter_router = AdapterRouter(adapter_registry)
        self.provider_manager = provider_manager
        self.mode = "balanced"  # fast, balanced, deep, research, coding, offline

    def route(self, task: dict, agent: str, user_context: dict = None,
              available_tools: list = None, available_skills: list = None,
              provider_capabilities: list = None, resource_state: dict = None) -> dict:
        """Full routing decision for a task."""
        domain = self._infer_domain(task)
        objective = task.get("description") or task.get("title") or ""

        # 1. Knowledge
        knowledge_sources = self.knowledge_router.select_sources(
            task, domain, objective, user_context, available_skills, provider_capabilities
        )

        # 2. Skills
        skill_matches = self.skill_router.select_skills(
            task, domain, available_skills
        )

        # 3. Adapters
        adapter_matches = self.adapter_router.select(
            task=task, domain=domain, base_model="local",
            required_capabilities=provider_capabilities,
            resource_state=resource_state
        )

        # 4. Provider (delegated to ProviderManager)
        # Just record requirements
        provider_req = {"required_capabilities": provider_capabilities or ["chat"]}

        return {
            "mode": self.mode,
            "domain": domain,
            "knowledge": [ks.to_dict() for ks in knowledge_sources],
            "skills": [sm.__dict__ for sm in skill_matches],
            "adapters": adapter_matches,
            "provider": provider_req,
            "context_budget": 4000,
        }

    def _infer_domain(self, task: dict) -> str:
        text = (task.get("title", "") + " " + task.get("description", "")).lower()
        domains = {
            "coding": ["code", "implement", "fix", "refactor", "debug", "function", "class", "api"],
            "research": ["research", "investigate", "analyze", "compare", "study"],
            "finance": ["financial", "budget", "revenue", "profit", "stock", "market"],
            "documentation": ["document", "readme", "guide", "tutorial", "explain"],
            "security": ["security", "vulnerability", "audit", "penetration", "threat"],
            "data": ["data", "csv", "sql", "database", "query", "etl"],
        }
        for domain, keywords in domains.items():
            if any(k in text for k in keywords):
                return domain
        return "general"

    def explain(self, task: str) -> dict:
        """Human-readable routing explanation."""
        task_dict = {"title": task, "description": task}
        route = self.route(task_dict, "implementer")
        return {
            "mode": self.mode,
            "domain": route["domain"],
            "skills": [s["name"] for s in route["skills"]],
            "knowledge_sources": len(route["knowledge"]),
            "adapters": route["adapters"],
            "provider_requirements": route["provider"],
        }

    def set_mode(self, mode: str):
        """Set intelligence mode: fast, balanced, deep, research, coding, offline."""
        valid = ["fast", "balanced", "deep", "research", "coding", "offline"]
        if mode in valid:
            self.mode = mode