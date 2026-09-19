"""Base classes for external agent integrations."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, List, Dict
from pathlib import Path


class ExternalAgentCapability(str, Enum):
    """Capabilities that external agents may have."""
    CODING = "coding"
    REPOSITORY_INSPECTION = "repository_inspection"
    TERMINAL = "terminal"
    FILE_EDIT = "file_edit"
    TEST_EXECUTION = "test_execution"
    DEBUGGING = "debugging"
    REFACTORING = "refactoring"
    CODE_REVIEW = "code_review"
    ARCHITECTURE_DESIGN = "architecture_design"


@dataclass
class AgentResult:
    """Normalized result from an external agent execution."""
    integration: str
    task_id: str
    status: str  # "completed", "failed", "partial", "cancelled"
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    test_results: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_output_reference: str = ""
    verification: dict = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str = ""
    duration_ms: float = 0.0


class ExternalAgent(ABC):
    """Abstract base class for external AI agents."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this integration (e.g., 'opencode', 'codex', 'freebuff')."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> List[ExternalAgentCapability]:
        """List of capabilities this agent supports."""
        pass

    @abstractmethod
    def inspect(self, workspace: str) -> Dict[str, Any]:
        """Inspect a repository/workspace and return analysis."""
        pass

    @abstractmethod
    def start_task(self, task: Dict[str, Any], workspace: str, permissions: List[str]) -> str:
        """Start a task and return an execution ID for monitoring."""
        pass

    @abstractmethod
    def send_instruction(self, execution_id: str, instruction: str) -> Dict[str, Any]:
        """Send an instruction to a running task."""
        pass

    @abstractmethod
    def observe(self, execution_id: str) -> Dict[str, Any]:
        """Observe the current state of a running task."""
        pass

    @abstractmethod
    def cancel(self, execution_id: str) -> bool:
        """Cancel a running task."""
        pass

    @abstractmethod
    def get_status(self, execution_id: str) -> Dict[str, Any]:
        """Get the current status of a task."""
        pass

    @abstractmethod
    def collect_result(self, execution_id: str) -> AgentResult:
        """Collect the final result of a completed task."""
        pass

    def health(self) -> Dict[str, Any]:
        """Return health status of this integration."""
        return {
            "name": self.name,
            "available": True,
            "capabilities": [c.value for c in self.capabilities],
        }

    def is_available(self) -> bool:
        """Check if this agent is available (installed, authenticated, etc.)."""
        return True


class IntegrationRegistry:
    """Registry for managing external agent integrations."""

    def __init__(self):
        self._agents: Dict[str, ExternalAgent] = {}

    def register(self, agent: ExternalAgent) -> None:
        self._agents[agent.name] = agent

    def unregister(self, name: str) -> bool:
        if name in self._agents:
            del self._agents[name]
            return True
        return False

    def get(self, name: str) -> Optional[ExternalAgent]:
        return self._agents.get(name)

    def list(self) -> List[ExternalAgent]:
        return list(self._agents.values())

    def get_by_capability(self, capability: ExternalAgentCapability) -> List[ExternalAgent]:
        return [a for a in self._agents.values() if capability in a.capabilities]

    def health_check(self) -> Dict[str, Any]:
        """Check health of all registered integrations."""
        results = {}
        for name, agent in self._agents.items():
            try:
                results[name] = agent.health()
            except Exception as e:
                results[name] = {"available": False, "error": str(e)}
        return results


from typing import Any, Optional, List, Dict, Optional