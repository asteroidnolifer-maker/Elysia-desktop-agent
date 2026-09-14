#!/usr/bin/env python3
"""Elysia meme factory - renders 30 vertical meme Shorts + month schedule manifest.

Usage: python3 meme_factory.py [start_day_offset] [count]
  Renders videos/meme_01.mp4 ... with top/bottom captions (ffmpeg drawtext),
  writes workspace/meme_schedule.json with daily 09:00 UTC slots.
"""
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone

WORKSPACE = "/data/elysia/workspace"
VIDEOS_DIR = f"{WORKSPACE}/videos"
MANIFEST = f"{WORKSPACE}/meme_schedule.json"
FONT = "/usr/share/fonts/liberation/LiberationSans-Bold.ttf"

PALETTE = ["0x1a1a2e", "0x16213e", "0x0f3460", "0x533483",
           "0x1b262c", "0x222831", "0x393e46", "0x2d132c"]

# (TOP, BOTTOM) - original captions
MEMES = [
    ("ME: I'LL JUST FIX ONE BUG", "ALSO ME AT 3AM: REWRITING EVERYTHING"),
    ("POV: YOU SAID IT WORKS ON MY MACHINE", "THE PROD SERVER RIGHT NOW:"),
    ("WHEN THE CODE WORKS", "BUT YOU HAVE NO IDEA WHY"),
    ("ME EXPLAINING MY CODE", "ME READING IT ONE WEEK LATER"),
    ("AI FINISHING MY SENTENCES", "ME: ARE YOU ME?"),
    ("DEPLOY ON A FRIDAY?", "LIVE DANGEROUSLY"),
    ("MY CODE IN DEV", "MY CODE IN PROD"),
    ("WHEN STACK OVERFLOW GOES DOWN", "DEVELOPERS EVERYWHERE SWEATING"),
    ("I DON'T ALWAYS TEST MY CODE", "BUT WHEN I DO, IT'S IN PRODUCTION"),
    ("ME: JUST ONE MORE VIDEO", "YOUTUBE AT 2AM:"),
    ("CLIENT: JUST A SMALL CHANGE", "THE SMALL CHANGE:"),
    ("WHEN WIFI DROPS IN A MEETING", "MY FACE FROZEN MID SENTENCE"),
    ("AI WILL REPLACE DEVELOPERS", "AI TRYING TO CENTER A DIV:"),
    ("MEAL PREP INFLUENCERS", "ME EATING CEREAL FOR DINNER AGAIN"),
    ("FINALLY FOUND THE BUG", "IT WAS A MISSING SEMICOLON"),
    ("MY SLEEP SCHEDULE", "POWERED BY CAFFEINE AND DEADLINES"),
    ("TUTORIAL: EASY 5 MINUTE PROJECT", "ME 6 HOURS LATER:"),
    ("JUST GOOGLE IT, THEY SAID", "GOOGLE: TURN IT OFF AND ON AGAIN?"),
    ("MONDAY MORNING ALARM", "ME NEGOTIATING 5 MORE MINUTES"),
    ("CLOUD: UNLIMITED STORAGE", "MY PHONE: STORAGE FULL"),
    ("TEST PASSES ON FIRST TRY", "SOMETHING IS DEFINITELY WRONG"),
    ("ME: I'M GOOD WITH MONEY", "ALSO ME: BUYS A 4TH MONITOR"),
    ("SENIOR DEV CODE REVIEW", "LGTM (DID NOT READ IT)"),
    ("AUTOCORRECT: DEPLOY TO DESTROY", "MESSAGE ALREADY SENT"),
    ("I'LL WATER YOU TOMORROW", "MY PLANTS ON DAY 47:"),
    ("OPENING THE FRIDGE 5TH TIME", "STILL NOTHING. STILL CHECKING."),
    ("MICROWAVE HITS 0:00", "ME OPENING AT 0:01 LIKE A GENTLEMAN"),
    ("DAY 1 AT THE GYM", "DAY 2: CANNOT FEEL MY ARMS"),
    ("WHEN YOU FINALLY GET RECURSION", "WHEN YOU FINALLY GET RECURSION"),
    ("ME CLOSING 47 TABS", "THE ONE TAB PLAYING MUSIC:"),
]


