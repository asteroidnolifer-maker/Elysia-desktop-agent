#!/usr/bin/env python3
"""Elysia Master Agent v2 - uses web research as primary intelligence."""
import json
import os
import sys
import sqlite3
import requests
import time
from datetime import datetime

WORKSPACE = "/data/elysia/workspace"
TOOLS_DIR = f"{WORKSPACE}/tools"
VIDEOS_DIR = f"{WORKSPACE}/videos"
DB_PATH = f"{WORKSPACE}/elysia_master.db"

sys.path.insert(0, TOOLS_DIR)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_request TEXT, task_type TEXT, status TEXT DEFAULT 'pending',
        plan TEXT, result TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS agent_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER, agent TEXT, action TEXT,
        input_text TEXT, output_text TEXT,
        timestamp TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    return conn


def classify_task(request):
    r = request.lower()
    rules = [
        (["youtube", "video", "shorts", "upload", "channel"], "youtube"),
        (["meme", "funny", "humor", "comedy"], "meme"),
        (["dropship", "product", "shopify", "amazon", "ecommerce", "sell"], "ecommerce"),
        (["crypto", "bitcoin", "ethereum", "solana", "coin"], "crypto"),
        (["stock", "trade", "invest", "ticker", "buy", "sell", "market", "share"], "stock"),
        (["search", "find", "look up", "research", "google"], "research"),
        (["code", "script", "program", "function"], "code"),
        (["write", "blog", "article", "post", "content"], "content"),
        (["automate", "schedule", "batch", "bulk"], "automation"),
        (["analyze", "data", "report"], "analysis"),
    ]
    for keywords, task_type in rules:
        if any(kw in r for kw in keywords):
            return task_type
    return "general"


def log_agent(task_id, agent, action, input_text, output_text):
    conn = init_db()
    c = conn.cursor()
    c.execute("INSERT INTO agent_log (task_id, agent, action, input_text, output_text) VALUES (?, ?, ?, ?, ?)",
              (task_id, agent, action, str(input_text)[:2000], str(output_text)[:2000]))
    conn.commit()
    conn.close()


def web_search(query, num=5):
    """Search the web using DuckDuckGo."""
    try:
        from web_research import search_duckduckgo
        return search_duckduckgo(query, num)
    except Exception as e:
        return {"error": str(e), "results": []}


def web_fetch(url):
    """Fetch a web page."""
    try:
        from web_research import fetch_page
        return fetch_page(url)
    except Exception as e:
        return {"error": str(e)}


def _infer_youtube_category(query):
    """Map free-text query to a youtube_research scraping category."""
    q = (query or "").lower()
    mapping = [
        (["tech", "ai", "gadget", "software", "coding", "python"], "tech"),
        (["funny", "comedy", "meme", "humor", "prank", "cat"], "comedy"),
        (["game", "gaming", "minecraft", "fortnite"], "gaming"),
        (["cook", "food", "recipe", "kitchen"], "cooking"),
        (["fitness", "workout", "gym", "health"], "fitness"),
        (["finance", "money", "stock", "crypto", "invest", "trading"], "finance"),
        (["fashion", "outfit", "style", "beauty"], "fashion"),
        (["learn", "education", "tutorial", "science", "history"], "education"),
        (["music", "song", "dance", "beat"], "music"),
    ]
    for keywords, cat in mapping:
        if any(kw in q for kw in keywords):
            return cat
    return "general"


