#!/usr/bin/env python3
"""
Android Task Dashboard for Elysia
Real-time task board status from Elysia HUD API.
"""
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path


class AndroidDashboard:
    """Android dashboard for Elysia task board."""

    def __init__(self, hud_url: str = "http://127.0.0.1:8087"):
        self.hud_url = hud_url
        self.cache = {}
        self.cache_ttl = 30

    def _request(self, endpoint: str) -> Dict[str, Any]:
        """Make API request to HUD."""
        import urllib.request
        try:
            url = f"{self.hud_url}{endpoint}"
            with urllib.request.urlopen(url, timeout=5) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {"error": str(e)}

    def get_task_summary(self) -> Dict[str, Any]:
        """Get task summary from HUD API."""
        data = self._request("/api/state")
        if "error" in data:
            return data

        return {
            "open": data["counts"]["open"],
            "claimed": data["counts"]["claimed"],
            "done": data["counts"]["done"],
            "failed": data["counts"]["failed"],
            "total": data["counts"]["total"],
            "health": data["health"],
            "timestamp": data["time"]
        }

    def get_recent_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent tasks from HUD."""
        data = self._request(f"/api/tasks?n={limit}")
        return data.get("tasks", [])

    def get_agent_status(self) -> List[Dict[str, Any]]:
        """Get agent status from HUD."""
        data = self._request("/api/agents")
        return data.get("agents", [])

    def get_task_detail(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed task information."""
        data = self._request(f"/api/tasks?id={task_id}")
        tasks = data.get("tasks", [])
        return tasks[0] if tasks else None

    def create_task(self, title: str, description: str,
                    files: List[str] = None, priority: int = 5) -> Dict[str, Any]:
        """Create a new task via HUD API."""
        import urllib.request

        payload = {
            "title": title,
            "description": description,
            "files": files or [],
            "priority": priority
        }

        req = urllib.request.Request(
            f"{self.hud_url}/api/task",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {"error": str(e)}

    def control_pool(self, action: str, cap: int = 2) -> Dict[str, Any]:
        """Control the adaptive pool."""
        import urllib.request

        payload = {"action": action, "cap": cap}

        req = urllib.request.Request(
            f"{self.hud_url}/api/pool",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {"error": str(e)}

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get all dashboard data in one call."""
        return {
            "summary": self.get_task_summary(),
            "recent_tasks": self.get_recent_tasks(5),
            "agents": self.get_agent_status(),
            "timestamp": datetime.now().isoformat()
        }


def main():
    """CLI entry point."""
    dashboard = AndroidDashboard()

    if len(sys.argv) < 2:
        print("Android Task Dashboard")
        print("=" * 40)
        print("\nCommands:")
        print("  summary          - Task summary")
        print("  tasks [n]        - Recent tasks")
        print("  agents           - Agent status")
        print("  detail <id>      - Task detail")
        print("  create <title>   - Create task")
        print("  pool <action>    - Control pool")
        print("  dashboard        - All data")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "summary":
        summary = dashboard.get_task_summary()
        print(f"\nTask Summary:")
        print(f"  Open: {summary.get('open', 0)}")
        print(f"  Claimed: {summary.get('claimed', 0)}")
        print(f"  Done: {summary.get('done', 0)}")
        print(f"  Failed: {summary.get('failed', 0)}")
        print(f"  Health: {summary.get('health', {})}")

    elif cmd == "tasks":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        tasks = dashboard.get_recent_tasks(limit)
        print(f"\nRecent Tasks ({len(tasks)}):")
        for t in tasks:
            print(f"  #{t['id']} [{t['status']}] {t['title'][:50]}")

    elif cmd == "agents":
        agents = dashboard.get_agent_status()
        print(f"\nActive Agents ({len(agents)}):")
        for a in agents:
            print(f"  {a['id']}: PID {a['pid']} (up {a.get('uptime_s', 0)}s)")

    elif cmd == "detail" and len(sys.argv) >= 3:
        task = dashboard.get_task_detail(int(sys.argv[2]))
        if task:
            print(f"\nTask #{task['id']}:")
            print(f"  Title: {task['title']}")
            print(f"  Status: {task['status']}")
            print(f"  Priority: {task['priority']}")
            print(f"  Worker: {task.get('worker', 'None')}")

    elif cmd == "create" and len(sys.argv) >= 3:
        title = " ".join(sys.argv[2:])
        result = dashboard.create_task(title, f"Auto-created: {title}")
        print(f"\nTask created: {result}")

    elif cmd == "pool" and len(sys.argv) >= 3:
        action = sys.argv[2]
        cap = int(sys.argv[3]) if len(sys.argv) > 3 else 2
        result = dashboard.control_pool(action, cap)
        print(f"\nPool control: {result}")

    elif cmd == "dashboard":
        data = dashboard.get_dashboard_data()
        print(f"\nDashboard Data:")
        print(json.dumps(data, indent=2))

    else:
        print("Unknown command. Run without args for help.")


import sys
if __name__ == "__main__":
    main()
