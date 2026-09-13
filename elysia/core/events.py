"""Structured event bus for observability.

The HUD consumes these events instead of scraping logs or guessing state from
process names. Every event carries a timestamp, run/task/agent identifiers,
provider/model context, status and optional error.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid


class EventBus:
    def __init__(self, run_id: str | None = None):
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self._mu = threading.Lock()
        self._events: list[dict] = []
        self._sinks: list = []
        self._max_mem = 2000

    def emit(self, event_type: str, *, task_id=None, agent_id=None,
             provider=None, model=None, status=None, error=None,
             duration_s=None, **extra) -> dict:
        ev = {
            "run_id": self.run_id,
            "ts": time.time(),
            "event_type": event_type,
            "task_id": task_id,
            "agent_id": agent_id,
            "provider": provider,
            "model": model,
            "status": status,
            "error": error,
            "duration_s": duration_s,
        }
        ev.update(extra)
        with self._mu:
            self._events.append(ev)
            if len(self._events) > self._max_mem:
                self._events = self._events[-self._max_mem:]
            for s in self._sinks:
                try:
                    s(ev)
                except Exception:
                    pass
        return ev

    def subscribe(self, sink) -> None:
        """Register a callable that receives each event dict."""
        self._sinks.append(sink)

    def recent(self, n: int = 200, event_type: str | None = None) -> list:
        with self._mu:
            evs = list(self._events)
        if event_type:
            evs = [e for e in evs if e.get("event_type") == event_type]
        return evs[-n:]

    def to_file(self, path: str, limit: int = 5000) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for ev in self.recent(limit):
                f.write(json.dumps(ev) + "\n")