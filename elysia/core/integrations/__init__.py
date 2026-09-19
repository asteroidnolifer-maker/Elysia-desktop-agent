"""Elysia External Agent Integrations — unified interface for AI coding agents.

Provides a common abstraction for external AI agents (Freebuff, OpenCode, Codex, etc.)
that can inspect repositories, edit files, run commands, and iterate on tasks.
"""
from .base import ExternalAgent, ExternalAgentCapability, AgentResult
from .registry import IntegrationRegistry, get_registry, get_integration, list_integrations, run_integration_task
from .opencode import OpenCodeAgent
from .codex import CodexAgent
from .freebuff import FreebuffAgent

__all__ = [
    "ExternalAgent",
    "ExternalAgentCapability",
    "AgentResult",
    "IntegrationRegistry",
    "get_registry",
    "get_integration",
    "list_integrations",
    "run_integration_task",
    "OpenCodeAgent",
    "CodexAgent",
    "FreebuffAgent",
]