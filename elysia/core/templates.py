"""Task templates: parameterised repeatable plans for common work types.

Templates are assembled into task graphs (dependencies included) when the user
asks for a well-understood kind of work. This keeps the planner focused on
genuinely novel requests and improves consistency.
"""
from __future__ import annotations

import hashlib
import json

# Each template: description + ordered steps (may create multiple tasks).
TEMPLATES: dict[str, dict] = {
    "feature": {
        "description": "Implement a new feature end to end.",
        "steps": [
            {"role": "planner", "title": "Plan {title}",
             "detail": "Break down {title}, identify affected files."},
            {"role": "implementer", "title": "Implement {title}",
             "detail": "Write the code for {title}."},
            {"role": "tester", "title": "Test {title}",
             "detail": "Add/run tests covering {title}."},
            {"role": "code_reviewer", "title": "Review {title}",
             "detail": "Review the {title} implementation and tests."},
        ],
        "depends": "linear",
    },
    "bugfix": {
        "description": "Reproduce, diagnose, and fix a bug.",
        "steps": [
            {"role": "debugger", "title": "Reproduce the bug: {title}",
             "detail": "Find and reproduce the bug described as {title}."},
            {"role": "implementer", "title": "Fix the bug: {title}",
             "detail": "Apply the minimal fix for {title}."},
            {"role": "tester", "title": "Verify the fix: {title}",
             "detail": "Confirm {title} is fixed and no regressions."},
        ],
        "depends": "linear",
    },
    "research": {
        "description": "Conduct a research brief and write it up.",
        "steps": [
            {"role": "research_agent", "title": "Research {title}",
             "detail": "Investigate {title} with sources and citations."},
            {"role": "documentation_agent", "title": "Write up {title}",
             "detail": "Turn the research into a structured report on {title}."},
        ],
        "depends": "linear",
    },
    "documentation": {
        "description": "Write or update documentation.",
        "steps": [
            {"role": "documentation_agent", "title": "Document {title}",
             "detail": "Create/update docs for {title}."},
            {"role": "code_reviewer", "title": "Review docs {title}",
             "detail": "Check the {title} docs for accuracy."},
        ],
        "depends": "linear",
    },
    "cleanup": {
        "description": "Remove obsolete/duplicate code and stale artifacts.",
        "steps": [
            {"role": "implementer", "title": "Clean up {title}",
             "detail": "Remove / simplify code for {title}."},
            {"role": "tester", "title": "Verify after cleanup: {title}",
             "detail": "Run the test suite to confirm {title} cleanup is safe."},
        ],
        "depends": "linear",
    },
}


def list_templates() -> list[dict]:
    return [{"name": k, "description": v["description"],
             "steps": len(v["steps"]), "depends": v["depends"]}
            for k, v in TEMPLATES.items()]


def expand_template(name: str, title: str, store=None, add_task=None,
                    **kw) -> list[int]:
    """Expand a template into tasks on the store.

    Either pass a TaskStore (``store``) or a task-creating callable
    ``add_task(title, description, agent_role, dependencies, ...)``.
    """
    tpl = TEMPLATES.get(name)
    if not tpl:
        raise ValueError(f"unknown template {name} (have {sorted(TEMPLATES)})")
    ids: list[int] = []
    for i, step in enumerate(tpl["steps"]):
        step_title = step["title"].format(title=title)
        deps = (ids[-1:] if tpl["depends"] == "linear" else []) or (
            ids[0:i] if tpl["depends"] == "parallel" and i else [])
        params = {
            "title": step_title,
            "description": step["detail"].format(title=title),
            "owned_files": kw.get("owned_files", []),
            "priority": kw.get("priority", 5),
            "agent_role": step["role"],
            "workflow": name,
            "dependencies": deps,
        }
        if store is not None:
            ids.append(store.add_task(**params))
        elif add_task is not None:
            ids.append(add_task(**params))
    return ids


def dedup_hash(title: str, description: str = "", files=None) -> str:
    blob = json.dumps({"title": title, "description": description,
                       "files": files or []}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]