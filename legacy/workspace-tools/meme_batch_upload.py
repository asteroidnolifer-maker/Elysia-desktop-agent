#!/usr/bin/env python3
"""Batch-upload meme manifest videos to YouTube as PRIVATE.

Usage: python3 meme_batch_upload.py [--limit N] [--only-failed]
  Reads workspace/meme_schedule.json, uploads items with status
  rendered/failed, writes back youtube_video_id + status. Logs progress.
  Safe to re-run: skips items already uploaded/published.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

WORKSPACE = "/data/elysia/workspace"
MANIFEST = f"{WORKSPACE}/meme_schedule.json"
LOG = f"{WORKSPACE}/meme_upload.log"
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


def main():
    limit = None
    only_failed = False
    for a in sys.argv[1:]:
        if a.startswith("--limit"):
            limit = int(a.split("=")[1] if "=" in a else sys.argv[sys.argv.index(a) + 1])
        if a == "--only-failed":
            only_failed = True
    from composio_youtube import youtube_upload_file
    with open(MANIFEST) as f:
        data = json.load(f)
    items = data["items"]
    todo = [it for it in items
            if (it.get("status") in ("rendered", "failed") and not it.get("youtube_video_id"))]
    if only_failed:
        todo = [it for it in todo if it.get("status") == "failed"]
    if limit:
        todo = todo[:limit]
    log(f"BATCH START: {len(todo)} to upload ({len(items)} total in manifest)")
    done, failed = 0, 0
    for it in todo:
        day = it["day"]
        try:
            log(f"[day {day}] uploading {os.path.basename(it['file'])} ...")
            res = youtube_upload_file(it["file"], it["title"],
                                      it["description"], tags=it["tags"],
                                      privacy="private")
            vid = None
            try:
                vid = res.get("data", {}).get("video", {}).get("id")
            except Exception:
                pass
            if res.get("successful") and vid:
                it["status"] = "uploaded"
                it["youtube_video_id"] = vid
                done += 1
                log(f"[day {day}] OK video_id={vid}")
            else:
                it["status"] = "failed"
                it["error"] = json.dumps(res, default=str)[:500]
                failed += 1
                log(f"[day {day}] FAILED: {it['error'][:200]}")
        except Exception as e:
            it["status"] = "failed"
            it["error"] = str(e)[:500]
            failed += 1
            log(f"[day {day}] EXCEPTION: {e}")
        save_manifest(data)
        time.sleep(2)
    log(f"BATCH DONE: {done} uploaded, {failed} failed")
    return done, failed


if __name__ == "__main__":
    d, f = main()
    print(f"uploaded={d} failed={f}")
