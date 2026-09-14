#!/usr/bin/env python3
"""
Android Offline Mode for Elysia
Offline caching and sync for tasks on Android.
"""
import json
import time
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime


class OfflineCache:
    """Offline task cache for Android app."""

    def __init__(self, cache_path: str = None):
        self.cache_path = cache_path or Path(__file__).parent / "offline_cache.json"
        self.data = self._load_cache()

    def _load_cache(self) -> Dict[str, Any]:
        if self.cache_path.exists():
            return json.loads(self.cache_path.read_text())
        return {"tasks": {}, "last_sync": None, "pending_actions": []}

    def _save_cache(self):
        self.cache_path.write_text(json.dumps(self.data, indent=2))

    def cache_tasks(self, tasks: List[Dict[str, Any]]):
        for task in tasks:
            self.data["tasks"][str(task["id"])] = {
                "id": task["id"],
                "title": task.get("title", ""),
                "description": task.get("description", ""),
                "status": task.get("status", "open"),
                "priority": task.get("priority", 3),
                "files": task.get("files", []),
                "cached_at": datetime.now().isoformat()
            }
        self.data["last_sync"] = datetime.now().isoformat()
        self._save_cache()

    def get_cached_tasks(self, status: str = None) -> List[Dict[str, Any]]:
        tasks = list(self.data["tasks"].values())
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        return sorted(tasks, key=lambda x: x.get("priority", 3), reverse=True)

    def add_pending_action(self, action: str, task_id: int, params: Dict[str, Any] = None):
        self.data["pending_actions"].append({
            "action": action,
            "task_id": task_id,
            "params": params or {},
            "timestamp": datetime.now().isoformat()
        })
        self._save_cache()

    def get_pending_actions(self) -> List[Dict[str, Any]]:
        return self.data.get("pending_actions", [])

    def clear_pending_actions(self):
        self.data["pending_actions"] = []
        self._save_cache()

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        return self.data["tasks"].get(str(task_id))

    def update_task_local(self, task_id: int, updates: Dict[str, Any]):
        key = str(task_id)
        if key in self.data["tasks"]:
            self.data["tasks"][key].update(updates)
            self.data["tasks"][key]["modified_offline"] = True
            self._save_cache()

    def get_sync_status(self) -> Dict[str, Any]:
        return {
            "cached_tasks": len(self.data["tasks"]),
            "last_sync": self.data.get("last_sync"),
            "pending_actions": len(self.data.get("pending_actions", [])),
            "is_online": self._check_connectivity()
        }

    def _check_connectivity(self) -> bool:
        import urllib.request
        try:
            urllib.request.urlopen("http://127.0.0.1:8087/api/state", timeout=3)
            return True
        except Exception:
            return False

    def sync_pending(self) -> Dict[str, Any]:
        if not self._check_connectivity():
            return {"success": False, "error": "Offline"}

        import urllib.request
        results = {"synced": 0, "failed": 0, "errors": []}
        pending = self.get_pending_actions()

        for action in pending:
            try:
                if action["action"] == "add_task":
                    payload = json.dumps({
                        "title": action["params"].get("title", "Offline task"),
                        "description": action["params"].get("description", ""),
                        "files": [],
                        "priority": action["params"].get("priority", 3)
                    }).encode()
                    req = urllib.request.Request(
                        "http://127.0.0.1:8087/api/task",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST"
                    )
                    urllib.request.urlopen(req, timeout=5)
                    results["synced"] += 1

                elif action["action"] == "complete_task":
                    results["synced"] += 1

            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))

        self.clear_pending_actions()
        self.data["last_sync"] = datetime.now().isoformat()
        self._save_cache()
        return results

    def clear_cache(self):
        self.data = {"tasks": {}, "last_sync": None, "pending_actions": []}
        self._save_cache()


def main():
    import sys
    cache = OfflineCache()

    if len(sys.argv) < 2:
        print("Offline Cache Manager")
        print("=" * 40)
        print("\nCommands:")
        print("  status          - Cache status")
        print("  tasks [status]  - List cached tasks")
        print("  add <title>     - Add offline task")
        print("  sync            - Sync pending actions")
        print("  clear           - Clear cache")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "status":
        status = cache.get_sync_status()
        print(f"Cached tasks: {status['cached_tasks']}")
        print(f"Pending actions: {status['pending_actions']}")
        print(f"Last sync: {status['last_sync'] or 'Never'}")
        print(f"Online: {status['is_online']}")

    elif cmd == "tasks":
        status = sys.argv[2] if len(sys.argv) > 2 else None
        tasks = cache.get_cached_tasks(status)
        for t in tasks:
            print(f"  #{t['id']} [{t['status']}] {t['title'][:50]}")

    elif cmd == "add" and len(sys.argv) >= 3:
        title = " ".join(sys.argv[2:])
        cache.add_pending_action("add_task", 0, {"title": title})
        print(f"Added offline task: {title}")

    elif cmd == "sync":
        result = cache.sync_pending()
        print(f"Synced: {result['synced']}, Failed: {result['failed']}")

    elif cmd == "clear":
        cache.clear_cache()
        print("Cache cleared")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
