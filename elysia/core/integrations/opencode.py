"""OpenCode Integration — execute coding tasks via OpenCode CLI."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import ExternalAgent, ExternalAgentCapability, AgentResult, IntegrationRegistry


@dataclass
class OpenCodeExecution:
    """Tracks an OpenCode execution."""
    execution_id: str
    task: Dict[str, Any]
    workspace: str
    process: Optional[subprocess.Popen] = None
    output_buffer: List[str] = field(default_factory=list)
    error_buffer: List[str] = field(default_factory=list)
    status: str = "running"  # running, completed, failed, cancelled
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    output_file: Optional[str] = None


class OpenCodeAgent:
    """OpenCode CLI integration for autonomous coding tasks."""

    def __init__(self):
        self._executations: Dict[str, OpenCodeExecution] = {}
        self._lock = threading.Lock()
        self._opencode_path = self._find_opencode()

    @property
    def name(self) -> str:
        return "opencode"

    @property
    def capabilities(self) -> List[ExternalAgentCapability]:
        return [
            ExternalAgentCapability.CODING,
            ExternalAgentCapability.REPOSITORY_INSPECTION,
            ExternalAgentCapability.TERMINAL,
            ExternalAgentCapability.FILE_EDIT,
            ExternalAgentCapability.TEST_EXECUTION,
        ]

    def _find_opencode(self) -> Optional[str]:
        """Find OpenCode executable."""
        return shutil.which("opencode")

    def is_available(self) -> bool:
        return self._opencode_path is not None

    def health(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "available": self.is_available(),
            "executable": self._opencode_path,
            "version": self._get_version() if self.is_available() else None,
            "status": "healthy" if self.is_available() else "unavailable",
        }

    def _get_version(self) -> str:
        try:
            result = subprocess.run(
                [self._opencode_path, "--version"],
                capture_output=True, text=True, timeout=10
            )
            return result.stdout.strip()
        except Exception:
            return "unknown"

    def inspect(self, workspace: str) -> Dict[str, Any]:
        """Inspect a repository for OpenCode compatibility."""
        if not self.is_available():
            return {"ok": False, "error": "OpenCode not installed"}

        workspace_path = Path(workspace)
        if not workspace_path.exists():
            return {"ok": False, "error": "Workspace does not exist"}

        # Check for common project files
        has_package_json = (workspace_path / "package.json").exists()
        has_pyproject = (workspace_path / "pyproject.toml").exists()
        has_go_mod = (workspace_path / "go.mod").exists()
        has_cargo = (workspace_path / "Cargo.toml").exists()
        has_git = (workspace_path / ".git").exists()

        return {
            "ok": True,
            "workspace": workspace,
            "project_type": self._detect_project_type(workspace_path),
            "has_git": has_git,
            "languages": self._detect_languages(workspace_path),
        }

    def _detect_project_type(self, workspace: Path) -> str:
        if (workspace / "package.json").exists():
            return "javascript/typescript"
        if (workspace / "pyproject.toml").exists() or (workspace / "requirements.txt").exists():
            return "python"
        if (workspace / "go.mod").exists():
            return "go"
        if (workspace / "Cargo.toml").exists():
            return "rust"
        return "unknown"

    def _detect_languages(self, workspace: Path) -> List[str]:
        langs = []
        if (workspace / "package.json").exists():
            langs.append("javascript")
            if (workspace / "tsconfig.json").exists():
                langs.append("typescript")
        if (workspace / "pyproject.toml").exists() or (workspace / "requirements.txt").exists():
            langs.append("python")
        if (workspace / "go.mod").exists():
            langs.append("go")
        if (workspace / "Cargo.toml").exists():
            langs.append("rust")
        if (workspace / "pom.xml").exists() or (workspace / "build.gradle").exists():
            langs.append("java")
        return langs

    def start_task(self, task: Dict[str, Any], workspace: str, permissions: List[str]) -> str:
        """Start an OpenCode task."""
        if not self.is_available():
            raise RuntimeError("OpenCode not available")

        execution_id = f"opencode-{uuid.uuid4().hex[:8]}"
        workspace_path = Path(workspace).resolve()

        # Prepare the task for OpenCode
        task_description = task.get("description", task.get("title", ""))

        # Create a temporary file with the task
        task_file = Path(workspace) / f".elysia_opencode_task_{uuid.uuid4().hex[:8]}.md"
        task_file.write_text(f"# Task\n\n{task_description}\n\n---\n\n*Auto-generated by Elysia*")

        # Start OpenCode process
        cmd = [
            self._opencode_path,
            "run",
            "--task", str(task_file),
            "--workspace", str(workspace_path),
        ]

        env = os.environ.copy()
        env["OPENCODE_WORKSPACE"] = str(workspace_path)

        process = subprocess.Popen(
            cmd,
            cwd=str(workspace_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
        )

        execution = OpenCodeExecution(
            execution_id=execution_id,
            task=task,
            workspace=workspace,
            process=process,
        )

        with self._lock:
            self._executations[execution_id] = execution

        # Start monitoring thread
        monitor_thread = threading.Thread(
            target=self._monitor_execution,
            args=(execution_id,),
            daemon=True,
        )
        monitor_thread.start()

        return execution_id

    def _monitor_execution(self, execution_id: str) -> None:
        """Monitor an OpenCode execution and capture output."""
        with self._lock:
            execution = self._executations.get(execution_id)
        if not execution or not execution.process:
            return

        try:
            stdout, stderr = execution.process.communicate(timeout=3600)
            execution.output_buffer = stdout.splitlines() if stdout else []
            execution.error_buffer = stderr.splitlines() if stderr else []
            execution.completed_at = time.time()
            execution.status = "completed" if execution.process.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            execution.status = "timeout"
            execution.process.kill()
            stdout, stderr = execution.process.communicate()
            execution.output_buffer = stdout.splitlines() if stdout else []
            execution.error_buffer = stderr.splitlines() if stderr else []
            execution.completed_at = time.time()
        except Exception as e:
            execution.status = "error"
            execution.error_buffer = [str(e)]
            execution.completed_at = time.time()

        with self._lock:
            self._executations[execution_id] = execution

    def send_instruction(self, execution_id: str, instruction: str) -> Dict[str, Any]:
        """Send an instruction to a running OpenCode task."""
        with self._lock:
            execution = self._executations.get(execution_id)
        if not execution or execution.status != "running":
            return {"ok": False, "error": "Execution not found or not running"}

        # OpenCode doesn't support interactive instruction injection via stdin easily
        # This would require a more complex implementation with PTY
        return {"ok": False, "error": "Interactive instruction not supported yet"}

    def observe(self, execution_id: str) -> Dict[str, Any]:
        """Observe the current state of an OpenCode task."""
        with self._lock:
            execution = self._executations.get(execution_id)
        if not execution:
            return {"ok": False, "error": "Execution not found"}

        return {
            "ok": True,
            "execution_id": execution_id,
            "status": execution.status,
            "output": execution.output_buffer[-50:] if execution.output_buffer else [],
            "errors": execution.error_buffer[-10:] if execution.error_buffer else [],
            "duration_ms": (time.time() - execution.started_at) * 1000,
        }

    def cancel(self, execution_id: str) -> bool:
        """Cancel a running OpenCode task."""
        with self._lock:
            execution = self._executations.get(execution_id)
        if not execution or execution.status not in ("running",):
            return False

        if execution.process:
            execution.process.terminate()
            try:
                execution.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                execution.process.kill()
        execution.status = "cancelled"
        execution.completed_at = time.time()
        return True

    def get_status(self, execution_id: str) -> Dict[str, Any]:
        """Get the current status of a task."""
        with self._lock:
            execution = self._executations.get(execution_id)
        if not execution:
            return {"ok": False, "error": "Execution not found"}

        return {
            "ok": True,
            "execution_id": execution_id,
            "status": execution.status,
            "started_at": execution.started_at,
            "completed_at": execution.completed_at,
        }

    def collect_result(self, execution_id: str) -> AgentResult:
        """Collect the final result of a completed task."""
        with self._lock:
            execution = self._executations.get(execution_id)
        if not execution:
            return AgentResult(
                integration=self.name,
                task_id=execution_id,
                status="not_found",
                summary="Execution not found",
            )

        duration_ms = ((execution.completed_at or time.time()) - execution.started_at) * 1000

        # Parse output for files changed, tests, etc.
        files_changed = self._extract_files_changed(execution.output_buffer)
        tests_run = self._extract_tests(execution.output_buffer)

        return AgentResult(
            integration=self.name,
            task_id=execution_id,
            status=execution.status,
            summary="\n".join(execution.output_buffer[-10:]) if execution.output_buffer else "",
            files_changed=files_changed,
            tests_run=tests_run,
            errors=execution.error_buffer[-5:] if execution.error_buffer else [],
            raw_output_reference="\n".join(execution.output_buffer),
            duration_ms=(execution.completed_at - execution.started_at) * 1000 if execution.completed_at else duration_ms,
        )

    def _extract_files_changed(self, output: List[str]) -> List[str]:
        """Extract file paths from output."""
        files = []
        for line in output:
            if "wrote" in line.lower() or "created" in line.lower() or "modified" in line.lower():
                # Try to extract file paths
                parts = line.split()
                for part in parts:
                    if "." in part and "/" in part:
                        files.append(part.strip(".,;:'\""))
        return list(set(files))

    def _extract_tests(self, output: List[str]) -> List[str]:
        """Extract test commands/results from output."""
        tests = []
        for line in output:
            if any(kw in line.lower() for kw in ["test", "pytest", "jest", "cargo test", "go test"]):
                tests.append(line.strip())
        return tests


def _discover_integrations(registry: IntegrationRegistry) -> None:
    """Register OpenCode if available."""
    try:
        agent = OpenCodeAgent()
        if agent.is_available():
            registry.register(agent)
    except Exception:
        pass