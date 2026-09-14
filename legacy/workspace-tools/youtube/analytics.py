#!/usr/bin/env python3
"""
YouTube Analytics Dashboard for Elysia
Channel analytics, subscriber growth, watch time tracking.
"""
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime, timedelta


class YouTubeAnalytics:
    """Track and analyze YouTube channel performance."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "analytics.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {
            "channel": {"subscribers": 0, "total_views": 0, "total_videos": 0},
            "videos": {}, "daily": [], "goals": {}
        }

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def update_channel_stats(self, subscribers: int, views: int, videos: int):
        self.data["channel"] = {"subscribers": subscribers, "total_views": views, "total_videos": videos}
        self.data["daily"].append({
            "date": datetime.now().isoformat(), "subscribers": subscribers,
            "views": views, "videos": videos
        })
        self._save_data()

    def add_video(self, video_id: str, title: str, views: int = 0, likes: int = 0, comments: int = 0):
        self.data["videos"][video_id] = {
            "title": title, "views": views, "likes": likes, "comments": comments,
            "added": datetime.now().isoformat(), "history": []
        }
        self.data["channel"]["total_videos"] += 1
        self._save_data()

    def update_video_stats(self, video_id: str, views: int, likes: int, comments: int):
        if video_id in self.data["videos"]:
            v = self.data["videos"][video_id]
            v["views"] = views
            v["likes"] = likes
            v["comments"] = comments
            v["history"].append({
                "timestamp": datetime.now().isoformat(),
                "views": views, "likes": likes, "comments": comments,
                "engagement": (likes + comments) / max(views, 1) * 100
            })
            self._save_data()

    def get_engagement_rate(self, video_id: str = None) -> float:
        if video_id and video_id in self.data["videos"]:
            v = self.data["videos"][video_id]
            total = v["views"]
            return ((v["likes"] + v["comments"]) / total * 100) if total > 0 else 0
        total_views = self.data["channel"]["total_views"]
        return 0

    def get_growth_metrics(self, days: int = 30) -> Dict[str, Any]:
        daily = self.data["daily"]
        if len(daily) < 2:
            return {"subscriber_growth": 0, "view_growth": 0}
        recent = daily[-1]
        old = daily[max(0, len(daily) - days)]
        return {
            "subscriber_growth": recent["subscribers"] - old["subscribers"],
            "view_growth": recent["views"] - old["views"],
            "period_days": days
        }

    def get_top_videos(self, limit: int = 5) -> List[Dict[str, Any]]:
        videos = [{"id": vid, **v} for vid, v in self.data["videos"].items()]
        return sorted(videos, key=lambda x: x.get("views", 0), reverse=True)[:limit]

    def set_goal(self, goal_type: str, target: int, deadline: str):
        self.data["goals"][goal_type] = {"target": target, "deadline": deadline, "set_date": datetime.now().isoformat()}
        self._save_data()

    def get_goals_progress(self) -> List[Dict[str, Any]]:
        goals = []
        for goal_type, goal in self.data.get("goals", {}).items():
            current = self.data["channel"].get(goal_type, 0)
            target = goal.get("target", 1)
            goals.append({
                "type": goal_type, "current": current, "target": target,
                "progress_pct": current / target * 100 if target > 0 else 0,
                "deadline": goal.get("deadline")
            })
        return goals

    def generate_report(self) -> str:
        report = []
        report.append("=" * 50)
        report.append("  YOUTUBE ANALYTICS REPORT")
        report.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("=" * 50)
        ch = self.data["channel"]
        report.append(f"\n  Channel Stats:")
        report.append(f"    Subscribers: {ch['subscribers']:,}")
        report.append(f"    Total Views: {ch['total_views']:,}")
        report.append(f"    Total Videos: {ch['total_videos']}")
        report.append(f"\n  Top Videos:")
        for v in self.get_top_videos():
            report.append(f"    {v['title'][:40]}: {v['views']:,} views")
        growth = self.get_growth_metrics()
        report.append(f"\n  Growth (30d):")
        report.append(f"    Subscribers: {growth['subscriber_growth']:+,}")
        report.append(f"    Views: {growth['view_growth']:+,}")
        return "\n".join(report)


def main():
    import sys
    analytics = YouTubeAnalytics()

    if len(sys.argv) < 2:
        print("YouTube Analytics")
        print("=" * 40)
        print("\nCommands:")
        print("  report         - Full report")
        print("  subs           - Subscriber count")
        print("  top [n]        - Top videos")
        print("  growth [days]  - Growth metrics")
        print("  goals          - Goals progress")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "report":
        print(analytics.generate_report())
    elif cmd == "subs":
        print(f"Subscribers: {analytics.data['channel']['subscribers']:,}")
    elif cmd == "top":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        for v in analytics.get_top_videos(n):
            print(f"  {v['title'][:40]}: {v['views']:,} views")
    elif cmd == "growth":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        growth = analytics.get_growth_metrics(days)
        print(f"Subscriber growth: {growth['subscriber_growth']:+,}")
        print(f"View growth: {growth['view_growth']:+,}")
    elif cmd == "goals":
        for g in analytics.get_goals_progress():
            print(f"  {g['type']}: {g['current']}/{g['target']} ({g['progress_pct']:.0f}%)")
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
