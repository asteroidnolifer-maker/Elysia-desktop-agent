#!/usr/bin/env python3
"""
Wear OS Companion for Elysia
Watch face data and sync for Wear OS devices.
"""
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime


class WearOSCompanion:
    """Wear OS companion app data provider."""

    def __init__(self, hud_url: str = "http://127.0.0.1:8087"):
        self.hud_url = hud_url
        self.watch_data_path = Path(__file__).parent / "watch_data.json"
        self.watchface_config_path = Path(__file__).parent / "watchface_config.json"

    def get_watchface_data(self) -> Dict[str, Any]:
        try:
            import urllib.request
            with urllib.request.urlopen(f"{self.hud_url}/api/state", timeout=5) as resp:
                state = json.loads(resp.read())

            counts = state.get("counts", {})
            return {
                "open_count": counts.get("open", 0),
                "done_count": counts.get("done", 0),
                "failed_count": counts.get("failed", 0),
                "health_ok": state.get("health", {}).get("model", False),
                "last_update": datetime.now().isoformat(),
                "complications": [
                    {"type": "short_text", "text": f"{counts.get('open', 0)} open", "tap_action": "open_tasks"},
                    {"type": "short_text", "text": f"{counts.get('done', 0)} done", "tap_action": "open_tasks"},
                    {"type": "icon", "icon": "check" if state.get("health", {}).get("model") else "warning", "tap_action": "status"}
                ]
            }
        except Exception as e:
            return {"error": str(e), "open_count": 0, "done_count": 0}

    def get_task_summary_for_watch(self, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            import urllib.request
            with urllib.request.urlopen(f"{self.hud_url}/api/tasks?status=open&n={limit}", timeout=5) as resp:
                data = json.loads(resp.read())
            tasks = data.get("tasks", [])
            return [{"id": t["id"], "title": t["title"][:30], "priority": t.get("priority", 3)} for t in tasks]
        except Exception:
            return []

    def sync_to_watch(self) -> Dict[str, Any]:
        watchface = self.get_watchface_data()
        tasks = self.get_task_summary_for_watch()
        sync_data = {
            "watchface": watchface,
            "tasks": tasks,
            "sync_time": datetime.now().isoformat()
        }
        self.watch_data_path.write_text(json.dumps(sync_data, indent=2))
        return {"success": True, "tasks_synced": len(tasks), "watchface": watchface}

    def get_vibration_events(self) -> List[Dict[str, Any]]:
        return [
            {"event": "task_completed", "pattern": [0, 200, 100, 200], "description": "Double pulse on task done"},
            {"event": "task_failed", "pattern": [0, 100, 100, 100, 100, 100, 100], "description": "Triple pulse on failure"},
            {"event": "urgent_task", "pattern": [0, 500], "description": "Long pulse for urgent"},
            {"event": "sync_complete", "pattern": [0, 100, 50, 100], "description": "Quick double pulse"}
        ]

    def get_watchface_config(self) -> Dict[str, Any]:
        if self.watchface_config_path.exists():
            return json.loads(self.watchface_config_path.read_text())
        return {
            "style": "digital",
            "complications": ["open_tasks", "done_count", "health"],
            "theme": "dark",
            "refresh_interval": 60,
            "vibrate_on_events": ["task_completed", "task_failed"]
        }

    def save_watchface_config(self, config: Dict[str, Any]):
        self.watchface_config_path.write_text(json.dumps(config, indent=2))


def main():
    import sys
    companion = WearOSCompanion()

    if len(sys.argv) < 2:
        print("Wear OS Companion")
        print("=" * 40)
        print("\nCommands:")
        print("  watchface    - Get watchface data")
        print("  tasks [n]    - Get tasks for watch")
        print("  sync         - Sync data to watch")
        print("  vibrations   - Vibration events")
        print("  config       - Watchface config")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "watchface":
        data = companion.get_watchface_data()
        print(json.dumps(data, indent=2))
    elif cmd == "tasks":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        tasks = companion.get_task_summary_for_watch(limit)
        for t in tasks:
            print(f"  #{t['id']} [P{t['priority']}] {t['title']}")
    elif cmd == "sync":
        result = companion.sync_to_watch()
        print(f"Synced: {result['tasks_synced']} tasks")
    elif cmd == "vibrations":
        events = companion.get_vibration_events()
        for e in events:
            print(f"  {e['event']}: {e['description']}")
    elif cmd == "config":
        config = companion.get_watchface_config()
        print(json.dumps(config, indent=2))
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
