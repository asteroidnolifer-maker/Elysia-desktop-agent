"""Integration Registry — discover, register, and manage external agent integrations."""
from __future__ import annotations

from typing import Dict, List, Optional
from .base import ExternalAgent, IntegrationRegistry, ExternalAgentCapability


# Global registry instance
_registry: Optional[IntegrationRegistry] = None


def get_registry() -> IntegrationRegistry:
    """Get the global integration registry."""
    global _registry
    if _registry is None:
        _registry = IntegrationRegistry()
        # Auto-discover available integrations
        _discover_integrations(_registry)
    return _registry


def _discover_integrations(registry: IntegrationRegistry) -> None:
    """Discover and register available integrations."""
    # Try to import and register each known integration
    integrations_to_try = [
        ("opencode", "elysia.core.integrations.opencode", "OpenCodeAgent"),
        ("codex", "elysia.core.integrations.codex", "CodexAgent"),
        ("freebuff", "elysia.core.integrations.freebuff", "FreebuffAgent"),
    ]

    for name, module_path, class_name in integrations_to_try:
        try:
            module = __import__(module_path, fromlist=[class_name])
            agent_class = getattr(module, class_name)
            agent = agent_class()
            if agent.is_available():
                registry.register(agent)
        except ImportError:
            pass  # Integration not available
        except Exception:
            pass  # Log but continue


def get_integration(name: str) -> Optional[ExternalAgent]:
    """Get an integration by name."""
    return get_registry().get(name)


def list_integrations() -> List[Dict[str, Any]]:
    """List all available integrations with their status."""
    registry = get_registry()
    integrations = []
    for agent in registry.list():
        health = agent.health()
        integrations.append({
            "name": agent.name,
            "capabilities": [c.value for c in agent.capabilities],
            "available": health.get("available", False),
            "status": health.get("status", "unknown"),
        })
    return integrations


def run_integration_task(integration_name: str, task: Dict[str, Any],
                         workspace: str, permissions: List[str]) -> Dict[str, Any]:
    """Run a task using the specified integration."""
    registry = get_registry()
    agent = registry.get(integration_name)
    if not agent:
        return {"ok": False, "error": f"Integration '{integration_name}' not found"}

    if not agent.is_available():
        return {"ok": False, "error": f"Integration '{integration_name}' not available"}

    execution_id = agent.start_task(task, workspace, permissions)
    # For now, we'll just return the execution ID; real implementation would monitor
    return {"ok": True, "execution_id": execution_id, "agent": integration_name}