#!/usr/bin/env python3
"""
Elysia Error Handler - Task 1215
Centralized error handling, retry logic, and graceful degradation.
"""
import json
import time
import traceback
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path
from functools import wraps
from enum import Enum


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ElysiaError(Exception):
    def __init__(self, message: str, severity: Severity = Severity.MEDIUM,
                 component: str = "unknown", context: Dict[str, Any] = None):
        super().__init__(message)
        self.severity = severity
        self.component = component
        self.context = context or {}
        self.timestamp = datetime.now().isoformat()


class ErrorHandler:
    def __init__(self, log_path: str = None):
        self.log_path = log_path or Path(__file__).parent / ".data" / "errors.jsonl"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.error_counts: Dict[str, int] = {}
        self.max_retries = 3
        self.retry_delays = [0.5, 1.0, 2.0]

    def record_error(self, error: Exception, component: str = "unknown",
                     context: Dict[str, Any] = None) -> Dict[str, Any]:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": type(error).__name__,
            "message": str(error),
            "component": component,
            "context": context or {},
            "traceback": traceback.format_exc()
        }
        key = f"{component}:{type(error).__name__}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
        entry["count"] = self.error_counts[key]

        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        return entry

    def retry(self, func: Callable, *args, max_retries: int = None,
              on_retry: Callable = None, **kwargs) -> Any:
        retries = max_retries or self.max_retries
        last_error = None

        for attempt in range(retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                self.record_error(e, component=func.__name__,
                                  context={"attempt": attempt + 1, "max": retries})
                if on_retry:
                    on_retry(e, attempt + 1)
                if attempt < retries - 1:
                    time.sleep(self.retry_delays[min(attempt, len(self.retry_delays) - 1)])

        raise last_error

    def safe_execute(self, func: Callable, *args, default: Any = None,
                     component: str = "unknown", **kwargs) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            self.record_error(e, component=component)
            return default

    def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        if not self.log_path.exists():
            return {"total": 0, "by_component": {}, "by_type": {}}

        cutoff = time.time() - (hours * 3600)
        errors = []
        with open(self.log_path) as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    ts = datetime.fromisoformat(entry["timestamp"]).timestamp()
                    if ts >= cutoff:
                        errors.append(entry)

        by_component = {}
        by_type = {}
        for e in errors:
            comp = e.get("component", "unknown")
            by_component[comp] = by_component.get(comp, 0) + 1
            etype = e.get("type", "unknown")
            by_type[etype] = by_type.get(etype, 0) + 1

        return {
            "total": len(errors),
            "by_component": by_component,
            "by_type": by_type,
            "period_hours": hours
        }


def with_retry(max_retries: int = 3, delay: float = 1.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            handler = ErrorHandler()
            return handler.retry(func, *args, max_retries=max_retries)
        return wrapper
    return decorator


def with_error_handling(default: Any = None, component: str = "unknown"):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            handler = ErrorHandler()
            return handler.safe_execute(func, *args, default=default, component=component)
        return wrapper
    return decorator


def main():
    import sys
    handler = ErrorHandler()

    if len(sys.argv) < 2:
        print("Elysia Error Handler")
        print("Commands: summary, test-retry, test-safe")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "summary":
        s = handler.get_error_summary()
        print(json.dumps(s, indent=2))
    elif cmd == "test-retry":
        attempt = [0]
        def flaky():
            attempt[0] += 1
            if attempt[0] < 3:
                raise ValueError(f"Attempt {attempt[0]} failed")
            return "success"
        result = handler.retry(flaky, max_retries=3)
        print(f"Result: {result}")
    elif cmd == "test-safe":
        result = handler.safe_execute(lambda: 1/0, default="recovered")
        print(f"Safe result: {result}")


if __name__ == "__main__":
    main()
