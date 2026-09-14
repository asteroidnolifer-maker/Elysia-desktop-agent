#!/usr/bin/env python3
"""
Android Voice Commands for Elysia
Voice command processing and routing for Android app.
"""
import json
import re
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime


class VoiceCommandProcessor:
    """Process voice commands from Android app and route to taskboard."""

    def __init__(self, hud_url: str = "http://127.0.0.1:8087"):
        self.hud_url = hud_url
        self.history_path = Path(__file__).parent / "voice_history.json"
        self.history = self._load_history()
        self.hotword = "elysia"
        self.command_patterns = self._build_patterns()

    def _load_history(self) -> List[Dict[str, Any]]:
        if self.history_path.exists():
            return json.loads(self.history_path.read_text())
        return []

    def _save_history(self):
        self.history_path.write_text(json.dumps(self.history[-500:], indent=2))

    def _build_patterns(self) -> List[Dict[str, Any]]:
        return [
            {"pattern": r"(?:add|create|new)\s+(?:task|todo|item)\s*:?\s*(.+)", "action": "add_task", "groups": ["description"]},
            {"pattern": r"(?:mark|set|complete|done)\s+(?:task)?\s*#?(\d+)\s+(?:as\s+)?done", "action": "complete_task", "groups": ["task_id"]},
            {"pattern": r"(?:fail|cancel)\s+(?:task)?\s*#?(\d+)", "action": "fail_task", "groups": ["task_id"]},
            {"pattern": r"(?:claim|take|start)\s+(?:task)?\s*#?(\d+)", "action": "claim_task", "groups": ["task_id"]},
            {"pattern": r"(?:what(?:'s| is| are))?\s*(?:open|available|todo|tasks)", "action": "list_open", "groups": []},
            {"pattern": r"(?:status|how(?:'s| is)|system)", "action": "status", "groups": []},
            {"pattern": r"(?:start|launch|run)\s+(?:the\s+)?pool", "action": "start_pool", "groups": []},
            {"pattern": r"(?:stop|kill|halt)\s+(?:the\s+)?pool", "action": "stop_pool", "groups": []},
            {"pattern": r"(?:show|display|list)\s+(?:done|completed)\s+tasks", "action": "list_done", "groups": []},
            {"pattern": r"(?:show|display)\s+(?:failed|errors?)", "action": "list_failed", "groups": []},
        ]

    def process_command(self, text: str) -> Dict[str, Any]:
        text = text.strip()
        text_lower = text.lower()

        if self.hotword not in text_lower:
            return {"recognized": False, "reason": "hotword_missing", "text": text}

        text_clean = re.sub(r'\belysia\b', '', text_lower, flags=re.IGNORECASE).strip()

        for pattern_def in self.command_patterns:
            match = re.search(pattern_def["pattern"], text_clean, re.IGNORECASE)
            if match:
                groups = match.groups()
                result = {
                    "recognized": True,
                    "action": pattern_def["action"],
                    "text": text,
                    "params": {},
                    "timestamp": datetime.now().isoformat()
                }
                for i, group_name in enumerate(pattern_def["groups"]):
                    if i < len(groups):
                        result["params"][group_name] = groups[i]
                self.history.append(result)
                self._save_history()
                return result

        return {"recognized": True, "action": "general", "text": text, "timestamp": datetime.now().isoformat()}

    def execute_action(self, command_result: Dict[str, Any]) -> Dict[str, Any]:
        action = command_result.get("action", "")
        params = command_result.get("params", {})

        try:
            import urllib.request
            if action == "add_task":
                desc = params.get("description", "Voice task")
                payload = json.dumps({"title": f"Voice: {desc}", "description": f"Created via voice command", "files": [], "priority": 3}).encode()
                req = urllib.request.Request(f"{self.hud_url}/api/task", data=payload, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return {"success": True, "result": json.loads(resp.read())}

            elif action == "complete_task":
                task_id = params.get("task_id")
                return {"success": True, "action": "complete_task", "task_id": task_id}

            elif action == "list_open":
                with urllib.request.urlopen(f"{self.hud_url}/api/tasks?status=open&n=5", timeout=5) as resp:
                    data = json.loads(resp.read())
                    tasks = data.get("tasks", [])
                    return {"success": True, "tasks": [{"id": t["id"], "title": t["title"]} for t in tasks]}

            elif action == "status":
                with urllib.request.urlopen(f"{self.hud_url}/api/state", timeout=5) as resp:
                    return {"success": True, "state": json.loads(resp.read())}

            elif action == "start_pool":
                payload = json.dumps({"action": "start", "cap": 4}).encode()
                req = urllib.request.Request(f"{self.hud_url}/api/pool", data=payload, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return {"success": True, "result": json.loads(resp.read())}

            elif action == "stop_pool":
                payload = json.dumps({"action": "stop"}).encode()
                req = urllib.request.Request(f"{self.hud_url}/api/pool", data=payload, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return {"success": True, "result": json.loads(resp.read())}

            else:
                return {"success": False, "error": f"Unknown action: {action}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.history[-limit:]

    def set_hotword(self, hotword: str):
        self.hotword = hotword.lower()


class VoiceResponseGenerator:
    """Generate natural language responses for voice commands."""

    RESPONSES = {
        "add_task": "Task added: {description}",
        "complete_task": "Task {task_id} marked as done",
        "fail_task": "Task {task_id} marked as failed",
        "claim_task": "Task {task_id} claimed",
        "list_open": "You have {count} open tasks",
        "status": "System is {status}. {open} open tasks, {done} done.",
        "start_pool": "Worker pool started",
        "stop_pool": "Worker pool stopped",
        "general": "I didn't understand that command",
        "error": "Error: {error}"
    }

    @classmethod
    def generate(cls, command_result: Dict[str, Any]) -> str:
        action = command_result.get("action", "general")
        template = cls.RESPONSES.get(action, "Unknown action")
        try:
            return template.format(**command_result.get("params", {}), **command_result)
        except (KeyError, IndexError):
            return template


def main():
    import sys
    processor = VoiceCommandProcessor()

    if len(sys.argv) < 2:
        print("Voice Command Processor")
        print("=" * 40)
        print("\nCommands:")
        print("  process <text>  - Process voice command")
        print("  history         - Command history")
        print("  hotword <word>  - Set hotword")
        print("\nExample: python voice_commands.py process 'Elysia add task: fix login bug'")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "process" and len(sys.argv) >= 3:
        text = " ".join(sys.argv[2:])
        result = processor.process_command(text)
        print(f"Recognized: {result['recognized']}")
        print(f"Action: {result.get('action', 'none')}")
        print(f"Params: {result.get('params', {})}")
        response = VoiceResponseGenerator.generate(result)
        print(f"Response: {response}")

    elif cmd == "history":
        for h in processor.get_history():
            print(f"  [{h['timestamp'][:19]}] {h['action']}: {h['text'][:60]}")

    elif cmd == "hotword" and len(sys.argv) >= 3:
        processor.set_hotword(sys.argv[2])
        print(f"Hotword set to: {sys.argv[2]}")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
