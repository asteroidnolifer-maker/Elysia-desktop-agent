#!/usr/bin/env python3
"""Task #1465: Social media auto-poster."""
import json, os, random
from datetime import datetime, timedelta

WORKSPACE = "/data/elysia/workspace/tools"

PLATFORMS = {
    "instagram": {"max_len": 2200, "best_times": ["9am", "12pm", "7pm"], "content_types": ["image", "carousel", "reel"]},
    "facebook": {"max_len": 63206, "best_times": ["1pm", "4pm"], "content_types": ["text", "image", "video", "link"]},
    "twitter": {"max_len": 280, "best_times": ["8am", "12pm", "5pm"], "content_types": ["text", "image", "thread"]},
    "tiktok": {"max_len": 300, "best_times": ["7am", "12pm", "7pm"], "content_types": ["video"]},
    "pinterest": {"max_len": 500, "best_times": ["8pm", "11pm"], "content_types": ["pin", "carousel"]},
}

def schedule_post(content, platform, scheduled_time=None):
    """Schedule a social media post."""
    info = PLATFORMS.get(platform, PLATFORMS["instagram"])
    if not scheduled_time:
        scheduled_time = (datetime.now() + timedelta(hours=random.randint(1, 48))).isoformat()
    hashtags = " ".join(f"#{w.lower()}" for w in content.split()[:5])
    return {
        "platform": platform,
        "content": content[:info["max_len"]],
        "scheduled": scheduled_time,
        "content_type": random.choice(info["content_types"]),
        "hashtags": hashtags,
        "best_times": info["best_times"],
        "status": "scheduled"
    }

def generate_content_ideas(niche):
    """Generate content ideas for a niche."""
    templates = {
        "fashion": ["Outfit of the day", "Style tips", "Behind the scenes", "Customer spotlight"],
        "tech": ["Product demo", "Unboxing", "Tips and tricks", "Comparison review"],
        "fitness": ["Workout routine", "Meal prep", "Progress update", "Motivation Monday"],
        "food": ["Recipe of the day", "Kitchen hacks", "Restaurant review", "Food styling"],
    }
    ideas = templates.get(niche.lower(), templates["tech"])
    return [{"idea": idea, "platforms": ["instagram", "facebook"], "content_type": "image"} for idea in ideas]

if __name__ == "__main__":
    result = schedule_post("Check out our new product launch!", "instagram")
    ideas = generate_content_ideas("tech")
    print(f"Scheduled post for {result['platform']}: {result['content'][:50]}...")
    print(f"\nContent ideas for tech:")
    for i in ideas:
        print(f"  - {i['idea']}")
    output = os.path.join(WORKSPACE, "social_scheduler.json")
    with open(output, 'w') as f:
        json.dump({"post": result, "ideas": ideas}, f, indent=2)
    print(f"[+] Saved to {output}")
