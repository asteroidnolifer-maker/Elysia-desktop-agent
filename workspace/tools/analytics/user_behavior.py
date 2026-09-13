#!/usr/bin/env python3
"""
Elysia User Behavior Tracking - Task 1606
Session recording, event funnels, and user journey mapping.
"""
import json
import sys
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


class UserBehaviorTracker:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "behavior")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self.funnels: Dict[str, List[str]] = {}

    def start_session(self, user_id: str = "anonymous") -> str:
        session_id = str(uuid.uuid4())[:8]
        self.sessions[session_id] = {
            "user_id": user_id,
            "started": datetime.now().isoformat(),
            "events": [],
            "pages": [],
            "duration_s": 0
        }
        return session_id

    def track_event(self, session_id: str, event: str, properties: Dict[str, Any] = None):
        entry = {
            "session_id": session_id,
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "properties": properties or {}
        }
        self.events.append(entry)
        if session_id in self.sessions:
            self.sessions[session_id]["events"].append(entry)

    def track_page(self, session_id: str, page: str, duration_s: float = 0):
        if session_id in self.sessions:
            self.sessions[session_id]["pages"].append({
                "page": page,
                "timestamp": datetime.now().isoformat(),
                "duration_s": duration_s
            })

    def end_session(self, session_id: str):
        if session_id in self.sessions:
            session = self.sessions[session_id]
            session["ended"] = datetime.now().isoformat()
            start = datetime.fromisoformat(session["started"])
            session["duration_s"] = (datetime.now() - start).total_seconds()

    def define_funnel(self, name: str, steps: List[str]):
        self.funnels[name] = steps

    def analyze_funnel(self, funnel_name: str, since_hours: int = 24) -> Dict[str, Any]:
        steps = self.funnels.get(funnel_name, [])
        if not steps:
            return {"error": f"Funnel '{funnel_name}' not found"}

        cutoff = datetime.now() - timedelta(hours=since_hours)
        user_events = defaultdict(list)
        for e in self.events:
            ts = datetime.fromisoformat(e["timestamp"])
            if ts >= cutoff:
                user_events[e.get("session_id", "")].append(e["event"])

        step_counts = []
        for step in steps:
            count = sum(1 for events in user_events.values() if step in events)
            step_counts.append(count)

        conversion_rates = []
        for i in range(1, len(step_counts)):
            rate = (step_counts[i] / max(step_counts[i-1], 1)) * 100
            conversion_rates.append(rate)

        return {
            "funnel": funnel_name,
            "steps": list(zip(steps, step_counts)),
            "conversion_rates": conversion_rates,
            "overall_conversion": (step_counts[-1] / max(step_counts[0], 1) * 100) if step_counts else 0
        }

    def get_user_journey(self, session_id: str) -> List[Dict[str, Any]]:
        session = self.sessions.get(session_id, {})
        return session.get("pages", [])

    def get_top_events(self, hours: int = 24, limit: int = 10) -> List[Dict[str, Any]]:
        cutoff = datetime.now() - timedelta(hours=hours)
        counts = defaultdict(int)
        for e in self.events:
            if datetime.fromisoformat(e["timestamp"]) >= cutoff:
                counts[e["event"]] += 1
        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"event": name, "count": count} for name, count in ranked]

    def get_engagement_metrics(self, hours: int = 24) -> Dict[str, Any]:
        cutoff = datetime.now() - timedelta(hours=hours)
        active_sessions = [s for s in self.sessions.values()
                          if datetime.fromisoformat(s["started"]) >= cutoff]
        if not active_sessions:
            return {"sessions": 0, "avg_duration": 0, "avg_events": 0}

        durations = [s.get("duration_s", 0) for s in active_sessions]
        event_counts = [len(s.get("events", [])) for s in active_sessions]
        return {
            "sessions": len(active_sessions),
            "avg_duration": sum(durations) / len(durations),
            "avg_events": sum(event_counts) / len(event_counts)
        }

    def save(self):
        path = self.data_dir / "behavior_data.json"
        path.write_text(json.dumps({
            "sessions": self.sessions,
            "events": self.events[-5000:],
            "funnels": self.funnels
        }, indent=2))


def main():
    tracker = UserBehaviorTracker()

    if len(sys.argv) < 2:
        print("Elysia User Behavior Tracker")
        print("Commands: session, track <sid> <event>, funnel <name> <steps>, analyze <funnel>, top-events, engagement")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "session":
        sid = tracker.start_session()
        print(f"Session: {sid}")
    elif cmd == "track" and len(sys.argv) >= 4:
        tracker.track_event(sys.argv[2], sys.argv[3])
        print(f"[+] Tracked {sys.argv[3]}")
    elif cmd == "funnel" and len(sys.argv) >= 4:
        steps = sys.argv[3].split(",")
        tracker.define_funnel(sys.argv[2], steps)
        print(f"[+] Funnel '{sys.argv[2]}' defined with {len(steps)} steps")
    elif cmd == "analyze" and len(sys.argv) >= 3:
        result = tracker.analyze_funnel(sys.argv[2])
        print(json.dumps(result, indent=2))
    elif cmd == "top-events":
        events = tracker.get_top_events()
        for e in events:
            print(f"  {e['event']}: {e['count']}")
    elif cmd == "engagement":
        m = tracker.get_engagement_metrics()
        print(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
