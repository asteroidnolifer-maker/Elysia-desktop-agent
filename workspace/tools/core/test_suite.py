#!/usr/bin/env python3
"""
Elysia Test Suite - Task 1223
Unified testing framework for all Elysia modules.
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class TestStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    ERROR = "error"


@dataclass
class TestResult:
    name: str
    status: TestStatus
    duration_ms: float = 0
    message: str = ""
    suite: str = "default"


@dataclass
class TestSuite:
    name: str
    tests: List[Callable] = field(default_factory=list)
    setup: Optional[Callable] = None
    teardown: Optional[Callable] = None

    def add_test(self, func: Callable):
        self.tests.append(func)
        return func


class TestRunner:
    def __init__(self, report_dir: str = None):
        self.report_dir = Path(report_dir or Path(__file__).parent / ".data" / "test_reports")
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.suites: Dict[str, TestSuite] = {}
        self.results: List[TestResult] = []

    def suite(self, name: str) -> TestSuite:
        if name not in self.suites:
            self.suites[name] = TestSuite(name=name)
        return self.suites[name]

    def run_test(self, func: Callable, suite_name: str = "default") -> TestResult:
        name = func.__name__
        start = time.time()
        try:
            func()
            duration = (time.time() - start) * 1000
            return TestResult(name=name, status=TestStatus.PASS,
                              duration_ms=duration, suite=suite_name)
        except AssertionError as e:
            duration = (time.time() - start) * 1000
            return TestResult(name=name, status=TestStatus.FAIL,
                              duration_ms=duration, message=str(e), suite=suite_name)
        except Exception as e:
            duration = (time.time() - start) * 1000
            return TestResult(name=name, status=TestStatus.ERROR,
                              duration_ms=duration, message=f"{type(e).__name__}: {e}",
                              suite=suite_name)

    def run_all(self) -> List[TestResult]:
        self.results = []
        for suite_name, suite in self.suites.items():
            if suite.setup:
                try:
                    suite.setup()
                except Exception:
                    pass
            for test in suite.tests:
                result = self.run_test(test, suite_name)
                self.results.append(result)
                symbol = {"pass": ".", "fail": "F", "error": "E", "skip": "S"}
                print(f"  {symbol[result.status.value]}", end="", flush=True)
            if suite.teardown:
                try:
                    suite.teardown()
                except Exception:
                    pass
        print()
        return self.results

    def summary(self) -> Dict[str, Any]:
        by_status = {}
        for r in self.results:
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
        total_ms = sum(r.duration_ms for r in self.results)
        return {
            "total": len(self.results),
            "by_status": by_status,
            "total_duration_ms": total_ms,
            "pass_rate": by_status.get("pass", 0) / max(len(self.results), 1) * 100
        }

    def save_report(self) -> str:
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": self.summary(),
            "results": [
                {
                    "name": r.name,
                    "status": r.status.value,
                    "suite": r.suite,
                    "duration_ms": r.duration_ms,
                    "message": r.message
                }
                for r in self.results
            ]
        }
        path = self.report_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps(report, indent=2))
        return str(path)


def assert_eq(a, b, msg=""):
    assert a == b, msg or f"Expected {b}, got {a}"

def assert_true(val, msg=""):
    assert val, msg or f"Expected truthy, got {val}"

def assert_false(val, msg=""):
    assert not val, msg or f"Expected falsy, got {val}"

def assert_raises(exc_type, func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except exc_type:
        return
    raise AssertionError(f"Expected {exc_type.__name__} but none raised")


def main():
    runner = TestRunner()

    core = runner.suite("core")
    @core.add_test
    def test_error_handler_import():
        from error_handler import ErrorHandler
        h = ErrorHandler()
        assert_true(h is not None)

    @core.add_test
    def test_logger_import():
        from logger import ElysiaLogger
        l = ElysiaLogger("test")
        assert_true(l is not None)

    @core.add_test
    def test_config_import():
        from config_manager import ConfigManager
        c = ConfigManager()
        assert_true(c.get("version") is not None)

    @core.add_test
    def test_assert_eq():
        assert_eq(1 + 1, 2)

    @core.add_test
    def test_assert_true():
        assert_true(True)

    print("Running tests...")
    results = runner.run_all()
    summary = runner.summary()
    print(f"\nResults: {summary['by_status']}")
    print(f"Pass rate: {summary['pass_rate']:.0f}%")
    path = runner.save_report()
    print(f"Report: {path}")


if __name__ == "__main__":
    main()
