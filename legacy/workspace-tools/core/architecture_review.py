#!/usr/bin/env python3
"""
Elysia Architecture Review - Task 1201
System architecture analysis, dependency mapping, and optimization recommendations.
"""
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List


class ArchitectureAnalyzer:
    def __init__(self, root_dir: str = None):
        self.root = Path(root_dir or ".")
        self.modules: Dict[str, Dict[str, Any]] = {}
        self.dependencies: Dict[str, List[str]] = {}
        self.issues: List[Dict[str, Any]] = []

    def analyze_module(self, filepath: str) -> Dict[str, Any]:
        path = Path(filepath)
        try:
            content = path.read_text(errors="ignore")
            tree = ast.parse(content)
        except (SyntaxError, Exception):
            return {"file": str(path), "error": "parse_failed"}

        imports = []
        classes = []
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
            elif isinstance(node, ast.ClassDef):
                methods = [n.name for n in node.body if isinstance(n, ast.FunctionDef)]
                classes.append({"name": node.name, "methods": methods, "line": node.lineno})
            elif isinstance(node, ast.FunctionDef):
                functions.append({"name": node.name, "line": node.lineno,
                                  "args": len(node.args.args)})

        lines = content.count("\n") + 1
        return {
            "file": str(path.relative_to(self.root)),
            "lines": lines,
            "imports": imports,
            "classes": classes,
            "functions": functions,
            "complexity": len(functions) + len(classes) * 2
        }

    def analyze_directory(self, directory: str = None):
        d = Path(directory or self.root)
        for ext in ["*.py"]:
            for path in d.rglob(ext):
                if ".data" in str(path) or "__pycache__" in str(path):
                    continue
                result = self.analyze_module(str(path))
                self.modules[result["file"]] = result

    def detect_cycles(self) -> List[List[str]]:
        cycles = []
        visited = set()
        def dfs(node, path):
            if node in path:
                cycle = path[path.index(node):]
                cycles.append(cycle)
                return
            if node in visited:
                return
            visited.add(node)
            for dep in self.dependencies.get(node, []):
                dfs(dep, path + [node])
        for mod in self.modules:
            dfs(mod, [])
        return cycles

    def find_large_files(self, threshold: int = 500) -> List[Dict[str, Any]]:
        large = []
        for name, data in self.modules.items():
            if data.get("lines", 0) > threshold:
                large.append({"file": name, "lines": data["lines"]})
        return sorted(large, key=lambda x: x["lines"], reverse=True)

    def find_god_classes(self, threshold: int = 10) -> List[Dict[str, Any]]:
        gods = []
        for name, data in self.modules.items():
            for cls in data.get("classes", []):
                if len(cls.get("methods", [])) > threshold:
                    gods.append({"file": name, "class": cls["name"],
                                "methods": len(cls["methods"])})
        return gods

    def generate_report(self) -> str:
        lines = ["=" * 50, "ARCHITECTURE REVIEW", "=" * 50, ""]
        lines.append(f"Total modules: {len(self.modules)}")
        total_lines = sum(m.get("lines", 0) for m in self.modules.values())
        total_classes = sum(len(m.get("classes", [])) for m in self.modules.values())
        total_funcs = sum(len(m.get("functions", [])) for m in self.modules.values())
        lines.append(f"Total lines: {total_lines}")
        lines.append(f"Total classes: {total_classes}")
        lines.append(f"Total functions: {total_funcs}")
        lines.append("")

        large = self.find_large_files()
        if large:
            lines.append("Large files (>500 lines):")
            for f in large[:10]:
                lines.append(f"  {f['file']}: {f['lines']} lines")
            lines.append("")

        gods = self.find_god_classes()
        if gods:
            lines.append("God classes (>10 methods):")
            for g in gods:
                lines.append(f"  {g['class']} in {g['file']}: {g['methods']} methods")

        return "\n".join(lines)


def main():
    analyzer = ArchitectureAnalyzer(sys.argv[1] if len(sys.argv) > 1 else ".")
    if len(sys.argv) < 2:
        print("Elysia Architecture Review")
        print("Commands: analyze <dir>, report <dir>")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "analyze" and len(sys.argv) >= 3:
        analyzer.analyze_directory(sys.argv[2])
        print(analyzer.generate_report())
    elif cmd == "report" and len(sys.argv) >= 3:
        analyzer.analyze_directory(sys.argv[2])
        print(analyzer.generate_report())


if __name__ == "__main__":
    main()
