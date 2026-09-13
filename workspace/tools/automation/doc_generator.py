#!/usr/bin/env python3
"""
Elysia Documentation Generator - Task 1847
Auto-generate docs from code: API docs, changelogs, README.
"""
import ast
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class DocGenerator:
    def __init__(self, source_dir: str = None, output_dir: str = None):
        self.source_dir = Path(source_dir or ".")
        self.output_dir = Path(output_dir or "docs")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def extract_python_docs(self, filepath: str) -> Dict[str, Any]:
        path = Path(filepath)
        content = path.read_text(errors="ignore")
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return {"error": "Syntax error"}

        module_doc = ast.get_docstring(tree) or ""
        classes = []
        functions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = []
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        doc = ast.get_docstring(item) or ""
                        args = [a.arg for a in item.args.args if a.arg != "self"]
                        methods.append({
                            "name": item.name,
                            "args": args,
                            "doc": doc,
                            "line": item.lineno
                        })
                classes.append({
                    "name": node.name,
                    "doc": ast.get_docstring(node) or "",
                    "methods": methods,
                    "line": node.lineno
                })
            elif isinstance(node, ast.FunctionDef):
                doc = ast.get_docstring(node) or ""
                args = [a.arg for a in node.args.args]
                functions.append({
                    "name": node.name,
                    "args": args,
                    "doc": doc,
                    "line": node.lineno
                })

        return {
            "file": str(path),
            "module_doc": module_doc,
            "classes": classes,
            "functions": functions
        }

    def generate_api_docs(self, directory: str) -> str:
        lines = ["# Elysia API Documentation", f"\nGenerated: {datetime.now().isoformat()}\n"]
        for py_file in Path(directory).rglob("*.py"):
            if ".data" in str(py_file) or "__pycache__" in str(py_file):
                continue
            docs = self.extract_python_docs(str(py_file))
            if "error" in docs:
                continue
            rel = py_file.relative_to(directory)
            lines.append(f"\n## {rel}\n")
            if docs["module_doc"]:
                lines.append(f"{docs['module_doc']}\n")
            for cls in docs["classes"]:
                lines.append(f"### class {cls['name']}\n")
                if cls["doc"]:
                    lines.append(f"{cls['doc']}\n")
                for m in cls["methods"]:
                    args = ", ".join(m["args"])
                    lines.append(f"- **{m['name']}**({args})")
                    if m["doc"]:
                        lines.append(f"  {m['doc']}")
            for func in docs["functions"]:
                args = ", ".join(func["args"])
                lines.append(f"- **{func['name']}**({args})")
                if func["doc"]:
                    lines.append(f"  {func['doc']}")

        output = self.output_dir / "api_docs.md"
        output.write_text("\n".join(lines))
        return str(output)

    def generate_changelog(self, git_dir: str = None) -> str:
        lines = ["# Changelog", f"\nGenerated: {datetime.now().isoformat()}\n"]
        try:
            result = os.popen(f"cd {git_dir or self.source_dir} && git log --oneline -20").read()
            for line in result.strip().split("\n"):
                if line.strip():
                    parts = line.split(" ", 1)
                    if len(parts) == 2:
                        lines.append(f"- `{parts[0][:7]}` {parts[1]}")
        except Exception:
            lines.append("- No git history available")
        output = self.output_dir / "CHANGELOG.md"
        output.write_text("\n".join(lines))
        return str(output)

    def generate_readme(self, directory: str) -> str:
        lines = ["# Elysia Project\n"]
        readme_path = Path(directory) / "README.md"
        if readme_path.exists():
            lines.append(readme_path.read_text()[:500])
        else:
            lines.append("Automated project documentation.\n")

        lines.append("\n## Project Structure\n")
        for item in sorted(Path(directory).iterdir()):
            if item.is_dir() and not item.name.startswith(".") and item.name != "__pycache__":
                lines.append(f"- `{item.name}/`")
            elif item.suffix == ".py":
                lines.append(f"- `{item.name}`")

        output = self.output_dir / "README.md"
        output.write_text("\n".join(lines))
        return str(output)


def main():
    gen = DocGenerator()

    if len(sys.argv) < 2:
        print("Elysia Documentation Generator")
        print("Commands: api-docs <dir>, changelog [dir], readme <dir>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "api-docs" and len(sys.argv) >= 3:
        path = gen.generate_api_docs(sys.argv[2])
        print(f"[+] API docs: {path}")
    elif cmd == "changelog":
        path = gen.generate_changelog(sys.argv[2] if len(sys.argv) > 2 else None)
        print(f"[+] Changelog: {path}")
    elif cmd == "readme" and len(sys.argv) >= 3:
        path = gen.generate_readme(sys.argv[2])
        print(f"[+] README: {path}")


if __name__ == "__main__":
    main()
