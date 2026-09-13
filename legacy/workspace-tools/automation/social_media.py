#!/usr/bin/env python3
"""
Elysia Social Media Automation - Task 1807
Post scheduling, content calendar, cross-platform posting.
"""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


class SocialPost:
    def __init__(self, content: str, platforms: List[str],
                 media: List[str] = None, tags: List[str] = None):
        self.id = f"post_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.content = content
        self.platforms = platforms
        self.media = media or []
        self.tags = tags or []
        self.status = "draft"
        self.created_at = datetime.now().isoformat()
        self.scheduled_at = None
        self.published_at = None
        self.metrics: Dict[str, int] = {"likes": 0, "shares": 0, "comments": 0}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "content": self.content, "platforms": self.platforms,
            "media": self.media, "tags": self.tags, "status": self.status,
            "created_at": self.created_at, "scheduled_at": self.scheduled_at,
            "published_at": self.published_at, "metrics": self.metrics
        }


class SocialMediaAutomation:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "social")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.posts: List[SocialPost] = []
        self.content_calendar: Dict[str, List[str]] = {}
        self.platforms = ["twitter", "linkedin", "facebook", "instagram", "mastodon"]

    def create_post(self, content: str, platforms: List[str],
                    media: List[str] = None, tags: List[str] = None) -> SocialPost:
        post = SocialPost(content, platforms, media, tags)
        self.posts.append(post)
        return post

    def schedule_post(self, post_id: str, scheduled_at: str) -> bool:
        for post in self.posts:
            if post.id == post_id:
                post.scheduled_at = scheduled_at
                post.status = "scheduled"
                date_key = scheduled_at[:10]
                if date_key not in self.content_calendar:
                    self.content_calendar[date_key] = []
                self.content_calendar[date_key].append(post_id)
                return True
        return False

    def publish_post(self, post_id: str) -> Dict[str, Any]:
        for post in self.posts:
            if post.id == post_id:
                post.status = "published"
                post.published_at = datetime.now().isoformat()
                return {"status": "published", "platforms": post.platforms,
                        "post_id": post_id}
        return {"error": "Post not found"}

    def get_calendar(self, month: str = None) -> Dict[str, List[Dict]]:
        month = month or datetime.now().strftime("%Y-%m")
        calendar = {}
        for date_key, post_ids in self.content_calendar.items():
            if date_key.startswith(month):
                calendar[date_key] = [
                    {"id": pid, "content": self._get_post_content(pid)[:50]}
                    for pid in post_ids
                ]
        return calendar

    def _get_post_content(self, post_id: str) -> str:
        for post in self.posts:
            if post.id == post_id:
                return post.content
        return ""

    def get_analytics(self) -> Dict[str, Any]:
        total = {"likes": 0, "shares": 0, "comments": 0}
        by_platform = {}
        for post in self.posts:
            for platform in post.platforms:
                if platform not in by_platform:
                    by_platform[platform] = {"posts": 0, "likes": 0, "shares": 0}
                by_platform[platform]["posts"] += 1
            for metric, val in post.metrics.items():
                total[metric] += val
        return {"total_posts": len(self.posts), "total_engagement": total,
                "by_platform": by_platform}

    def get_queue(self) -> List[Dict[str, Any]]:
        return [p.to_dict() for p in self.posts if p.status in ("draft", "scheduled")]

    def generate_content_ideas(self, niche: str = "tech") -> List[Dict[str, str]]:
        ideas = {
            "tech": [
                "5 tools every developer needs in 2026",
                "Why I switched to open source",
                "Building AI agents - a beginner's guide",
                "The future of local LLMs",
                "How I automated my workflow"
            ],
            "finance": [
                "3 investment mistakes I made",
                "Building a side hustle with coding",
                "Financial independence roadmap",
                "Crypto vs stocks - my strategy",
                "Automating your finances"
            ]
        }
        return [{"title": t, "platform": "all"} for t in ideas.get(niche, ideas["tech"])]


def main():
    automation = SocialMediaAutomation()

    if len(sys.argv) < 2:
        print("Elysia Social Media Automation")
        print("Commands: create, schedule, publish, calendar, queue, ideas [niche]")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "create" and len(sys.argv) >= 4:
        platforms = sys.argv[3].split(",")
        post = automation.create_post(sys.argv[2], platforms)
        print(f"[+] Post created: {post.id}")
    elif cmd == "schedule" and len(sys.argv) >= 4:
        automation.schedule_post(sys.argv[2], sys.argv[3])
        print(f"[+] Scheduled")
    elif cmd == "publish" and len(sys.argv) >= 3:
        result = automation.publish_post(sys.argv[2])
        print(json.dumps(result, indent=2))
    elif cmd == "calendar":
        calendar = automation.get_calendar()
        for date, posts in calendar.items():
            print(f"  {date}: {len(posts)} posts")
    elif cmd == "queue":
        queue = automation.get_queue()
        for p in queue:
            print(f"  [{p['status']}] {p['content'][:50]}...")
    elif cmd == "ideas":
        niche = sys.argv[2] if len(sys.argv) > 2 else "tech"
        ideas = automation.generate_content_ideas(niche)
        for i in ideas:
            print(f"  - {i['title']}")
    elif cmd == "analytics":
        print(json.dumps(automation.get_analytics(), indent=2))


if __name__ == "__main__":
    main()
