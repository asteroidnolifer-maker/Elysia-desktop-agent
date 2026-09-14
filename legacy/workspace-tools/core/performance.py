#!/usr/bin/env python3
"""
Elysia Performance Optimizer - Tasks 1212-1214
CPU/memory profiling, bottleneck detection, optimization recommendations.
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class PerformanceProfiler:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "perf")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.profiles: List[Dict[str, Any]] = []

    def time_function(self, func, *args, **kwargs) -> Dict[str, Any]:
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            entry = {
                "function": func.__name__,
                "duration_ms": elapsed * 1000,
                "status": "success",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            elapsed = time.perf_counter() - start
            entry = {
                "function": func.__name__,
                "duration_ms": elapsed * 1000,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
        self.profiles.append(entry)
        return entry

    def profile_directory(self, directory: str) -> Dict[str, Any]:
        py_files = list(Path(directory).rglob("*.py"))
        results = {"files": 0, "total_lines": 0, "slow_files": [], "large_files": []}
        for f in py_files:
            if ".data" in str(f) or "__pycache__" in str(f):
                continue
            try:
                content = f.read_text(errors="ignore")
                lines = content.count("\n") + 1
                results["files"] += 1
                results["total_lines"] += lines
                if lines > 500:
                    results["large_files"].append({"file": str(f), "lines": lines})
            except Exception:
                pass
        return results

    def analyze_memory_patterns(self, directory: str) -> Dict[str, Any]:
        issues = []
        for py_file in Path(directory).rglob("*.py"):
            if ".data" in str(py_file) or "__pycache__" in str(py_file):
                continue
            try:
                content = py_file.read_text(errors="ignore")
                if "global " in content and "=" in content:
                    issues.append({"file": str(py_file), "issue": "global state usage"})
                if "eval(" in content:
                    issues.append({"file": str(py_file), "issue": "eval() usage (security/perf)"})
                if content.count("import ") > 20:
                    issues.append({"file": str(py_file), "issue": "excessive imports"})
            except Exception:
                pass
        return {"issues": issues, "total_checked": len(list(Path(directory).rglob("*.py")))}

    def suggest_optimizations(self, results: Dict[str, Any]) -> List[str]:
        suggestions = []
        if results.get("large_files"):
            suggestions.append(f"Split {len(results['large_files'])} large files (>500 lines)")
        for f in results.get("large_files", []):
            if f["lines"] > 1000:
                suggestions.append(f"CRITICAL: {f['file']} has {f['lines']} lines - split immediately")
        return suggestions

    def save_report(self, results: Dict[str, Any]) -> str:
        path = self.data_dir / f"perf_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps(results, indent=2))
        return str(path)


def main():
    profiler = PerformanceProfiler()
    if len(sys.argv) < 2:
        print("Elysia Performance Profiler")
        print("Commands: profile <dir>, memory <dir>")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "profile" and len(sys.argv) >= 3:
        results = profiler.profile_directory(sys.argv[2])
        suggestions = profiler.suggest_optimizations(results)
        print(f"Files: {results['files']}, Lines: {results['total_lines']}")
        print(f"Large files: {len(results['large_files'])}")
        for s in suggestions:
            print(f"  -> {s}")
    elif cmd == "memory" and len(sys.argv) >= 3:
        results = profiler.analyze_memory_patterns(sys.argv[2])
        print(f"Issues found: {len(results['issues'])}")
        for issue in results["issues"]:
            print(f"  {issue['file']}: {issue['issue']}")


if __name__ == "__main__":
    main()
