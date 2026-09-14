#!/usr/bin/env python3
"""Elysia Web Browser - own browser for web search and interaction."""
import subprocess, json, os, re, time, hashlib
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

WORKSPACE = "/data/elysia/workspace"
CACHE_DIR = os.path.join(WORKSPACE, ".web_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

class ElysiaBrowser:
    def __init__(self):
        self.session = None
        self._ensure_deps()

    def _ensure_deps(self):
        try:
            import requests
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
        except ImportError:
            subprocess.run(['pip3', 'install', 'requests', 'beautifulsoup4', 'lxml'], capture_output=True)
            import requests
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })

    def search(self, query, num_results=10):
        """Search the web using DuckDuckGo."""
        cache_key = hashlib.md5(query.encode()).hexdigest()
        cache_file = os.path.join(CACHE_DIR, f"search_{cache_key}.json")
        if os.path.exists(cache_file) and time.time() - os.path.getmtime(cache_file) < 3600:
            with open(cache_file) as f:
                return json.load(f)

        results = []
        try:
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            resp = self.session.get(url, timeout=15)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, 'lxml')
            for r in soup.select('.result')[:num_results]:
                title_el = r.select_one('.result__title a')
                snippet_el = r.select_one('.result__snippet')
                if title_el:
                    results.append({
                        'title': title_el.get_text(strip=True),
                        'url': title_el.get('href', ''),
                        'snippet': snippet_el.get_text(strip=True) if snippet_el else ''
                    })
        except Exception as e:
            results = [{'error': str(e)}]

        with open(cache_file, 'w') as f:
            json.dump(results, f)
        return results

    def fetch(self, url, extract_text=True):
        """Fetch a URL and optionally extract text content."""
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
            if extract_text:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'lxml')
                for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                    tag.decompose()
                text = soup.get_text(separator='\n', strip=True)
                lines = [l.strip() for l in text.splitlines() if l.strip()]
                return {'url': url, 'status': resp.status_code, 'content': '\n'.join(lines[:500])}
            return {'url': url, 'status': resp.status_code, 'html': resp.text[:50000]}
        except Exception as e:
            return {'url': url, 'error': str(e)}

    def screenshot(self, url, output_path=None):
        """Take screenshot using playwright."""
        if not output_path:
            output_path = os.path.join(WORKSPACE, f"screenshot_{hashlib.md5(url.encode()).hexdigest()[:8]}.png")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1280, 'height': 720})
                page.goto(url, timeout=30000)
                page.screenshot(path=output_path)
                browser.close()
            return {'screenshot': output_path}
        except ImportError:
            subprocess.run(['pip3', 'install', 'playwright'], capture_output=True)
            subprocess.run(['playwright', 'install', 'chromium'], capture_output=True)
            return self.screenshot(url, output_path)

    def extract_links(self, url):
        """Extract all links from a page."""
        try:
            resp = self.session.get(url, timeout=15)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, 'lxml')
            links = []
            for a in soup.find_all('a', href=True):
                href = urljoin(url, a['href'])
                links.append({'text': a.get_text(strip=True)[:100], 'url': href})
            return links[:200]
        except Exception as e:
            return [{'error': str(e)}]

    def extract_meta(self, url):
        """Extract metadata from a page."""
        try:
            resp = self.session.get(url, timeout=15)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, 'lxml')
            meta = {
                'title': soup.title.string if soup.title else '',
                'description': '',
                'keywords': '',
                'og_title': '',
                'og_description': '',
                'og_image': '',
            }
            for tag in soup.find_all('meta'):
                name = tag.get('name', '').lower()
                prop = tag.get('property', '').lower()
                content = tag.get('content', '')
                if name == 'description': meta['description'] = content
                elif name == 'keywords': meta['keywords'] = content
                elif prop == 'og:title': meta['og_title'] = content
                elif prop == 'og:description': meta['og_description'] = content
                elif prop == 'og:image': meta['og_image'] = content
            return meta
        except Exception as e:
            return {'error': str(e)}

    def submit_form(self, url, form_data):
        """Submit a form on a page."""
        try:
            resp = self.session.post(url, data=form_data, timeout=15)
            return {'status': resp.status_code, 'content': resp.text[:10000]}
        except Exception as e:
            return {'error': str(e)}

if __name__ == "__main__":
    import sys
    browser = ElysiaBrowser()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "search"
    query = ' '.join(sys.argv[2:]) if len(sys.argv) > 2 else "hello world"

    if cmd == "search":
        results = browser.search(query)
        for r in results:
            print(f"  {r.get('title', 'N/A')}")
            print(f"  {r.get('url', 'N/A')}")
            print(f"  {r.get('snippet', '')[:100]}")
            print()
    elif cmd == "fetch":
        result = browser.fetch(query)
        print(result.get('content', result.get('error', 'No content'))[:2000])
    elif cmd == "links":
        links = browser.extract_links(query)
        for l in links[:20]:
            print(f"  {l.get('text', '')[:50]} -> {l.get('url', '')}")
    elif cmd == "meta":
        meta = browser.extract_meta(query)
        for k, v in meta.items():
            print(f"  {k}: {v[:100]}")
    elif cmd == "screenshot":
        result = browser.screenshot(query)
        print(result)