def _normalize_composio_search(res, query, num):
    """Extract a trending_videos list from a Composio execute response."""
    videos = []
    data = res
    if isinstance(res, dict):
        # common wrappers: {data: ...} / {result: ...} / {response: ...}
        for key in ("data", "result", "response", "output"):
            if key in res and isinstance(res[key], (dict, list)):
                data = res[key]
                break
    items = []
    if isinstance(data, dict):
        for key in ("items", "videos", "results", "searchResults"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        else:
            # single video dict?
            if data.get("title") or data.get("videoId"):
                items = [data]
    elif isinstance(data, list):
        items = data
    for it in items[:num]:
        if not isinstance(it, dict):
            continue
        # YouTube Data API v3 shape (via Composio): {id: {videoId},
        # snippet: {title, channelTitle, publishedAt, description}}
        snip = it.get("snippet") if isinstance(it.get("snippet"), dict) else {}
        idobj = it.get("id", "")
        if isinstance(idobj, dict):
            vid = idobj.get("videoId", "")
        else:
            vid = (it.get("videoId") or it.get("video_id") or idobj or "")
        title = snip.get("title", it.get("title", ""))
        if isinstance(title, dict):  # some APIs nest title.runs
            runs = title.get("runs") or []
            title = runs[0].get("text", "") if runs else str(title)
        channel = (snip.get("channelTitle") or it.get("channel")
                   or it.get("channelTitle") or it.get("channelId", ""))
        published = (snip.get("publishedAt") or it.get("published")
                     or it.get("publishedAt", "N/A"))
        videos.append({
            "title": str(title),
            "video_id": str(vid),
            "url": f"https://youtube.com/watch?v={vid}" if vid else it.get("url", ""),
            "views": it.get("views", it.get("viewCount", "N/A")),
            "duration": it.get("duration", "N/A"),
            "channel": str(channel),
            "published": str(published),
        })
    return videos


def youtube_search(query, num=5):
    """Search YouTube: Composio API primary, scraping fallback.

    Previously ignored `query` (always searched "general"). Now honors
    both args. Returns {"query", "source", "trending_videos", "count"}.
    """
    query = (query or "").strip() or "general"
    try:
        num = max(1, min(int(num or 5), 20))
    except (TypeError, ValueError):
        num = 5
    composio_error = ""
    try:
        from composio_youtube import youtube_search as composio_search
        res = composio_search(query, num)
        if isinstance(res, dict) and res.get("error") and not res.get("data"):
            composio_error = str(res.get("error"))[:200]
        else:
            videos = _normalize_composio_search(res, query, num)
            if videos:
                return {"query": query, "source": "composio",
                        "trending_videos": videos, "count": len(videos)}
            composio_error = f"no videos parsed from: {str(res)[:200]}"
    except Exception as e:
        composio_error = str(e)[:200]
    try:
        from youtube_research import search_youtube_trending
        fallback = search_youtube_trending(_infer_youtube_category(query))
        fallback["query"] = query
        fallback["source"] = "scrape"
        if composio_error:
            fallback["composio_note"] = f"primary failed ({composio_error}), used scrape fallback"
        vids = fallback.get("trending_videos", [])[:num]
        fallback["trending_videos"] = vids
        fallback["count"] = len(vids)
        return fallback
    except Exception as e:
        return {"query": query, "source": "none", "error": str(e)[:200],
                "composio_error": composio_error, "trending_videos": []}


def try_agent_upload(request, task_id):
    """Upload intent: pick a video from workspace/videos/ and upload via Composio.

    Privacy parsed from request text (private|unlisted|public, default unlisted).
    Returns dict with file/privacy/response (or error).
    """
    import glob
    import re
    rl = request.lower()
    privacy = "unlisted"
    for p in ("private", "unlisted", "public"):
        if re.search(r"\b" + p + r"\b", rl):
            privacy = p
            break
    pattern = os.path.join(VIDEOS_DIR, "*.mp4")
    candidates = sorted(glob.glob(pattern), key=os.path.getmtime)
    picked = None
    for c in candidates:
        base = os.path.basename(c).lower()
        stem = os.path.splitext(base)[0].replace("_", " ")
        if base in rl or stem in rl:
            picked = c
            break
    if not picked and candidates:
        picked = candidates[-1]  # newest
    if not picked:
        return {"error": f"no .mp4 files in {VIDEOS_DIR}/ - generate one first"}
    # derive title from request, stripped of command words
    title = re.sub(r"\b(upload|to\s+(my\s+)?(youtube|yt)\s*(channel)?|as\s+(private|unlisted|public)|please|my|the|a|video|videos)\b",
                   " ", request, flags=re.I)
    title = re.sub(r"\s+", " ", title).strip(" -.,")[:100]
    if len(title) < 5:
        title = os.path.splitext(os.path.basename(picked))[0].replace("_", " ")
    description = (f"{title}\n\nUploaded by Elysia Master Agent "
                   f"({datetime.now().isoformat(timespec='seconds')}) #shorts")
    print(f"  [UPLOAD] File: {picked} -> privacy={privacy}")
    try:
        from composio_youtube import youtube_upload_file
        res = youtube_upload_file(picked, title, description,
                                  tags=["elysia", "aitest", "shorts"],
                                  privacy=privacy)
        log_agent(task_id, "composio_youtube", "upload",
                  f"{picked} [{privacy}]",
                  json.dumps(res, default=str)[:1000])
        return {"file": picked, "title": title, "privacy": privacy,
                "response": res}
    except Exception as e:
        return {"file": picked, "privacy": privacy, "error": str(e)}


def orchestrate_meme_schedule(request, task_id):
    """Meme-month orchestration: render batch -> detached private upload ->
    publisher daemon for daily public release. Returns summary dict."""
    import glob
    import re
    import subprocess
    rl = request.lower()
    m = re.search(r"(\d+)\s*(meme|video|short)", rl)
    count = int(m.group(1)) if m else 30
    count = max(1, min(count, 30))
    log_agent(task_id, "orchestrator", "meme_schedule_start", request,
              f"count={count}")

    # 1) render (skip if manifest already has enough rendered files)
    manifest_path = f"{WORKSPACE}/meme_schedule.json"
    have = len(glob.glob(os.path.join(VIDEOS_DIR, "meme_*.mp4")))
    if have >= count:
        print(f"  [MEME] {have} videos already rendered, skipping factory...")
        factory = {"status": "skipped", "have": have}
    else:
        print(f"  [MEME] Rendering {count} meme videos (have {have})...")
        try:
            p = subprocess.run(
                [sys.executable, os.path.join(TOOLS_DIR, "meme_factory.py"),
                 "1", str(count)],
                capture_output=True, text=True, timeout=1500)
            factory = {"status": "ok" if p.returncode == 0 else "failed",
                       "tail": (p.stdout + p.stderr)[-500:]}
            print(f"  [MEME] Factory: {factory['status']}")
        except Exception as e:
            factory = {"status": "failed", "error": str(e)}
    log_agent(task_id, "meme_factory", "render", f"count={count}",
              json.dumps(factory, default=str)[:1000])

    # 2) detached batch upload (private) - returns immediately
    with open(os.devnull, "w") as dn:
        subprocess.Popen(
            ["setsid", sys.executable,
             os.path.join(TOOLS_DIR, "meme_batch_upload.py")],
            stdin=dn, stdout=dn, stderr=dn, start_new_session=True)
    print("  [MEME] Batch uploader launched (detached, private uploads)...")

    # 3) publisher daemon (idempotent - exits if already running)
    with open(os.devnull, "w") as dn:
        subprocess.Popen(
            ["setsid", sys.executable,
             os.path.join(TOOLS_DIR, "meme_publisher.py"), "--daemon"],
            stdin=dn, stdout=dn, stderr=dn, start_new_session=True)
    print("  [MEME] Publisher daemon started (daily public release)...")

    try:
        with open(manifest_path) as f:
            man = json.load(f)
        items = man.get("items", [])[:count]
        summary = {"count": count, "factory": factory,
                   "uploader": "detached (see workspace/meme_upload.log)",
                   "publisher": "daemon hourly (see workspace/meme_publisher.log)",
                   "first": items[0]["scheduled_for"] if items else None,
                   "last": items[-1]["scheduled_for"] if items else None}
    except Exception as e:
        summary = {"count": count, "factory": factory,
                   "manifest_error": str(e)}
    log_agent(task_id, "orchestrator", "meme_schedule_done", request,
              json.dumps(summary, default=str)[:1000])
    return summary


def execute_task(task_id, task_type, request):
    """Execute a task based on its type."""
    results = {}

    if task_type == "youtube" or task_type == "meme":
        # Month-schedule intent: "generate N memes and schedule ... month/daily"
        rl = request.lower()
        if ("meme" in rl or task_type == "meme") and (
                "schedul" in rl or "month" in rl or "daily" in rl):
            print("  [MEME] Schedule intent detected...")
            results["meme_schedule"] = orchestrate_meme_schedule(request,
                                                                 task_id)
        # Upload intent takes priority: "upload X to youtube"
        if "upload" in request.lower():
            print("  [UPLOAD] Upload intent detected...")
            results["upload"] = try_agent_upload(request, task_id)
            if "error" not in results["upload"]:
                print("  [UPLOAD] Done, gathering trend context...")
        # YouTube/Meme task: research trends, generate ideas, create scripts
        print("  [RESEARCH] Searching YouTube trends...")
        trends = youtube_search(request)
        log_agent(task_id, "web_research", "youtube_trends", request, json.dumps(trends, default=str)[:1000])
        results["trends"] = trends

        print("  [RESEARCH] Searching for meme ideas...")
        memes = web_search(f"funny meme ideas for youtube shorts 2026", 5)
        log_agent(task_id, "web_research", "meme_ideas", request, json.dumps(memes, default=str)[:1000])
        results["meme_ideas"] = memes

        print("  [CREATE] Generating video scripts...")
        topics = []
        for v in trends.get("trending_videos", [])[:5]:
            topics.append(v.get("title", ""))
        scripts = []
        for topic in topics[:3]:
            script = {
                "topic": topic,
                "hook": f"You won't believe what happens with {topic[:30]}",
                "structure": ["Hook (0-3s)", "Content (3-50s)", "CTA (50-60s)"],
                "hashtags": ["#shorts", "#viral", "#trending"],
            }
            scripts.append(script)
        results["scripts"] = scripts
        print(f"  [CREATE] Generated {len(scripts)} video scripts")

        print("  [RESEARCH] Finding upload instructions...")
        upload_info = web_search("how to upload youtube shorts API programmatically", 3)
        results["upload_info"] = upload_info

    elif task_type == "stock":
        # Stock task: research price, analysis, news
        import re
        tickers = re.findall(r'\b[A-Z]{2,5}\b', request.upper())
        ticker = tickers[0] if tickers else "AAPL"

        print(f"  [RESEARCH] Searching {ticker} stock data...")
        stock_data = web_search(f"{ticker} stock price today analysis", 5)
        log_agent(task_id, "web_research", "stock_price", ticker, json.dumps(stock_data, default=str)[:1000])
        results["stock_data"] = stock_data

        print(f"  [RESEARCH] Searching {ticker} news...")
        news = web_search(f"{ticker} stock news latest", 5)
        log_agent(task_id, "web_research", "stock_news", ticker, json.dumps(news, default=str)[:1000])
        results["news"] = news

        print(f"  [ANALYZE] Analyzing {ticker}...")
        analysis = web_search(f"{ticker} stock analysis buy or sell recommendation", 3)
        results["analysis"] = analysis

        # Fetch actual price from a result
        if stock_data.get("results"):
            first_url = stock_data["results"][0].get("url", "")
            if first_url:
                print(f"  [FETCH] Fetching details from {first_url[:60]}...")
                page = web_fetch(first_url)
                results["page_data"] = {"title": page.get("title", ""), "text": page.get("text", "")[:1000]}

    elif task_type == "research":
        # General research
        print(f"  [RESEARCH] Searching: {request[:50]}...")
        search_results = web_search(request, 8)
        log_agent(task_id, "web_research", "search", request, json.dumps(search_results, default=str)[:1000])
        results["search"] = search_results

        # Fetch top results
        fetched = []
        for r in search_results.get("results", [])[:3]:
            url = r.get("url", "")
            if url:
                print(f"  [FETCH] Fetching {url[:60]}...")
                page = web_fetch(url)
                fetched.append({"url": url, "title": page.get("title", ""), "text": page.get("text", "")[:500]})
        results["fetched"] = fetched

    elif task_type == "ecommerce":
        print("  [RESEARCH] Searching products...")
        products = web_search(f"{request} best products review 2026", 5)
        results["products"] = products
        print("  [RESEARCH] Searching suppliers...")
        suppliers = web_search(f"{request} suppliers wholesale aliexpress", 5)
        results["suppliers"] = suppliers

    elif task_type == "crypto":
        print("  [RESEARCH] Getting crypto prices...")
        try:
            from crypto_tracker import get_crypto_prices, get_trending_coins
            prices = get_crypto_prices()
            trending = get_trending_coins()
            results["prices"] = prices
            results["trending"] = trending
            print(f"  [DATA] Got prices for {len(prices)} coins")
        except Exception as e:
            results["prices"] = {"error": str(e)}
        print("  [RESEARCH] Searching crypto news...")
        news = web_search(f"{request} news analysis", 5)
        results["news"] = news

    elif task_type == "content":
        print("  [RESEARCH] Researching topic...")
        topic_research = web_search(f"{request} guide tutorial", 5)
        results["topic_research"] = topic_research
        print("  [CREATE] Generating content outline...")
        outline = {"sections": ["Introduction", "Key Points", "How-To", "Benefits", "Conclusion"]}
        results["outline"] = outline

    elif task_type == "automation":
        print("  [ANALYZE] Analyzing workflow...")
        analysis = web_search(f"{request} best practices automation", 5)
        results["analysis"] = analysis

    else:
        # General task
        print(f"  [RESEARCH] Researching: {request[:50]}...")
        search = web_search(request, 5)
        results["search"] = search

    return results


def process_request(request):
    """Main entry point."""
    conn = init_db()
    c = conn.cursor()
    c.execute("INSERT INTO tasks (user_request, status) VALUES (?, 'running')", (request,))
    task_id = c.lastrowid
    conn.commit()

    task_type = classify_task(request)

    print(f"\n{'='*60}")
    print(f"ELYSIA AGENT v2 - Task #{task_id}")
    print(f"Request: {request}")
    print(f"Type: {task_type}")
    print(f"{'='*60}")

    results = execute_task(task_id, task_type, request)

    c.execute("UPDATE tasks SET status='done', task_type=?, result=?, completed_at=? WHERE id=?",
              (task_type, json.dumps(results, default=str)[:10000], datetime.now().isoformat(), task_id))
    conn.commit()
    conn.close()

    print(f"\n{'='*60}")
    print(f"TASK #{task_id} COMPLETE - {len(results)} sections")
    print(f"{'='*60}")

    return {"task_id": task_id, "type": task_type, "results": results}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = "Upload funny cat memes to my YouTube channel as Shorts"
    result = process_request(task)
    # Save result
    output = os.path.join(WORKSPACE, "agent_result.json")
    with open(output, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n[+] Results saved to {output}")
