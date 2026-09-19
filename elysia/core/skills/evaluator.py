"""Skill Evaluator — test and track skill performance."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, List
from .registry import SkillRegistry, SkillEntry


@dataclass
class SkillTest:
    """A single test case for a skill."""
    name: str
    input: dict
    expected_output: dict = field(default_factory=dict)
    expected_tools: list[str] = field(default_factory=list)
    timeout: int = 60


@dataclass
class EvaluationResult:
    """Result of evaluating a skill."""
    skill_id: str
    passed: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    details: list[dict] = field(default_factory=list)


class SkillEvaluator:
    """Run evaluations for skills and track performance metrics."""

    def __init__(self, registry: SkillRegistry, test_dir: str = None):
        self.registry = registry
        self.test_dir = test_dir or os.path.join(os.getcwd(), "tests", "skills")
        os.makedirs(self.test_dir, exist_ok=True)

    def run_tests(self, skill: SkillEntry, tests: list[SkillTest] = None) -> EvaluationResult:
        """Run evaluation tests for a skill."""
        start = time.time()
        result = EvaluationResult(skill_id=skill.id)

        if tests is None:
            # Look for test file in test_dir
            test_file = os.path.join(self.test_dir, f"{skill.id}.json")
            if os.path.exists(test_file):
                with open(test_file) as f:
                    data = json.load(f)
                tests = [SkillTest(**t) for t in data.get("tests", [])]

        if not tests:
            result.errors.append("No tests found")
            return result

        for test in tests:
            test_start = time.time()
            try:
                # Execute skill (simplified - would integrate with AgentPipeline in reality)
                test_result = self._run_skill_test(skill, test)
                duration = time.time() - test_start

                if test_result.get("ok"):
                    result.passed += 1
                    result.details.append({"test": test.name, "passed": True, "duration": duration})
                else:
                    result.failed += 1
                    result.errors.append(f"{test.name}: {test_result.get('error', 'unknown')}")
                    result.details.append({"test": test.name, "passed": False, "duration": duration,
                                           "error": test_result.get("error")})

            except Exception as e:
                result.failed += 1
                result.errors.append(f"{test.name}: {type(e).__name__}: {e}")

        result.duration_ms = (time.time() - start) * 1000
        # Update registry stats
        self.registry.record_usage(skill.id, result.failed == 0)
        return result

    def _run_skill_test(self, skill: SkillEntry, test: SkillTest) -> dict:
        """Execute a single skill test (placeholder - integrate with AgentPipeline)."""
        # In real implementation, this would invoke the skill via AgentPipeline
        return {"ok": True, "output": f"Executed {skill.name} with {test.input}"}

    def save_test(self, skill_id: str, tests: list[SkillTest]):
        """Persist test suite for a skill."""
        test_file = os.path.join(self.test_dir, f"{skill_id}.json")
        data = {"skill_id": skill_id, "tests": [t.__dict__ for t in tests]}
        with open(test_file, "w") as f:
            json.dump(data, f, indent=2)

    def load_tests(self, skill_id: str) -> list[SkillTest]:
        test_file = os.path.join(self.test_dir, f"{skill_id}.json")
        if not os.path.exists(test_file):
            return []
        with open(test_file) as f:
            data = json.load(f)
        return [SkillTest(**t) for t in data.get("tests", [])]


from datetime import datetime
from typing import Any, Optional, List