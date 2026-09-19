"""High-level Intelligence Fabric interface.

Conceptually:
    IntelligenceFabric
        .plan(task, agent, user_context, available_tools, available_skills,
              provider_capabilities, resource_state) -> IntelligencePlan

The plan must be inspectable — no hidden decisions.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from .knowledge import KnowledgeRegistry
from .retrieval import HybridRetriever
from .datasets import DatasetRegistry
from .adapters import AdapterRegistry, AdapterRouter
from .router import IntelligenceRouter
from .provenance import ProvenanceTracker


@dataclass
class IntelligencePlan:
    """Inspectable execution plan produced by the Intelligence Fabric."""
    objective: str
    knowledge_sources: list[str] = field(default_factory=list)
    retrieved_context: list[dict] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    adapters: list[str] = field(default_factory=list)
    memory: list[dict] = field(default_factory=list)
    provider: Optional[dict] = None
    model: Optional[str] = None
    tools: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    resource_budget: dict = field(default_factory=dict)
    verification_plan: list[str] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    run_id: str = field(default_factory=lambda: f"run-{uuid.uuid4().hex[:8]}")
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


class IntelligenceFabric:
    """Unified knowledge, retrieval, skill, adapter, and routing layer.

    Integrates with the canonical Elysia architecture:
    MasterController -> Scheduler -> TaskExecutor -> AgentPipeline ->
    ProviderManager -> ToolManager -> Workspace -> QA
    """

    def __init__(self, workspace_root: str, config=None):
        self.workspace_root = workspace_root
        self.config = config
        # Core subsystems
        self.knowledge = KnowledgeRegistry(workspace_root)
        self.retriever = HybridRetriever(self.knowledge)
        self.datasets = DatasetRegistry(workspace_root)
        self.adapters = AdapterRegistry(workspace_root)
        self.adapter_router = AdapterRouter(self.adapters)
        self.router = IntelligenceRouter(
            knowledge=self.knowledge,
            skills=None,  # set by SkillRegistry integration
            adapters=self.adapters,
            providers=None,  # set by ProviderManager integration
        )
        self.provenance = ProvenanceTracker()
        # Runtime state
        self._plan_cache: dict[str, IntelligencePlan] = {}

    def plan(self, task: dict, agent: str = "implementer",
             user_context: dict = None, available_tools: list = None,
             available_skills: list = None, provider_capabilities: list = None,
             resource_state: dict = None) -> IntelligencePlan:
        """Produce an IntelligencePlan for the given task.

        This is the main entry point called by MasterController.plan()
        before dispatching to the scheduler.
        """
        # Build cache key for plan caching
        cache_key = self._cache_key(task, agent, provider_capabilities)
        if cache_key in self._plan_cache:
            return self._plan_cache[cache_key]

        objective = task.get("description") or task.get("title") or ""
        plan = IntelligencePlan(objective=objective)

        # 1. Knowledge Router: what sources are relevant?
        knowledge_sources = self.router.knowledge_router.select_sources(
            task=task, domain=self._infer_domain(task),
            query=objective, user_context=user_context,
            skills=available_skills, provider_capabilities=provider_capabilities
        )
        plan.knowledge_sources = knowledge_sources

        # 2. Retrieval: get relevant context chunks
        retrieved = self.retriever.retrieve(
            query=objective, sources=knowledge_sources,
            task=task, budget_tokens=2000
        )
        plan.retrieved_context = retrieved

        # 3. Skill Router: which skills are relevant?
        skills = self.router.skill_router.select_skills(
            task=task, domain=self._infer_domain(task),
            available_skills=available_skills or [],
            retrieved_context=retrieved
        )
        plan.skills = skills

        # 4. Adapter Router: which adapters are compatible?
        adapters = self.adapter_router.select(
            task=task, domain=self._infer_domain(task),
            base_model=self._get_base_model(provider_capabilities),
            required_capabilities=provider_capabilities,
            available_adapters=self.adapters.list(),
            resource_state=resource_state
        )
        plan.adapters = adapters

        # 5. Provider / Model routing (delegated to ProviderManager)
        if provider_capabilities:
            # The actual provider selection happens in ProviderManager
            # Here we just record the requirements
            plan.provider = {"required_capabilities": provider_capabilities}

        # 6. Tools required
        plan.tools = available_tools or []

        # 7. Permissions required (from skill + tool declarations)
        plan.permissions = self._compute_permissions(skills, available_tools)

        # 8. Resource budget estimation
        plan.resource_budget = self._estimate_resources(task, skills, adapters)

        # 9. Verification plan
        plan.verification_plan = self._build_verification_plan(task, skills)

        # 10. Provenance tracking
        plan.provenance = self.provenance.record_plan(plan)

        # Cache and return
        self._plan_cache[cache_key] = plan
        return plan

    def _cache_key(self, task: dict, agent: str, provider_caps: list = None) -> str:
        import hashlib
        key_parts = [
            task.get("title", ""),
            task.get("description", ""),
            agent,
            str(sorted(provider_caps or [])),
        ]
        return hashlib.md5("|".join(key_parts).encode()).hexdigest()

    def _infer_domain(self, task: dict) -> str:
        """Infer the task domain from title/description."""
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

    def _get_base_model(self, provider_caps: list = None) -> str:
        """Get the configured base model from config."""
        if self.config and hasattr(self.config, "model"):
            return getattr(self.config.model, "name", "unknown")
        return "local"

    def _compute_permissions(self, skills: list, tools: list = None) -> list:
        """Compute required permissions from skills and tools."""
        perms = set()
        # Tool permissions would be looked up from ToolRegistry
        if tools:
            for tool in tools:
                perms.add(f"tool:{tool}")
        return list(perms)

    def _estimate_resources(self, task: dict, skills: list, adapters: list) -> dict:
        """Estimate resource requirements for the plan."""
        return {
            "cpu": "LIGHT",
            "memory_mb": 512,
            "network": bool(skills and any("web" in s for s in skills)),
            "local_llm_calls": len(skills) + 1,
            "estimated_tokens": 4000,
        }

    def _build_verification_plan(self, task: dict, skills: list) -> list:
        """Build verification steps for the plan."""
        steps = ["compile", "tests"]
        if any("security" in s for s in skills):
            steps.append("security_audit")
        if any("doc" in s for s in skills):
            steps.append("link_check")
        return steps

    def explain(self, task: str) -> dict:
        """Return a human-readable explanation of what the fabric would do."""
        task_dict = {"title": task, "description": task}
        plan = self.plan(task_dict)
        return {
            "mode": self.router.mode or "balanced",
            "skills": plan.skills,
            "knowledge_sources": plan.knowledge_sources,
            "adapters": plan.adapters,
            "provider_requirements": plan.provider,
            "estimated_tokens": plan.resource_budget.get("estimated_tokens"),
            "tools": plan.tools,
            "verification": plan.verification_plan,
        }

    def simulate(self, task: str) -> IntelligencePlan:
        """Dry-run: produce plan without executing anything."""
        return self.plan({"title": task, "description": task})


import hashlib