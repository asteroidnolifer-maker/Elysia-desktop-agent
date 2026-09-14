#!/usr/bin/env python3
"""YouTube channel scheduler - manages posting to hundreds of channels."""
import json
import os
import sqlite3
from datetime import datetime, timedelta
import random

WORKSPACE = "/data/elysia/workspace/tools"
DB_PATH = "/data/elysia/workspace/scheduler.sqlite"


def init_scheduler_db():
    """Initialize scheduler database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS channels (
        id INTEGER PRIMARY KEY, name TEXT, niche TEXT, subscribers INTEGER,
        api_key TEXT, upload_hour INTEGER DEFAULT 14, timezone TEXT DEFAULT 'EST',
        posting_enabled INTEGER DEFAULT 1, max_daily_uploads INTEGER DEFAULT 3,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS scheduled_videos (
        id INTEGER PRIMARY KEY, channel_id INTEGER, title TEXT, description TEXT,
        tags TEXT, video_path TEXT, thumbnail_path TEXT,
        scheduled_time TEXT, status TEXT DEFAULT 'pending',
        youtube_video_id TEXT, views INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (channel_id) REFERENCES channels(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS upload_log (
        id INTEGER PRIMARY KEY, channel_id INTEGER, video_id INTEGER,
        action TEXT, result TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn


def add_channel(name, niche, subscribers=0, api_key=None, upload_hour=14):
    """Add a YouTube channel to manage."""
    conn = init_scheduler_db()
    c = conn.cursor()
    c.execute("INSERT INTO channels (name, niche, subscribers, api_key, upload_hour) VALUES (?, ?, ?, ?, ?)",
              (name, niche, subscribers, api_key, upload_hour))
    conn.commit()
    channel_id = c.lastrowid
    conn.close()
    return {"channel_id": channel_id, "name": name, "status": "added"}


def schedule_video(channel_id, title, description, tags, video_path, scheduled_time=None):
    """Schedule a video for a channel."""
    conn = init_scheduler_db()
    c = conn.cursor()
    if not scheduled_time:
        c.execute("SELECT upload_hour FROM channels WHERE id=?", (channel_id,))
        row = c.fetchone()
        hour = row[0] if row else 14
        scheduled_time = (datetime.now().replace(hour=hour, minute=0) + timedelta(days=random.randint(1, 7))).isoformat()
    tags_str = ",".join(tags) if isinstance(tags, list) else tags
    c.execute("INSERT INTO scheduled_videos (channel_id, title, description, tags, video_path, scheduled_time) VALUES (?, ?, ?, ?, ?, ?)",
              (channel_id, title, description, tags_str, video_path, scheduled_time))
    conn.commit()
    video_id = c.lastrowid
    conn.close()
    return {"video_id": video_id, "scheduled": scheduled_time, "channel_id": channel_id}


def get_pending_uploads():
    """Get all videos ready for upload."""
    conn = init_scheduler_db()
    c = conn.cursor()
    c.execute("""SELECT sv.id, sv.title, sv.scheduled_time, c.name, c.niche, c.api_key
                 FROM scheduled_videos sv JOIN channels c ON sv.channel_id=c.id
                 WHERE sv.status='pending' AND sv.scheduled_time <= ?""",
              (datetime.now().isoformat(),))
    pending = [{"video_id": r[0], "title": r[1], "scheduled": r[2], "channel": r[3], "niche": r[4], "has_api_key": bool(r[5])} for r in c.fetchall()]
    conn.close()
    return pending


def bulk_schedule(channel_ids, topics, niche="general"):
    """Schedule videos across multiple channels."""
    results = []
    for ch_id in channel_ids:
        for topic in topics:
            result = schedule_video(ch_id, f"{topic} - {niche.title()}", f"Check out {topic}!", [niche, topic], f"/tmp/{topic}.mp4")
            results.append(result)
    return {"scheduled": len(results), "details": results}


def get_scheduler_stats():
    """Get scheduler statistics."""
    conn = init_scheduler_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM channels")
    total_channels = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM scheduled_videos WHERE status='pending'")
    pending = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM scheduled_videos WHERE status='done'")
    uploaded = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM channels WHERE posting_enabled=1")
    active = c.fetchone()[0]
    conn.close()
    return {"total_channels": total_channels, "active_channels": active, "pending_uploads": pending, "completed_uploads": uploaded}


if __name__ == "__main__":
    print("=== YouTube Channel Scheduler ===")
    conn = init_scheduler_db()
    for i in range(20):
        add_channel(f"Channel_{i+1}", random.choice(["tech", "finance", "gaming", "cooking", "fitness"]), random.randint(1000, 100000))
    stats = get_scheduler_stats()
    print(f"Channels: {stats['total_channels']} ({stats['active_channels']} active)")
    channel_ids = list(range(1, 6))
    topics = ["5 AI Tools You Need", "How to Save Money", "Daily Productivity Hack"]
    result = bulk_schedule(channel_ids, topics, "tech")
    print(f"Scheduled {result['scheduled']} videos across {len(channel_ids)} channels")
    pending = get_pending_uploads()
    print(f"Pending uploads: {len(pending)}")
    for p in pending[:3]:
        print(f"  {p['channel']}: {p['title'][:50]}")
    output = os.path.join(WORKSPACE, "scheduler_stats.json")
    with open(output, "w") as f:
        json.dump({"stats": stats, "pending": pending[:5]}, f, indent=2)
    print(f"[+] Saved to {output}")
