#!/usr/bin/env python3
"""
Elysia Workflow Engine - Task 1236
Step-based workflow automation with conditions, parallelism, and state tracking.
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from enum import Enum


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Step:
    def __init__(self, name: str, action: str, params: Dict[str, Any] = None,
                 depends_on: List[str] = None, condition: str = None):
        self.name = name
        self.action = action
        self.params = params or {}
        self.depends_on = depends_on or []
        self.condition = condition
        self.status = StepStatus.PENDING
        self.result = None
        self.error = None
        self.started_at = None
        self.completed_at = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "action": self.action,
            "params": self.params,
            "depends_on": self.depends_on,
            "condition": self.condition,
            "status": self.status.value,
            "result": self.result,
            "error": self.error
        }


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.steps: List[Step] = []
        self.status = WorkflowStatus.IDLE
        self.context: Dict[str, Any] = {}
        self.created_at = datetime.now().isoformat()
        self.started_at = None
        self.completed_at = None

    def add_step(self, name: str, action: str, params: Dict[str, Any] = None,
                 depends_on: List[str] = None, condition: str = None) -> Step:
        step = Step(name, action, params, depends_on, condition)
        self.steps.append(step)
        return step

    def get_step(self, name: str) -> Optional[Step]:
        for s in self.steps:
            if s.name == name:
                return s
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "context": self.context,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at
        }


class WorkflowEngine:
    def __init__(self, workflows_dir: str = None):
        self.workflows_dir = Path(workflows_dir or Path(__file__).parent / ".data" / "workflows")
        self.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.workflows: Dict[str, Workflow] = {}
        self.handlers: Dict[str, Callable] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register_handler("log", lambda params, ctx: print(f"[LOG] {params.get('message', '')}"))
        self.register_handler("set_var", lambda params, ctx: ctx.update({params["key"]: params["value"]}))
        self.register_handler("delay", lambda params, ctx: time.sleep(params.get("seconds", 1)))
        self.register_handler("shell", lambda params, ctx: self._run_shell(params.get("command", "")))

    def _run_shell(self, cmd: str):
        import subprocess
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return {"stdout": result.stdout, "stderr": result.stderr, "code": result.returncode}

    def register_handler(self, action: str, handler: Callable):
        self.handlers[action] = handler

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        wf = Workflow(name, description)
        self.workflows[name] = wf
        return wf

    def _check_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        if not condition:
            return True
        try:
            return bool(eval(condition, {"__builtins__": {}}, context))
        except Exception:
            return False

    def run_workflow(self, name: str) -> Dict[str, Any]:
        wf = self.workflows.get(name)
        if not wf:
            return {"error": f"Workflow '{name}' not found"}

        wf.status = WorkflowStatus.RUNNING
        wf.started_at = datetime.now().isoformat()

        completed = set()
        max_iterations = len(wf.steps) * 2
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            all_done = True

            for step in wf.steps:
                if step.status in (StepStatus.DONE, StepStatus.SKIPPED):
                    if step.name not in completed:
                        completed.add(step.name)
                    continue

                all_done = False

                deps_met = all(d in completed for d in step.depends_on)
                if not deps_met:
                    continue

                if not self._check_condition(step.condition, wf.context):
                    step.status = StepStatus.SKIPPED
                    completed.add(step.name)
                    continue

                if step.status == StepStatus.RUNNING:
                    continue

                step.status = StepStatus.RUNNING
                step.started_at = datetime.now().isoformat()

                handler = self.handlers.get(step.action)
                if not handler:
                    step.status = StepStatus.FAILED
                    step.error = f"No handler for action: {step.action}"
                    wf.status = WorkflowStatus.FAILED
                    break

                try:
                    step.result = handler(step.params, wf.context)
                    step.status = StepStatus.DONE
                    step.completed_at = datetime.now().isoformat()
                    completed.add(step.name)
                except Exception as e:
                    step.status = StepStatus.FAILED
                    step.error = str(e)
                    wf.status = WorkflowStatus.FAILED
                    break

            if all_done or wf.status == WorkflowStatus.FAILED:
                break

        if wf.status == WorkflowStatus.RUNNING:
            wf.status = WorkflowStatus.COMPLETED

        wf.completed_at = datetime.now().isoformat()
        return wf.to_dict()

    def save_workflow(self, name: str):
        wf = self.workflows.get(name)
        if wf:
            path = self.workflows_dir / f"{name}.json"
            path.write_text(json.dumps(wf.to_dict(), indent=2))

    def load_workflow(self, name: str) -> bool:
        path = self.workflows_dir / f"{name}.json"
        if not path.exists():
            return False
        data = json.loads(path.read_text())
        wf = Workflow(data["name"], data.get("description", ""))
        for sd in data.get("steps", []):
            wf.add_step(sd["name"], sd["action"], sd.get("params"),
                        sd.get("depends_on"), sd.get("condition"))
        self.workflows[name] = wf
        return True

    def list_workflows(self) -> List[Dict[str, Any]]:
        return [
            {"name": wf.name, "steps": len(wf.steps), "status": wf.status.value}
            for wf in self.workflows.values()
        ]


def main():
    engine = WorkflowEngine()

    if len(sys.argv) < 2:
        print("Elysia Workflow Engine")
        print("Commands: list, create, run <name>, save <name>, load <name>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "list":
        wfs = engine.list_workflows()
        for wf in wfs:
            print(f"  {wf['name']}: {wf['steps']} steps [{wf['status']}]")
    elif cmd == "run" and len(sys.argv) >= 3:
        engine.load_workflow(sys.argv[2])
        result = engine.run_workflow(sys.argv[2])
        print(json.dumps(result, indent=2))
    elif cmd == "demo":
        wf = engine.create_workflow("demo", "Demo workflow")
        wf.add_step("start", "log", {"message": "Workflow started"})
        wf.add_step("set_name", "set_var", {"key": "name", "value": "Elysia"})
        wf.add_step("greet", "log", {"message": "Hello {name}"}, depends_on=["set_name"])
        wf.add_step("end", "log", {"message": "Workflow complete"}, depends_on=["greet"])
        result = engine.run_workflow("demo")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
