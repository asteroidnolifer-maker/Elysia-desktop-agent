#!/usr/bin/env python3
"""Real web search engine - fetches actual data from the internet."""
import requests
import json
import os
import re
import time
from urllib.parse import quote_plus, urljoin
from bs4 import BeautifulSoup

WORKSPACE = "/data/elysia/workspace/tools"
CACHE_DIR = "/data/elysia/workspace/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def search_google(query, num_results=10):
    """Real Google search - returns actual results."""
    url = f"https://www.google.com/search?q={quote_plus(query)}&num={num_results}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        results = []
        for g in soup.select("div.g"):
            title_el = g.select_one("h3")
            link_el = g.select_one("a")
            snippet_el = g.select_one("div.VwiC3b")
            if title_el and link_el:
                results.append({
                    "title": title_el.text.strip(),
                    "url": link_el["href"],
                    "snippet": snippet_el.text.strip() if snippet_el else ""
                })
        return {"query": query, "results": results[:num_results], "count": len(results)}
    except Exception as e:
        return {"query": query, "error": str(e), "results": []}


def search_duckduckgo(query, num_results=10):
    """DuckDuckGo search using ddgs library."""
    try:
        from ddgs import DDGS
        raw = DDGS().text(query, max_results=num_results)
        results = [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in raw]
        return {"query": query, "results": results, "count": len(results)}
    except Exception as e:
        return {"query": query, "error": str(e), "results": []}


def fetch_page(url, extract_text=True):
    """Fetch and parse a web page."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        title = soup.title.text.strip() if soup.title else ""
        text = soup.get_text(separator="\n", strip=True)[:5000]
        links = [{"text": a.text.strip(), "href": urljoin(url, a.get("href", ""))} for a in soup.find_all("a", href=True)[:20]]
        meta = {m.get("name", ""): m.get("content", "") for m in soup.find_all("meta") if m.get("name") and m.get("content")}
        return {"url": url, "title": title, "text": text, "links": links, "meta": meta, "status": r.status_code}
    except Exception as e:
        return {"url": url, "error": str(e)}


def search_and_fetch(query, num_results=5):
    """Search and fetch top results."""
    search_results = search_google(query, num_results)
    if not search_results["results"]:
        search_results = search_duckduckgo(query, num_results)
    fetched = []
    for r in search_results["results"][:num_results]:
        page = fetch_page(r["url"])
        page["search_title"] = r["title"]
        page["search_snippet"] = r["snippet"]
        fetched.append(page)
        time.sleep(0.5)
    return {"query": query, "search_results": search_results["results"], "fetched_pages": fetched}


if __name__ == "__main__":
    print("=== Real Web Search Test ===")
    result = search_and_fetch("current S&P 500 stock price today 2026", 3)
    print(f"Query: {result['query']}")
    print(f"Search results: {len(result['search_results'])}")
    for i, r in enumerate(result['search_results']):
        print(f"  {i+1}. {r['title'][:60]}")
        print(f"     {r['url'][:80]}")
    for p in result['fetched_pages']:
        print(f"\nFetched: {p.get('title', 'no title')[:60]}")
        print(f"  Text preview: {p.get('text', '')[:200]}")
    output = os.path.join(WORKSPACE, "web_search_result.json")
    with open(output, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n[+] Saved to {output}")
