#!/usr/bin/env python3
"""
Elysia Test Suite Automation - Task 1839
Auto-discovery, parallel execution, and result aggregation.
"""
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed


class TestResult:
    def __init__(self, name: str, status: str, duration_ms: float = 0,
                 message: str = "", suite: str = ""):
        self.name = name
        self.status = status
        self.duration_ms = duration_ms
        self.message = message
        self.suite = suite

    def to_dict(self):
        return {
            "name": self.name, "status": self.status,
            "duration_ms": self.duration_ms, "message": self.message,
            "suite": self.suite
        }


class TestSuiteRunner:
    def __init__(self, test_dir: str = None, report_dir: str = None):
        self.test_dir = Path(test_dir or Path(__file__).parent.parent.parent / "tests")
        self.report_dir = Path(report_dir or Path(__file__).parent / ".data" / "test_reports")
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.results: List[TestResult] = []

    def discover_tests(self) -> List[str]:
        tests = []
        if self.test_dir.exists():
            for f in self.test_dir.rglob("test_*.py"):
                tests.append(str(f))
            for f in self.test_dir.rglob("*_test.py"):
                tests.append(str(f))
        return list(set(tests))

    def run_file(self, filepath: str) -> List[TestResult]:
        results = []
        start = time.time()
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("test_module", filepath)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for name in dir(module):
                if name.startswith("test_"):
                    func = getattr(module, name)
                    if callable(func):
                        t0 = time.time()
                        try:
                            func()
                            results.append(TestResult(name, "pass",
                                                      (time.time() - t0) * 1000,
                                                      suite=filepath))
                        except AssertionError as e:
                            results.append(TestResult(name, "fail",
                                                      (time.time() - t0) * 1000,
                                                      str(e), filepath))
                        except Exception as e:
                            results.append(TestResult(name, "error",
                                                      (time.time() - t0) * 1000,
                                                      str(e), filepath))
        except Exception as e:
            results.append(TestResult(filepath, "error", 0, str(e)))
        return results

    def run_all(self, parallel: bool = True, max_workers: int = 4) -> List[TestResult]:
        test_files = self.discover_tests()
        self.results = []

        if parallel and len(test_files) > 1:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self.run_file, f): f for f in test_files}
                for future in as_completed(futures):
                    self.results.extend(future.result())
        else:
            for f in test_files:
                self.results.extend(self.run_file(f))

        return self.results

    def summary(self) -> Dict[str, Any]:
        by_status = {}
        for r in self.results:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        total_ms = sum(r.duration_ms for r in self.results)
        passed = by_status.get("pass", 0)
        total = len(self.results)
        return {
            "total": total,
            "passed": passed,
            "failed": by_status.get("fail", 0),
            "errors": by_status.get("error", 0),
            "pass_rate": (passed / total * 100) if total > 0 else 0,
            "total_duration_ms": total_ms
        }

    def save_report(self) -> str:
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": self.summary(),
            "results": [r.to_dict() for r in self.results]
        }
        path = self.report_dir / f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps(report, indent=2))
        return str(path)

    def print_results(self):
        for r in self.results:
            symbol = {"pass": ".", "fail": "F", "error": "E"}
            print(f"  {symbol.get(r.status, '?')} {r.name} ({r.duration_ms:.0f}ms)")
            if r.message:
                print(f"    {r.message[:100]}")


def main():
    runner = TestSuiteRunner()

    if len(sys.argv) < 2:
        print("Elysia Test Suite Automation")
        print("Commands: discover, run, run-file <path>, summary")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "discover":
        tests = runner.discover_tests()
        print(f"Found {len(tests)} test files:")
        for t in tests:
            print(f"  {t}")
    elif cmd == "run":
        runner.run_all()
        runner.print_results()
        s = runner.summary()
        print(f"\n{s['passed']}/{s['total']} passed ({s['pass_rate']:.0f}%)")
        path = runner.save_report()
        print(f"Report: {path}")
    elif cmd == "run-file" and len(sys.argv) >= 3:
        results = runner.run_file(sys.argv[2])
        for r in results:
            print(f"  {'.' if r.status == 'pass' else 'F'} {r.name}")
        print(f"\n{len([r for r in results if r.status == 'pass'])}/{len(results)} passed")
    elif cmd == "summary":
        runner.run_all()
        print(json.dumps(runner.summary(), indent=2))


if __name__ == "__main__":
    main()
