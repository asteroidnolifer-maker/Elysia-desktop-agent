#!/usr/bin/env python3
"""
YouTube Content Calendar for Elysia
Plan and schedule video content.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime, timedelta


class ContentCalendar:
    """Manage YouTube content calendar."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "content_calendar.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"videos": [], "ideas": [], "schedule": {}}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_video_plan(self, title: str, topic: str, scheduled_date: str,
                       status: str = "planned", tags: List[str] = None) -> Dict[str, Any]:
        video = {
            "id": f"vid_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "title": title, "topic": topic, "scheduled_date": scheduled_date,
            "status": status, "tags": tags or [], "created": datetime.now().isoformat(),
            "checklist": {
                "script": False, "record": False, "edit": False,
                "thumbnail": False, "upload": False, "promote": False
            }
        }
        self.data["videos"].append(video)
        self._save_data()
        return video

    def update_video_status(self, video_id: str, status: str):
        for v in self.data["videos"]:
            if v["id"] == video_id:
                v["status"] = status
                self._save_data()
                return True
        return False

    def get_upcoming(self, days: int = 30) -> List[Dict[str, Any]]:
        cutoff = (datetime.now() + timedelta(days=days)).isoformat()
        return [v for v in self.data["videos"]
                if v.get("scheduled_date", "") <= cutoff and v.get("status") != "published"]

    def add_idea(self, title: str, niche: str = "tech", priority: int = 3):
        self.data["ideas"].append({
            "id": f"idea_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "title": title, "niche": niche, "priority": priority,
            "added": datetime.now().isoformat()
        })
        self._save_data()

    def get_ideas(self, niche: str = None) -> List[Dict[str, Any]]:
        ideas = self.data.get("ideas", [])
        if niche:
            ideas = [i for i in ideas if i.get("niche") == niche]
        return sorted(ideas, key=lambda x: x.get("priority", 3), reverse=True)

    def generate_weekly_plan(self) -> List[Dict[str, Any]]:
        plan = []
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        upcoming = self.get_upcoming(7)
        for i, day in enumerate(days[:len(upcoming)]):
            plan.append({"day": day, "video": upcoming[i] if i < len(upcoming) else None})
        return plan

    def get_stats(self) -> Dict[str, Any]:
        videos = self.data["videos"]
        statuses = {}
        for v in videos:
            s = v.get("status", "planned")
            statuses[s] = statuses.get(s, 0) + 1
        return {"total": len(videos), "by_status": statuses, "ideas": len(self.data.get("ideas", []))}


def main():
    import sys
    calendar = ContentCalendar()

    if len(sys.argv) < 2:
        print("Content Calendar")
        print("=" * 40)
        print("\nCommands:")
        print("  add <title> <topic> <date>  - Add video plan")
        print("  upcoming [days]             - Upcoming videos")
        print("  idea <title> [niche]        - Add idea")
        print("  ideas [niche]               - List ideas")
        print("  plan                        - Weekly plan")
        print("  stats                       - Calendar stats")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add" and len(sys.argv) >= 5:
        result = calendar.add_video_plan(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"Added: {result['title']} on {result['scheduled_date']}")
    elif cmd == "upcoming":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        for v in calendar.get_upcoming(days):
            print(f"  [{v['scheduled_date'][:10]}] {v['title']}")
    elif cmd == "idea" and len(sys.argv) >= 3:
        niche = sys.argv[3] if len(sys.argv) > 3 else "tech"
        calendar.add_idea(sys.argv[2], niche)
        print(f"Idea added: {sys.argv[2]}")
    elif cmd == "ideas":
        niche = sys.argv[2] if len(sys.argv) > 2 else None
        for i in calendar.get_ideas(niche):
            print(f"  [P{i['priority']}] {i['title']}")
    elif cmd == "plan":
        for item in calendar.generate_weekly_plan():
            title = item["video"]["title"] if item["video"] else "No video"
            print(f"  {item['day']}: {title}")
    elif cmd == "stats":
        stats = calendar.get_stats()
        print(f"Total videos: {stats['total']}, Ideas: {stats['ideas']}")
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
