#!/usr/bin/env python3
"""
Elysia Code Quality Automation - Task 1843
Linting, formatting, complexity analysis, and quality scoring.
"""
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


class CodeQualityAnalyzer:
    def __init__(self):
        self.results: Dict[str, Any] = {}

    def analyze_file(self, filepath: str) -> Dict[str, Any]:
        path = Path(filepath)
        if not path.exists():
            return {"error": f"File not found: {filepath}"}

        content = path.read_text(errors="ignore")
        lines = content.split("\n")
        issues = []

        for i, line in enumerate(lines, 1):
            if len(line) > 120:
                issues.append({"line": i, "severity": "warning",
                              "message": f"Line too long ({len(line)} > 120)"})
            if line.rstrip() != line and line.strip():
                issues.append({"line": i, "severity": "info",
                              "message": "Trailing whitespace"})
            if "\t" in line:
                issues.append({"line": i, "severity": "info",
                              "message": "Tab character used"})

        if path.suffix == ".py":
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        func_lines = (node.end_lineno or node.lineno) - node.lineno
                        if func_lines > 50:
                            issues.append({
                                "line": node.lineno, "severity": "warning",
                                "message": f"Function '{node.name}' too long ({func_lines} lines)"
                            })
                        if len(node.args.args) > 5:
                            issues.append({
                                "line": node.lineno, "severity": "warning",
                                "message": f"Function '{node.name}' has too many parameters"
                            })
                    if isinstance(node, ast.ClassDef):
                        method_count = sum(1 for n in ast.walk(node)
                                          if isinstance(n, ast.FunctionDef))
                        if method_count > 20:
                            issues.append({
                                "line": node.lineno, "severity": "warning",
                                "message": f"Class '{node.name}' has {method_count} methods (God class)"
                            })
            except SyntaxError as e:
                issues.append({"line": e.lineno or 1, "severity": "error",
                              "message": f"Syntax error: {e.msg}"})

        blank_lines = sum(1 for l in lines if not l.strip())
        comment_lines = sum(1 for l in lines if l.strip().startswith("#"))
        total = len(lines)

        return {
            "file": filepath,
            "total_lines": total,
            "blank_lines": blank_lines,
            "comment_lines": comment_lines,
            "code_lines": total - blank_lines - comment_lines,
            "issues": issues,
            "quality_score": max(0, 100 - len(issues) * 5)
        }

    def analyze_directory(self, directory: str) -> Dict[str, Any]:
        results = []
        for ext in ["*.py", "*.js", "*.ts"]:
            for path in Path(directory).rglob(ext):
                if ".data" not in str(path) and "__pycache__" not in str(path):
                    results.append(self.analyze_file(str(path)))

        total_issues = sum(len(r.get("issues", [])) for r in results)
        avg_score = (sum(r.get("quality_score", 0) for r in results) /
                     max(len(results), 1))

        return {
            "files_analyzed": len(results),
            "total_issues": total_issues,
            "average_quality_score": round(avg_score, 1),
            "by_severity": self._count_by_severity(results),
            "files": results
        }

    def _count_by_severity(self, results: List[Dict]) -> Dict[str, int]:
        counts = {}
        for r in results:
            for issue in r.get("issues", []):
                sev = issue.get("severity", "unknown")
                counts[sev] = counts.get(sev, 0) + 1
        return counts

    def format_report(self, result: Dict[str, Any]) -> str:
        lines = [
            "=" * 50,
            "CODE QUALITY REPORT",
            f"Files: {result.get('files_analyzed', 0)}",
            f"Issues: {result.get('total_issues', 0)}",
            f"Quality Score: {result.get('average_quality_score', 0)}/100",
            "=" * 50, ""
        ]
        for r in result.get("files", []):
            if r.get("issues"):
                lines.append(f"{r['file']} ({r['quality_score']}/100):")
                for issue in r["issues"]:
                    lines.append(f"  L{issue['line']}: [{issue['severity']}] {issue['message']}")
                lines.append("")
        return "\n".join(lines)


def main():
    analyzer = CodeQualityAnalyzer()

    if len(sys.argv) < 2:
        print("Elysia Code Quality")
        print("Commands: analyze <file>, scan <directory>, report <directory>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "analyze" and len(sys.argv) >= 3:
        result = analyzer.analyze_file(sys.argv[2])
        print(json.dumps(result, indent=2))
    elif cmd in ("scan", "report") and len(sys.argv) >= 3:
        result = analyzer.analyze_directory(sys.argv[2])
        print(analyzer.format_report(result))


if __name__ == "__main__":
    main()
