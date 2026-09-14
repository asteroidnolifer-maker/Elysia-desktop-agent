#!/usr/bin/env python3
"""
Elysia Event System - Task 1269
Event-driven architecture with pub/sub, event sourcing, and handlers.
"""
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class Event:
    def __init__(self, event_type: str, data: Dict[str, Any] = None,
                 source: str = "system"):
        self.id = f"evt_{int(time.time()*1000)}"
        self.type = event_type
        self.data = data or {}
        self.source = source
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "type": self.type, "data": self.data,
            "source": self.source, "timestamp": self.timestamp
        }


class EventBus:
    def __init__(self, store_path: str = None):
        self.store_path = Path(store_path or Path(__file__).parent / ".data" / "events.jsonl")
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self.wildcard_handlers: List[Callable] = []
        self.event_log: List[Dict[str, Any]] = []

    def subscribe(self, event_type: str, handler: Callable):
        self.subscribers[event_type].append(handler)

    def subscribe_all(self, handler: Callable):
        self.wildcard_handlers.append(handler)

    def unsubscribe(self, event_type: str, handler: Callable):
        if event_type in self.subscribers:
            self.subscribers[event_type] = [
                h for h in self.subscribers[event_type] if h != handler
            ]

    def publish(self, event: Event) -> Dict[str, Any]:
        self.event_log.append(event.to_dict())
        with open(self.store_path, "a") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

        results = []
        for handler in self.subscribers.get(event.type, []):
            try:
                result = handler(event)
                results.append({"handler": handler.__name__, "status": "ok"})
            except Exception as e:
                results.append({"handler": handler.__name__, "status": "error",
                               "error": str(e)})

        for handler in self.wildcard_handlers:
            try:
                handler(event)
            except Exception:
                pass

        return {"event_id": event.id, "handlers_called": len(results),
                "results": results}

    def emit(self, event_type: str, data: Dict[str, Any] = None,
             source: str = "system") -> Dict[str, Any]:
        event = Event(event_type, data, source)
        return self.publish(event)

    def get_events(self, event_type: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        events = self.event_log
        if event_type:
            events = [e for e in events if e["type"] == event_type]
        return events[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        by_type = defaultdict(int)
        for e in self.event_log:
            by_type[e["type"]] += 1
        return {
            "total_events": len(self.event_log),
            "by_type": dict(by_type),
            "subscribers": {k: len(v) for k, v in self.subscribers.items()}
        }


def main():
    bus = EventBus()
    if len(sys.argv) < 2:
        print("Elysia Event System")
        print("Commands: emit <type> [data_json], subscribe <type>, events [type], stats")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "emit" and len(sys.argv) >= 3:
        data = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        result = bus.emit(sys.argv[2], data)
        print(json.dumps(result, indent=2))
    elif cmd == "events":
        etype = sys.argv[2] if len(sys.argv) > 2 else None
        events = bus.get_events(etype)
        for e in events:
            print(f"  [{e['type']}] {e['timestamp'][:19]} - {e.get('data', {})}")
    elif cmd == "stats":
        print(json.dumps(bus.get_stats(), indent=2))


if __name__ == "__main__":
    main()
