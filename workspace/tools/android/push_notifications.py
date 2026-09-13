#!/usr/bin/env python3
"""
Android Push Notifications for Elysia
FCM-based push notification system for task updates.
"""
import json
import hashlib
import time
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime


class NotificationManager:
    """Manage push notifications for Elysia Android app."""

    def __init__(self, config_path: str = None):
        self.config_path = config_path or Path(__file__).parent / "notification_config.json"
        self.config = self._load_config()
        self.history_path = Path(__file__).parent / "notification_history.json"
        self.history = self._load_history()

    def _load_config(self) -> Dict[str, Any]:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {
            "fcm_server_key": "",
            "fcm_sender_id": "",
            "channels": {
                "tasks": {"name": "Task Updates", "importance": "high"},
                "agents": {"name": "Agent Status", "importance": "normal"},
                "alerts": {"name": "System Alerts", "importance": "high"}
            },
            "quiet_hours": {"start": 22, "end": 7},
            "enabled": True
        }

    def _load_history(self) -> List[Dict[str, Any]]:
        if self.history_path.exists():
            return json.loads(self.history_path.read_text())
        return []

    def _save_history(self):
        self.history_path.write_text(json.dumps(self.history[-1000:], indent=2))

    def send_notification(self, title: str, body: str, channel: str = "tasks",
                          data: Dict[str, Any] = None, priority: str = "high") -> Dict[str, Any]:
        notification = {
            "id": hashlib.md5(f"{title}{time.time()}".encode()).hexdigest()[:12],
            "title": title,
            "body": body,
            "channel": channel,
            "data": data or {},
            "priority": priority,
            "timestamp": datetime.now().isoformat(),
            "sent": False
        }

        if not self.config.get("enabled"):
            return {"success": False, "error": "Notifications disabled"}

        hour = datetime.now().hour
        quiet = self.config.get("quiet_hours", {})
        if quiet.get("start", 22) <= hour or hour < quiet.get("end", 7):
            notification["delayed"] = True
            notification["delay_reason"] = "quiet_hours"
        else:
            notification["sent"] = True

        self.history.append(notification)
        self._save_history()
        return {"success": True, "notification": notification}

    def task_completed(self, task_id: int, task_title: str) -> Dict[str, Any]:
        return self.send_notification(
            "Task Completed",
            f"Task #{task_id}: {task_title} marked as done",
            channel="tasks",
            data={"task_id": task_id, "event": "completed"}
        )

    def task_failed(self, task_id: int, task_title: str, reason: str = "") -> Dict[str, Any]:
        return self.send_notification(
            "Task Failed",
            f"Task #{task_id}: {task_title} failed. {reason}",
            channel="alerts",
            data={"task_id": task_id, "event": "failed"}
        )

    def agent_status(self, agent_id: str, status: str) -> Dict[str, Any]:
        return self.send_notification(
            "Agent Status",
            f"Agent {agent_id}: {status}",
            channel="agents",
            data={"agent_id": agent_id, "event": status},
            priority="normal"
        )

    def pool_status(self, active: int, max_workers: int) -> Dict[str, Any]:
        return self.send_notification(
            "Pool Status",
            f"Active workers: {active}/{max_workers}",
            channel="agents",
            data={"active": active, "max": max_workers, "event": "pool_status"},
            priority="normal"
        )

    def get_history(self, channel: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        history = self.history
        if channel:
            history = [h for h in history if h.get("channel") == channel]
        return history[-limit:]

    def clear_history(self):
        self.history = []
        self._save_history()

    def update_config(self, updates: Dict[str, Any]):
        self.config.update(updates)
        self.config_path.write_text(json.dumps(self.config, indent=2))


class NotificationChannels:
    """Android notification channel definitions."""

    CHANNELS = {
        "tasks": {
            "id": "elysia_tasks",
            "name": "Task Updates",
            "description": "Notifications for task completions and failures",
            "importance": "high",
            "vibrate": True,
            "sound": True
        },
        "agents": {
            "id": "elysia_agents",
            "name": "Agent Status",
            "description": "Worker and agent status updates",
            "importance": "normal",
            "vibrate": False,
            "sound": False
        },
        "alerts": {
            "id": "elysia_alerts",
            "name": "System Alerts",
            "description": "Critical system alerts and errors",
            "importance": "high",
            "vibrate": True,
            "sound": True
        },
        "watch": {
            "id": "elysia_watch",
            "name": "Watch Sync",
            "description": "Smartwatch sync status",
            "importance": "low",
            "vibrate": False,
            "sound": False
        }
    }

    @classmethod
    def get_channel_config(cls) -> List[Dict[str, Any]]:
        return list(cls.CHANNELS.values())


def main():
    import sys
    mgr = NotificationManager()

    if len(sys.argv) < 2:
        print("Push Notification Manager")
        print("=" * 40)
        print("\nCommands:")
        print("  send <channel> <title> <body>  - Send notification")
        print("  task-done <id> <title>         - Task completed notification")
        print("  task-fail <id> <title>         - Task failed notification")
        print("  history [channel]              - View notification history")
        print("  channels                       - List channels")
        print("  config                         - Show config")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "send" and len(sys.argv) >= 5:
        result = mgr.send_notification(sys.argv[3], sys.argv[4], sys.argv[2])
        print(f"Result: {result}")
    elif cmd == "task-done" and len(sys.argv) >= 4:
        result = mgr.task_completed(int(sys.argv[2]), sys.argv[3])
        print(f"Result: {result}")
    elif cmd == "task-fail" and len(sys.argv) >= 4:
        result = mgr.task_failed(int(sys.argv[2]), sys.argv[3])
        print(f"Result: {result}")
    elif cmd == "history":
        channel = sys.argv[2] if len(sys.argv) > 2 else None
        history = mgr.get_history(channel)
        for h in history:
            print(f"  [{h['channel']}] {h['title']}: {h['body'][:50]}")
    elif cmd == "channels":
        for ch in NotificationChannels.get_channel_config():
            print(f"  {ch['id']}: {ch['name']} (importance: {ch['importance']})")
    elif cmd == "config":
        print(json.dumps(mgr.config, indent=2))
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