def wrap(text, width=18):
    return "\n".join(textwrap.wrap(text, width=width))


def render_meme(idx, top, bottom, out_path):
    bg = PALETTE[idx % len(PALETTE)]
    top_f = f"/tmp/meme_top_{idx}.txt"
    bot_f = f"/tmp/meme_bot_{idx}.txt"
    with open(top_f, "w") as f:
        f.write(wrap(top))
    with open(bot_f, "w") as f:
        f.write(wrap(bottom))
    vf = (
        f"drawtext=fontfile={FONT}:textfile={top_f}:fontcolor=white:"
        f"fontsize=80:borderw=3:bordercolor=black:x=(w-text_w)/2:y=200,"
        f"drawtext=fontfile={FONT}:textfile={bot_f}:fontcolor=yellow:"
        f"fontsize=80:borderw=3:bordercolor=black:x=(w-text_w)/2:y=h-620,"
        f"drawtext=fontfile={FONT}:text='@ELYSIA MEMES':fontcolor=white@0.7:"
        f"fontsize=40:x=(w-text_w)/2:y=h-140,"
        f"fade=t=in:st=0:d=0.5,fade=t=out:st=7.3:d=0.7"
    )
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
           f"color=c={bg}:s=1080x1920:d=8:r=30",
           "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    for p in (top_f, bot_f):
        try:
            os.remove(p)
        except OSError:
            pass
    if r.returncode != 0 or not os.path.isfile(out_path):
        return {"status": "failed", "error": r.stderr[:300]}
    return {"status": "ok", "file": out_path,
            "size": os.path.getsize(out_path)}


def build_schedule(start_offset=1, count=30, hour=9):
    os.makedirs(VIDEOS_DIR, exist_ok=True)
    base = (datetime.now(timezone.utc).replace(hour=hour, minute=0,
                                               second=0, microsecond=0)
            + timedelta(days=start_offset))
    manifest = []
    memes = (MEMES * ((count // len(MEMES)) + 1))[:count]
    for i, (top, bottom) in enumerate(memes):
        day = base + timedelta(days=i)
        fname = f"meme_{i+1:02d}.mp4"
        fpath = os.path.join(VIDEOS_DIR, fname)
        print(f"[{i+1}/{count}] rendering {fname} ...", flush=True)
        res = render_meme(i, top, bottom, fpath)
        if res["status"] != "ok":
            print(f"  FAILED: {res.get('error')}", flush=True)
            continue
        title = f"{top.title()} Vs {bottom.title()}"[:95] + " #shorts"
        manifest.append({
            "day": i + 1,
            "scheduled_for": day.isoformat(),
            "file": fpath,
            "title": title,
            "description": (f"{top} ... {bottom}\n\nDaily meme #{i+1} by "
                            f"Elysia #memes #funny #shorts #comedy #viral"),
            "tags": ["memes", "funny", "shorts", "comedy", "viral",
                     "elysia"],
            "privacy": "private",   # uploaded private, publisher flips to public
            "status": "rendered",
            "youtube_video_id": None,
            "published_at": None,
        })
        print(f"  ok ({res['size']//1024}KB) -> {day.date()}", flush=True)
    with open(MANIFEST, "w") as f:
        json.dump({"created": datetime.now(timezone.utc).isoformat(),
                   "items": manifest}, f, indent=1)
    print(f"[+] {len(manifest)}/{count} rendered, manifest: {MANIFEST}")
    return manifest


if __name__ == "__main__":
    off = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    cnt = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    build_schedule(off, cnt)
