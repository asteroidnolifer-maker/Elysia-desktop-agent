#!/usr/bin/env python3
"""News aggregator - real news from multiple sources."""
import requests
import json
from datetime import datetime

def get_news(category="general", country="us"):
    """Get news from multiple free sources."""
    results = []
    
    # Try NewsAPI (free tier)
    try:
        r = requests.get(f"https://newsapi.org/v2/top-headlines", params={
            "country": country, "category": category, "pageSize": 5,
            "apiKey": "demo"  # free tier
        }, timeout=10)
        if r.status_code == 200:
            for a in r.json().get("articles", []):
                results.append({"title": a["title"], "source": a["source"]["name"], "url": a.get("url", ""), "published": a.get("publishedAt", "")})
    except:
        pass

    # Fallback: Google News RSS
    try:
        import feedparser
        feed = feedparser.parse(f"https://news.google.com/rss?q={category}&hl=en-US&gl=US&ceid=US:en")
        for entry in feed.entries[:5]:
            results.append({"title": entry.title, "source": "Google News", "url": entry.link, "published": entry.get("published", "")})
    except:
        pass

    return {"category": category, "articles": results[:10], "count": len(results), "fetched_at": datetime.now().isoformat()}

def search_news(query):
    """Search for specific news."""
    try:
        from ddgs import DDGS
        results = DDGS().news(query, max_results=8)
        return {"query": query, "articles": [{"title": r.get("title", ""), "source": r.get("source", ""), "url": r.get("url", ""), "body": r.get("body", "")[:200]} for r in results]}
    except Exception as e:
        return {"query": query, "error": str(e), "articles": []}

if __name__ == "__main__":
    print("=== Trending News ===")
    news = get_news("technology")
    for a in news["articles"][:5]:
        print(f"  [{a.get('source', '?')}] {a['title'][:70]}")
    print(f"\n=== Search: AI stocks ===")
    search = search_news("AI stocks market 2026")
    for a in search["articles"][:5]:
        print(f"  [{a.get('source', '?')}] {a['title'][:70]}")
