#!/usr/bin/env python3
"""
Elysia Logger - Task 1216
Structured logging with rotation, levels, and component tracking.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
from enum import Enum


class LogLevel(Enum):
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4


class ElysiaLogger:
    def __init__(self, name: str = "elysia", log_dir: str = None,
                 level: LogLevel = LogLevel.INFO, max_bytes: int = 10_000_000,
                 backup_count: int = 5):
        self.name = name
        self.log_dir = Path(log_dir or Path(__file__).parent / ".data" / "logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.level = level
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.log_file = self.log_dir / f"{name}.log"
        self.metrics: Dict[str, int] = {}

    def _rotate(self):
        if not self.log_file.exists():
            return
        if self.log_file.stat().st_size < self.max_bytes:
            return
        for i in range(self.backup_count - 1, 0, -1):
            src = self.log_dir / f"{self.name}.{i}.log"
            dst = self.log_dir / f"{self.name}.{i+1}.log"
            if src.exists():
                src.rename(dst)
        self.log_file.rename(self.log_dir / f"{self.name}.1.log")

    def _write(self, level: LogLevel, message: str, component: str,
               data: Dict[str, Any] = None):
        if level.value < self.level.value:
            return
        self._rotate()
        entry = {
            "ts": datetime.now().isoformat(),
            "level": level.name,
            "component": component,
            "message": message,
        }
        if data:
            entry["data"] = data
        key = f"{component}:{level.name}"
        self.metrics[key] = self.metrics.get(key, 0) + 1

        line = json.dumps(entry)
        with open(self.log_file, "a") as f:
            f.write(line + "\n")

    def debug(self, message: str, component: str = "core",
              data: Dict[str, Any] = None):
        self._write(LogLevel.DEBUG, message, component, data)

    def info(self, message: str, component: str = "core",
             data: Dict[str, Any] = None):
        self._write(LogLevel.INFO, message, component, data)

    def warning(self, message: str, component: str = "core",
                data: Dict[str, Any] = None):
        self._write(LogLevel.WARNING, message, component, data)

    def error(self, message: str, component: str = "core",
              data: Dict[str, Any] = None):
        self._write(LogLevel.ERROR, message, component, data)

    def critical(self, message: str, component: str = "core",
                 data: Dict[str, Any] = None):
        self._write(LogLevel.CRITICAL, message, component, data)

    def get_recent(self, count: int = 50, level: LogLevel = None,
                   component: str = None) -> list:
        if not self.log_file.exists():
            return []
        lines = self.log_file.read_text().strip().split("\n")
        entries = []
        for line in reversed(lines):
            if not line.strip():
                continue
            entry = json.loads(line)
            if level and entry.get("level") != level.name:
                continue
            if component and entry.get("component") != component:
                continue
            entries.append(entry)
            if len(entries) >= count:
                break
        return entries

    def get_metrics(self) -> Dict[str, Any]:
        return {
            "counts": self.metrics,
            "log_file": str(self.log_file),
            "log_size_bytes": self.log_file.stat().st_size if self.log_file.exists() else 0
        }

    def search(self, query: str, since_minutes: int = 60) -> list:
        if not self.log_file.exists():
            return []
        cutoff = time.time() - (since_minutes * 60)
        results = []
        for line in self.log_file.read_text().strip().split("\n"):
            if not line.strip():
                continue
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry["ts"]).timestamp()
            if ts < cutoff:
                continue
            if query.lower() in json.dumps(entry).lower():
                results.append(entry)
        return results


class ComponentLogger:
    def __init__(self, logger: ElysiaLogger, component: str):
        self.logger = logger
        self.component = component

    def debug(self, msg, data=None):
        self.logger.debug(msg, self.component, data)

    def info(self, msg, data=None):
        self.logger.info(msg, self.component, data)

    def warning(self, msg, data=None):
        self.logger.warning(msg, self.component, data)

    def error(self, msg, data=None):
        self.logger.error(msg, self.component, data)


def get_logger(name: str = "elysia", component: str = "core") -> ComponentLogger:
    logger = ElysiaLogger(name)
    return ComponentLogger(logger, component)


def main():
    if len(sys.argv) < 2:
        print("Elysia Logger")
        print("Commands: log <level> <msg>, recent, metrics, search <query>")
        sys.exit(0)

    logger = ElysiaLogger()
    cmd = sys.argv[1]

    if cmd == "log" and len(sys.argv) >= 4:
        level = sys.argv[2]
        msg = " ".join(sys.argv[3:])
        getattr(logger, level, logger.info)(msg, "cli")
        print(f"[+] Logged at {level}: {msg}")
    elif cmd == "recent":
        entries = logger.get_recent(20)
        for e in entries:
            print(f"[{e['level']}] {e['component']}: {e['message']}")
    elif cmd == "metrics":
        print(json.dumps(logger.get_metrics(), indent=2))
    elif cmd == "search" and len(sys.argv) >= 3:
        query = " ".join(sys.argv[2:])
        results = logger.search(query)
        print(f"Found {len(results)} matches")
        for r in results[:10]:
            print(f"  [{r['level']}] {r['message']}")


if __name__ == "__main__":
    main()
