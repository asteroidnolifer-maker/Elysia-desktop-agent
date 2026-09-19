"""Codex Integration — execute coding tasks via Codex CLI."""
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

from .base import ExternalAgent, ExternalAgentCapability, AgentResult


@dataclass
class CodexExecution:
    execution_id: str
    task: Dict[str, Any]
    workspace: str
    process: Optional[subprocess.Popen] = None
    output_buffer: List[str] = field(default_factory=list)
    error_buffer: List[str] = field(default_factory=list)
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


class CodexAgent:
    """Codex CLI integration for autonomous coding tasks."""

    def __init__(self):
        self._executions: Dict[str, CodexExecution] = {}
        self._lock = threading.Lock()
        self._codex_path = self._find_codex()

    @property
    def name(self) -> str:
        return "codex"

    @property
    def capabilities(self) -> List[ExternalAgentCapability]:
        return [
            ExternalAgentCapability.CODING,
            ExternalAgentCapability.REPOSITORY_INSPECTION,
            ExternalAgentCapability.TERMINAL,
            ExternalAgentCapability.FILE_EDIT,
            ExternalAgentCapability.TEST_EXECUTION,
            ExternalAgentCapability.CODE_REVIEW,
        ]

    def _find_codex(self) -> Optional[str]:
        return shutil.which("codex")

    def is_available(self) -> bool:
        return self._codex_path is not None

    def health(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "available": self.is_available(),
            "executable": self._codex_path,
            "status": "healthy" if self.is_available() else "unavailable",
        }

    def inspect(self, workspace: str) -> Dict[str, Any]:
        if not self.is_available():
            return {"ok": False, "error": "Codex not installed"}

        workspace_path = Path(workspace)
        if not workspace_path.exists():
            return {"ok": False, "error": "Workspace does not exist"}

        return {
            "ok": True,
            "workspace": workspace,
            "project_type": "unknown",
            "has_git": (workspace_path / ".git").exists(),
        }

    def start_task(self, task: Dict[str, Any], workspace: str, permissions: List[str]) -> str:
        if not self.is_available():
            raise RuntimeError("Codex not available")

        execution_id = f"codex-{uuid.uuid4().hex[:8]}"
        workspace_path = Path(workspace).resolve()

        task_description = task.get("description", task.get("title", ""))

        # Codex CLI typically works with a task file or stdin
        task_file = Path(workspace) / f".elysia_codex_task_{uuid.uuid4().hex[:8]}.md"
        task_file.write_text(f"# Task\n\n{task_description}\n")

        cmd = [self._codex_path, "exec", "--task", str(task_file), "--workspace", str(workspace)]

        process = subprocess.Popen(
            cmd,
            cwd=str(Path(workspace).resolve()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        execution = CodexExecution(
            execution_id=execution_id,
            task=task,
            workspace=workspace,
            process=process,
        )

        with self._lock:
            self._executions[execution_id] = execution

        monitor_thread = threading.Thread(
            target=self._monitor_execution,
            args=(execution_id,),
            daemon=True,
        )
        monitor_thread.start()

        return execution_id

    def _monitor_execution(self, execution_id: str) -> None:
        with self._lock:
            execution = self._executions.get(execution_id)
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
            self._executions[execution_id] = execution

    def send_instruction(self, execution_id: str, instruction: str) -> Dict[str, Any]:
        return {"ok": False, "error": "Interactive instruction not supported yet"}

    def observe(self, execution_id: str) -> Dict[str, Any]:
        with self._lock:
            execution = self._executions.get(execution_id)
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
        with self._lock:
            execution = self._executions.get(execution_id)
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
        with self._lock:
            execution = self._executions.get(execution_id)
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
        with self._lock:
            execution = self._executions.get(execution_id)
        if not execution:
            return AgentResult(
                integration=self.name,
                task_id=execution_id,
                status="not_found",
                summary="Execution not found",
            )

        duration_ms = ((execution.completed_at or time.time()) - execution.started_at) * 1000
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
            duration_ms=duration_ms,
        )

    def _extract_files_changed(self, output: List[str]) -> List[str]:
        files = set()
        for line in output:
            if any(kw in line.lower() for kw in ["wrote", "created", "modified", "edited"]):
                for part in line.split():
                    if "." in part and "/" in part:
                        files.add(part.strip(".,;:'\""))
        return list(files)

    def _extract_tests(self, output: List[str]) -> List[str]:
        tests = []
        for line in output:
            if any(kw in line.lower() for kw in ["test", "pytest", "jest", "cargo test", "go test"]):
                tests.append(line.strip())
        return tests


import time
from typing import Any, Dict, List, Optional

def _discover_integrations(registry):
    """Register Codex if available."""
    try:
        agent = CodexAgent()
        if agent.is_available():
            registry.register(agent)
    except Exception:
        pass