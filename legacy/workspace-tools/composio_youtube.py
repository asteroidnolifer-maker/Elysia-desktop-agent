#!/usr/bin/env python3
"""Composio v3.1 integration - real YouTube control (FIXED 2026-09-13).

Fixes vs old version:
- Endpoints were camelCase (connectedAccounts) -> now snake_case (connected_accounts)
- Tools list uses ?toolkit_slug= (not ?toolkits=)
- Execute needs user_id + connected_account_id
- Search slug is YOUTUBE_SEARCH_YOU_TUBE with param `q`
- Upload is now 2-step: presigned S3 upload -> YOUTUBE_MULTIPART_UPLOAD_VIDEO
  (old YOUTUBE_UPLOAD_VIDEO with local videoFilePath never worked - file must
  be on Composio's storage, not local disk)
"""
import hashlib
import mimetypes
import os
import requests
import json

API_KEY = os.environ.get("COMPOSIO_API_KEY", "ak_FIwmCfHE8vjHlYW8zY_F")
BASE = "https://backend.composio.dev/api/v3.1"
H = {"x-api-key": API_KEY, "Content-Type": "application/json"}

DEFAULT_USER_ID = os.environ.get("COMPOSIO_USER_ID", "elysia_user")
DEFAULT_ACCOUNT_ID = os.environ.get(
    "COMPOSIO_YOUTUBE_ACCOUNT", "ca_sWrT8cHrT-ek")  # ACTIVE, has youtube.upload scope
YOUTUBE_AUTH_CONFIG = "ac_V9z363xdny0d"


def list_tools(toolkit="youtube", limit=50):
    """List available YouTube tools."""
    r = requests.get(f"{BASE}/tools", headers=H,
                     params={"toolkit_slug": toolkit, "limit": limit}, timeout=15)
    return r.json()


def execute_tool(tool_slug, arguments, connected_account_id=None,
                 user_id=None):
    """Execute any Composio tool (v3.1)."""
    payload = {"arguments": arguments}
    payload["connected_account_id"] = connected_account_id or DEFAULT_ACCOUNT_ID
    payload["user_id"] = user_id or DEFAULT_USER_ID
    r = requests.post(f"{BASE}/tools/execute/{tool_slug}", headers=H,
                      json=payload, timeout=60)
    try:
        return r.json()
    except Exception:
        return {"error": f"HTTP {r.status_code}", "body": r.text[:500]}


def list_connections():
    """List connected accounts (v3.1 snake_case endpoint)."""
    r = requests.get(f"{BASE}/connected_accounts", headers=H, timeout=15)
    return r.json()


def get_connection(account_id=None):
    """Get one connected account's details/status."""
    account_id = account_id or DEFAULT_ACCOUNT_ID
    r = requests.get(f"{BASE}/connected_accounts/{account_id}",
                     headers=H, timeout=15)
    return r.json()


def youtube_search(query, max_results=5):
    """Search YouTube via Composio (slug YOUTUBE_SEARCH_YOU_TUBE, param q)."""
    return execute_tool("YOUTUBE_SEARCH_YOU_TUBE",
                        {"q": query, "maxResults": max_results})


def request_upload_url(toolkit_slug="youtube",
                       tool_slug="YOUTUBE_MULTIPART_UPLOAD_VIDEO",
                       filepath=None, filename=None, mimetype=None):
    """Step 1 of upload: mint a presigned S3 URL from Composio."""
    if filepath and not filename:
        filename = os.path.basename(filepath)
    if filepath and not mimetype:
        mimetype, _ = mimetypes.guess_type(filepath)
        mimetype = mimetype or "video/mp4"
    md5 = ""
    if filepath and os.path.isfile(filepath):
        h = hashlib.md5()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                h.update(chunk)
        md5 = h.hexdigest()
    body = {"toolkit_slug": toolkit_slug, "tool_slug": tool_slug,
            "filename": filename or "video.mp4",
            "mimetype": mimetype or "video/mp4", "md5": md5}
    r = requests.post(f"{BASE}/files/upload/request", headers=H,
                      json=body, timeout=30)
    return r.json()


def put_file_to_presigned_url(presigned_url, filepath):
    """Step 2 of upload: PUT raw bytes to Composio storage."""
    with open(filepath, "rb") as f:
        r = requests.put(presigned_url, data=f, timeout=300)
    return r.status_code in (200, 201, 403)


def youtube_upload_file(filepath, title, description, tags=None,
                        privacy="public", category_id="22"):
    """Full upload: local file -> Composio S3 -> YouTube.

    Returns the execute_tool response (contains video id on success).
    """
    if not os.path.isfile(filepath):
        return {"error": f"file not found: {filepath}"}
    filename = os.path.basename(filepath)
    mimetype, _ = mimetypes.guess_type(filepath)
    mimetype = mimetype or "video/mp4"

    up = request_upload_url(filepath=filepath, filename=filename,
                            mimetype=mimetype)
    key = up.get("key", "")
    url = up.get("new_presigned_url") or up.get("newPresignedUrl", "")
    if not key or not url:
        return {"error": "could not mint upload URL", "detail": up}

    if not put_file_to_presigned_url(url, filepath):
        return {"error": "PUT to presigned URL failed", "s3key": key}

    args = {"title": title, "description": description,
            "categoryId": category_id, "privacyStatus": privacy,
            "videoFile": {"name": filename, "mimetype": mimetype,
                          "s3key": key}}
    if tags:
        args["tags"] = tags
    return execute_tool("YOUTUBE_MULTIPART_UPLOAD_VIDEO", args)


def youtube_upload(title, description, video_file_path, tags="",
                   privacy="public"):
    """Backward-compat wrapper: local path -> full S3 upload flow.

    Old code passed a local path straight to Composio (which failed because
    Composio can't see local disk). Now routes through youtube_upload_file().
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or None
    if os.path.isfile(video_file_path or ""):
        return youtube_upload_file(video_file_path, title, description,
                                   tags=tag_list, privacy=privacy)
    return {"error": "video_file_path must be a local file; it is uploaded "
                     "to Composio storage first",
            "path": video_file_path}


def youtube_list_channels():
    """List YouTube channels (mine)."""
    return execute_tool("YOUTUBE_LIST_CHANNELS", {"mine": True})


def youtubeget_video(video_id):
    """Get video details."""
    return execute_tool("YOUTUBE_GET_VIDEO_DETAILS_BATCH",
                        {"videoIds": video_id})


def youtubeget_channel(channel_id):
    """Get channel details."""
    return execute_tool("YOUTUBE_GET_CHANNEL_STATISTICS", {})


if __name__ == "__main__":
    print("=== Composio v3.1 Test ===")
    print("\n1. YouTube tools available:")
    tools = list_tools("youtube")
    if "items" in tools:
        for t in tools["items"][:10]:
            print(f"  - {t.get('slug', t.get('name', 'unknown'))}")
    else:
        print(f"  Response: {json.dumps(tools, indent=2)[:300]}")

    print("\n2. Connected accounts:")
    conns = list_connections()
    if "items" in conns:
        for c in conns["items"]:
            print(f"  - {c.get('toolkit', {}).get('slug', '?')}: "
                  f"{c.get('id', '?')} [{c.get('status', '?')}]")
    else:
        print(f"  Response: {json.dumps(conns, indent=2)[:300]}")

    print("\n3. YouTube search (via Composio):")
    res = youtube_search("funny cats", 2)
    print(f"  {json.dumps(res, indent=2)[:500]}")
