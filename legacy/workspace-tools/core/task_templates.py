#!/usr/bin/env python3
"""
Elysia Task Templates - Task 1235
Reusable task templates with variable substitution.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


TEMPLATES_DIR = Path(__file__).parent / ".data" / "templates"

BUILTIN_TEMPLATES = {
    "bug_fix": {
        "title": "Fix: {component} - {description}",
        "description": "Resolve issue in {component}.\n\n"
                       "Steps:\n1. Reproduce the issue\n2. Identify root cause\n"
                       "3. Implement fix\n4. Test fix\n5. Update docs if needed",
        "files": ["workspace/{component}.py"],
        "priority": 4,
        "tags": ["bug", "{component}"]
    },
    "feature": {
        "title": "Feature: {name}",
        "description": "Implement {name}.\n\n"
                       "Requirements:\n{requirements}\n\n"
                       "Acceptance Criteria:\n{criteria}",
        "files": ["workspace/{name}.py", "workspace/tests/test_{name}.py"],
        "priority": 3,
        "tags": ["feature", "{name}"]
    },
    "tool_integration": {
        "title": "Integration: {service_name} - {action}",
        "description": "Create {service_name} integration for: {action}\n\n"
                       "API endpoint: {endpoint}\nAuth type: {auth_type}",
        "files": ["workspace/tools/{category}/{service_name}.py"],
        "priority": 4,
        "tags": ["integration", "{service_name}"]
    },
    "documentation": {
        "title": "Docs: {topic}",
        "description": "Write documentation for {topic}.\n\n"
                       "Sections:\n{sections}",
        "files": ["workspace/docs/{topic}.md"],
        "priority": 3,
        "tags": ["docs", "{topic}"]
    },
    "test": {
        "title": "Test: {module}",
        "description": "Write tests for {module}.\n\n"
                       "Cover: {coverage_areas}",
        "files": ["workspace/tests/test_{module}.py"],
        "priority": 3,
        "tags": ["testing", "{module}"]
    },
    "security_audit": {
        "title": "Security Audit: {target}",
        "description": "Perform security audit on {target}.\n\n"
                       "Check for:\n- Input validation\n- SQL injection\n"
                       "- XSS\n- Authentication bypass\n- Data exposure",
        "files": [],
        "priority": 5,
        "tags": ["security", "{target}"]
    },
    "performance": {
        "title": "Performance: {target} optimization",
        "description": "Optimize {target} for better performance.\n\n"
                       "Current metrics:\n{current_metrics}\n\n"
                       "Target: {target_metrics}",
        "files": [],
        "priority": 4,
        "tags": ["performance", "{target}"]
    },
    "devops": {
        "title": "DevOps: {action} - {target}",
        "description": "Automate {action} for {target}.\n\n"
                       "Environment: {environment}\nConfig: {config}",
        "files": [],
        "priority": 4,
        "tags": ["devops", "{target}"]
    }
}


class TemplateManager:
    def __init__(self, templates_dir: str = None):
        self.templates_dir = Path(templates_dir or TEMPLATES_DIR)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.templates = BUILTIN_TEMPLATES.copy()
        self._load_custom()

    def _load_custom(self):
        for f in self.templates_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                name = f.stem
                self.templates[name] = data
            except Exception:
                pass

    def list_templates(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": name,
                "title_pattern": t.get("title", ""),
                "priority": t.get("priority", 3),
                "tags": t.get("tags", [])
            }
            for name, t in self.templates.items()
        ]

    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        return self.templates.get(name)

    def create_task(self, template_name: str, variables: Dict[str, str]) -> Dict[str, Any]:
        template = self.templates.get(template_name)
        if not template:
            return {"error": f"Template '{template_name}' not found"}

        task = {}
        for key, value in template.items():
            if isinstance(value, str):
                for var, val in variables.items():
                    value = value.replace(f"{{{var}}}", val)
                task[key] = value
            elif isinstance(value, list):
                task[key] = [
                    item.format(**variables) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                task[key] = value

        task["created_at"] = datetime.now().isoformat()
        task["template"] = template_name
        return task

    def save_template(self, name: str, template: Dict[str, Any]):
        self.templates[name] = template
        path = self.templates_dir / f"{name}.json"
        path.write_text(json.dumps(template, indent=2))
        print(f"[+] Saved template: {name}")

    def delete_template(self, name: str) -> bool:
        if name in BUILTIN_TEMPLATES:
            print(f"[-] Cannot delete built-in template: {name}")
            return False
        if name in self.templates:
            del self.templates[name]
            path = self.templates_dir / f"{name}.json"
            if path.exists():
                path.unlink()
            return True
        return False

    def preview(self, template_name: str, variables: Dict[str, str]) -> str:
        task = self.create_task(template_name, variables)
        lines = [
            f"Title: {task.get('title', '')}",
            f"Priority: {task.get('priority', 3)}",
            f"Files: {', '.join(task.get('files', []))}",
            f"Tags: {', '.join(task.get('tags', []))}",
            f"\nDescription:",
            task.get("description", "")
        ]
        return "\n".join(lines)


def main():
    manager = TemplateManager()

    if len(sys.argv) < 2:
        print("Elysia Task Templates")
        print("Commands: list, preview <template> [vars], create <name> [vars], save <name>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "list":
        templates = manager.list_templates()
        for t in templates:
            print(f"  {t['name']}: {t['title_pattern']} (p{t['priority']})")
    elif cmd == "preview" and len(sys.argv) >= 3:
        template = sys.argv[2]
        variables = {}
        for arg in sys.argv[3:]:
            if "=" in arg:
                k, v = arg.split("=", 1)
                variables[k] = v
        print(manager.preview(template, variables))
    elif cmd == "create" and len(sys.argv) >= 3:
        template = sys.argv[2]
        variables = {}
        for arg in sys.argv[3:]:
            if "=" in arg:
                k, v = arg.split("=", 1)
                variables[k] = v
        task = manager.create_task(template, variables)
        print(json.dumps(task, indent=2))


if __name__ == "__main__":
    main()
