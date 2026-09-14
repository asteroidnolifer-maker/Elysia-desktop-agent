#!/usr/bin/env python3
"""Daily meme publisher daemon - flips due PRIVATE videos to PUBLIC.

Usage:
  python3 meme_publisher.py --daemon   # detached hourly loop (use setsid to launch)
  python3 meme_publisher.py --run-once # single check (cron/manual/test)
  Reads workspace/meme_schedule.json; items with status=uploaded whose
  scheduled_for <= now get YOUTUBE_UPDATE_VIDEO privacy_status=public.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

WORKSPACE = "/data/elysia/workspace"
MANIFEST = f"{WORKSPACE}/meme_schedule.json"
LOG = f"{WORKSPACE}/meme_publisher.log"
PIDFILE = "/tmp/meme_publisher.pid"
sys.path.insert(0, f"{WORKSPACE}/tools")


def log(msg):
    line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def save_manifest(data):
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, MANIFEST)


def run_once():
    from composio_youtube import execute_tool
    with open(MANIFEST) as f:
        data = json.load(f)
    now = datetime.now(timezone.utc)
    acted = 0
    for it in data["items"]:
        if it.get("status") != "uploaded" or not it.get("youtube_video_id"):
            continue
        try:
            due = datetime.fromisoformat(it["scheduled_for"])
        except Exception:
            continue
        if due > now:
            continue
        vid = it["youtube_video_id"]
        log(f"[day {it['day']}] publishing {vid} ...")
        try:
            res = execute_tool("YOUTUBE_UPDATE_VIDEO",
                               {"video_id": vid, "privacy_status": "public"})
            if res.get("successful"):
                it["status"] = "published"
                it["published_at"] = now.isoformat()
                acted += 1
                log(f"[day {it['day']}] PUBLISHED {vid}")
            else:
                it["error"] = json.dumps(res, default=str)[:300]
                log(f"[day {it['day']}] FAILED: {it['error'][:150]}")
        except Exception as e:
            it["error"] = str(e)[:300]
            log(f"[day {it['day']}] EXCEPTION: {e}")
        save_manifest(data)
    return acted


def is_running():
    if not os.path.isfile(PIDFILE):
        return False
    try:
        with open(PIDFILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def daemon():
    if is_running():
        print("publisher already running")
        return
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    log("publisher daemon started (hourly checks)")
    try:
        while True:
            try:
                n = run_once()
                if n:
                    log(f"check done: published {n}")
            except Exception as e:
                log(f"check error: {e}")
            time.sleep(3600)
    finally:
        try:
            os.remove(PIDFILE)
        except OSError:
            pass


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        daemon()
    else:
        n = run_once()
        print(f"published={n}")
