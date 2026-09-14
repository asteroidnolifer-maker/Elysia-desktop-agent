#!/usr/bin/env python3
"""YouTube Data API v3 - direct upload and management."""
import requests
import json
import os

WORKSPACE = "/data/elysia/workspace/tools"

# YouTube Data API v3 - get your key from https://console.cloud.google.com
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


def search_youtube(query, max_results=10, api_key=None):
    """Search YouTube using Data API v3."""
    key = api_key or YOUTUBE_API_KEY
    if not key:
        return {"error": "No YouTube API key set. Get one from https://console.cloud.google.com"}
    params = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "videoDuration": "short",
        "maxResults": max_results,
        "order": "viewCount",
        "key": key
    }
    r = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
    return r.json()


def get_trending(category_id="0", max_results=10, api_key=None):
    """Get trending videos."""
    key = api_key or YOUTUBE_API_KEY
    if not key:
        return {"error": "No YouTube API key set"}
    params = {
        "part": "snippet",
        "chart": "mostPopular",
        "regionCode": "US",
        "videoCategoryId": category_id,
        "maxResults": max_results,
        "key": key
    }
    r = requests.get("https://www.googleapis.com/youtube/v3/videos", params=params, timeout=15)
    return r.json()


def get_channel_info(channel_id, api_key=None):
    """Get channel details."""
    key = api_key or YOUTUBE_API_KEY
    if not key:
        return {"error": "No YouTube API key set"}
    params = {
        "part": "snippet,statistics",
        "id": channel_id,
        "key": key
    }
    r = requests.get("https://www.googleapis.com/youtube/v3/channels", params=params, timeout=15)
    return r.json()


if __name__ == "__main__":
    if YOUTUBE_API_KEY:
        print("=== YouTube Data API Test ===")
        results = search_youtube("funny cat shorts", 5)
        print(f"Search results: {len(results.get('items', []))}")
        for item in results.get("items", [])[:5]:
            print(f"  - {item['snippet']['title'][:60]}")
    else:
        print("No YouTube API key set.")
        print("Get one from: https://console.cloud.google.com")
        print("Then set: export YOUTUBE_API_KEY=your_key")
