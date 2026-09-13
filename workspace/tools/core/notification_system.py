#!/usr/bin/env python3
"""
Elysia Notification System - Task 1239
Multi-channel notifications: log, file, webhook, email, push.
"""
import json
import os
import smtplib
import sys
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum


class NotifyLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationChannel:
    def send(self, title: str, message: str, level: NotifyLevel,
             data: Dict[str, Any] = None) -> bool:
        raise NotImplementedError


class LogChannel(NotificationChannel):
    def send(self, title, message, level, data=None):
        print(f"[{level.value.upper()}] {title}: {message}")
        return True


class FileChannel(NotificationChannel):
    def __init__(self, path: str = None):
        self.path = Path(path or Path(__file__).parent / ".data" / "notifications.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, title, message, level, data=None):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "title": title,
            "message": message,
            "level": level.value,
            "data": data or {}
        }
        with open(self.path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return True


class WebhookChannel(NotificationChannel):
    def __init__(self, url: str):
        self.url = url

    def send(self, title, message, level, data=None):
        payload = json.dumps({
            "title": title,
            "message": message,
            "level": level.value,
            "data": data or {},
            "timestamp": datetime.now().isoformat()
        }).encode()
        req = urllib.request.Request(self.url, data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10):
                return True
        except Exception:
            return False


class EmailChannel(NotificationChannel):
    def __init__(self, smtp_host: str, smtp_port: int, username: str,
                 password: str, from_addr: str, to_addrs: List[str]):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs

    def send(self, title, message, level, data=None):
        msg = MIMEText(message)
        msg["Subject"] = f"[Elysia {level.value.upper()}] {title}"
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as s:
                s.starttls()
                s.login(self.username, self.password)
                s.send_message(msg)
            return True
        except Exception:
            return False


class NotificationManager:
    def __init__(self, config_path: str = None):
        self.config_path = Path(config_path or Path(__file__).parent / ".data" / "notif_config.json")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.channels: Dict[str, NotificationChannel] = {}
        self.history: List[Dict[str, Any]] = []
        self._load_config()

    def _load_config(self):
        if self.config_path.exists():
            config = json.loads(self.config_path.read_text())
        else:
            config = {"channels": {"log": True, "file": True}}
            self.config_path.write_text(json.dumps(config, indent=2))

        if config.get("channels", {}).get("file"):
            self.channels["file"] = FileChannel()
        if config.get("channels", {}).get("webhook"):
            url = config["channels"]["webhook"].get("url", "")
            if url:
                self.channels["webhook"] = WebhookChannel(url)

        self.channels.setdefault("log", LogChannel())

    def notify(self, title: str, message: str, level: NotifyLevel = NotifyLevel.INFO,
               data: Dict[str, Any] = None, channels: List[str] = None) -> Dict[str, bool]:
        results = {}
        target_channels = channels or list(self.channels.keys())
        for ch_name in target_channels:
            ch = self.channels.get(ch_name)
            if ch:
                results[ch_name] = ch.send(title, message, level, data)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "title": title,
            "message": message,
            "level": level.value,
            "results": results
        }
        self.history.append(entry)
        return results

    def info(self, title: str, message: str, **kwargs):
        return self.notify(title, message, NotifyLevel.INFO, **kwargs)

    def warning(self, title: str, message: str, **kwargs):
        return self.notify(title, message, NotifyLevel.WARNING, **kwargs)

    def error(self, title: str, message: str, **kwargs):
        return self.notify(title, message, NotifyLevel.ERROR, **kwargs)

    def critical(self, title: str, message: str, **kwargs):
        return self.notify(title, message, NotifyLevel.CRITICAL, **kwargs)

    def get_history(self, limit: int = 50, level: NotifyLevel = None) -> list:
        entries = self.history
        if level:
            entries = [e for e in entries if e["level"] == level.value]
        return entries[-limit:]

    def add_webhook(self, url: str):
        self.channels["webhook"] = WebhookChannel(url)

    def list_channels(self) -> List[str]:
        return list(self.channels.keys())


def main():
    mgr = NotificationManager()

    if len(sys.argv) < 2:
        print("Elysia Notification System")
        print("Commands: notify <title> <msg>, history, channels, webhook <url>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "notify" and len(sys.argv) >= 4:
        title = sys.argv[2]
        msg = " ".join(sys.argv[3:])
        result = mgr.info(title, msg)
        print(json.dumps(result, indent=2))
    elif cmd == "history":
        for e in mgr.get_history(20):
            print(f"[{e['level']}] {e['title']}: {e['message']}")
    elif cmd == "channels":
        print(f"Active: {', '.join(mgr.list_channels())}")
    elif cmd == "webhook" and len(sys.argv) >= 3:
        mgr.add_webhook(sys.argv[2])
        print(f"[+] Webhook added: {sys.argv[2]}")


if __name__ == "__main__":
    main()
