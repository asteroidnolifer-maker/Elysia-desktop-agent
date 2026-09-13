"""Deep-research pipeline (OpenResearcher-style).

The research agent plans queries, executes them against search backends, reads
sources, iteratively expands, and finally synthesizes a cited report. It is
provider- and search-engine-agnostic:

  - ``search(query, k)`` generic interface
  - DuckDuckGo HTML adapter (no API key; may be rate-limited)
  - Tavily adapter (needs TAVILY_API_KEY)
  - a no-net local fallback for offline runs

The synthesized report is written into the workspace/reports dir and recorded
to memory as a research note; citations are tracked per source.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request

from .events import EventBus
from .memory import Memory

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120 Safari/537.36")


class SearchProvider:
    def search(self, query: str, k: int = 5) -> list[dict]:
        raise NotImplementedError


class DuckDuckGoSearch(SearchProvider):
    def search(self, query, k=5):
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                html = r.read().decode("utf-8", errors="replace")
        except OSError:
            return []
        results = []
        # extremely tolerant extractor for the lightweight HTML skin
        for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                             html, re.S):
            url = m.group(1)
            title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            if url.startswith("//duckduckgo.com/l/?uddg="):
                url = urllib.parse.unquote(url.split("uddg=", 1)[1])
            results.append({"url": url, "title": title, "snippet": ""})
            if len(results) >= k:
                break
        # snippets
        snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)
        for i, s in enumerate(snips[: len(results)]):
            results[i]["snippet"] = re.sub(r"<[^>]+>", "", s).strip()
        return results


class TavilySearch(SearchProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query, k=5):
        payload = json.dumps({"api_key": self.api_key, "query": query,
                              "max_results": k}).encode()
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode())
        except OSError:
            return []
        return [{"url": x.get("url", ""), "title": x.get("title", ""),
                 "snippet": x.get("content", "")}
                for x in data.get("results", [])][:k]


class OfflineSearch(SearchProvider):
    """Deterministic no-net search for tests/offline: matches a tiny local corpus."""

    def __init__(self, corpus: list[dict] | None = None):
        self.corpus = corpus or [
            {"url": "elysia://docs/architecture", "title": "Elysia architecture",
             "snippet": "Elysia core modules: tasks, scheduler, providers, tools "
                        "and workspace."},
            {"url": "elysia://docs/context", "title": "Context layers",
             "snippet": "ContextBuilder assembles system, project, task, memory, "
                        "history and scratch layers within a char budget."},
        ]

    def search(self, query, k=5):
        q = query.lower()
        hits = [c for c in self.corpus if q in
                (c["title"] + " " + c["snippet"]).lower()]
        return hits[:k]


class ResearchEngine:
    """Plan -> search -> read -> iterate -> synthesize."""

    def __init__(self, providers, memory: Memory | None = None,
                 events: EventBus | None = None, search: SearchProvider | None = None,
                 max_sources: int = 5, output_dir: str = "",
                 max_passes: int = 3):
        self.exec_provider = providers
        self.memory = memory or Memory(os.path.join(output_dir or ".", "state"))
        self.events = events or EventBus()
        self.search = search or DuckDuckGoSearch()
        self.max_sources = max_sources
        self.max_passes = max_passes
        self.output_dir = output_dir

    def run(self, query: str, format_spec: str = "", task_id=None,
            correlation_id=None) -> dict:
        start = time.time()
        queries = self._plan_queries(query)
        sources: dict[str, dict] = {}
        for qi, q in enumerate(queries[:self.max_passes]):
            self.events.emit("research.query", agent_id="research_agent",
                             task_id=task_id, status="ok", detail=q)
            res = self.search.search(q, k=self.max_sources)
            for r in res:
                url = r.get("url", "")
                if url and url not in sources:
                    sources[url] = {"url": url, "title": r.get("title", ""),
                                    "snippet": r.get("snippet", ""),
                                    "query": q}
                    self.events.emit("research.source", agent_id="research_agent",
                                     task_id=task_id, status="ok", detail=url)
            if len(sources) >= self.max_sources:
                break
        sources = dict(list(sources.items())[: self.max_sources])
        report = self._synthesize(query, list(sources.values()), format_spec,
                                  task_id)
        cost = time.time() - start
        self.events.emit("research.complete", agent_id="research_agent",
                         task_id=task_id, status="ok", duration_s=round(cost, 2))
        result = {
            "query": query,
            "queries": queries,
            "sources": list(sources.values()),
            "report": report,
            "format": format_spec or "default",
            "duration_s": round(cost, 2),
            "generated_at": time.time(),
        }
        if self.output_dir:
            os.makedirs(os.path.join(self.output_dir, "reports"), exist_ok=True)
            fname = re.sub(r"[^A-Za-z0-9]+", "_", query)[:60] or "research"
            path = os.path.join(self.output_dir, "reports", fname + ".md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(report)
            result["report_path"] = path
        if self.memory is not None:
            self.memory.record_project_note("research", {
                "query": query, "sources": len(sources),
                "first_sources": [s["url"] for s in list(sources.values())[:3]]})
        return result

    def _plan_queries(self, query: str) -> list[str]:
        text, err = self.exec_provider.execute(
            [{"role": "system", "content": "Break the research question into 2-4 "
               "concrete web-search queries. Return only one query per line."},
             {"role": "user", "content": query}],
            capabilities=["chat", "reasoning"], max_tokens=300)
        if err or not text:
            return [query]
        qs = [ln.strip("- ").strip() for ln in (text or "").splitlines()
              if ln.strip() and not ln.startswith("```")]
        qs = [q for q in qs if 5 < len(q) < 250]
        return (qs[: self.max_passes] or [query])

    def _synthesize(self, query, sources, format_spec, task_id) -> str:
        if not sources:
            return f"# {query}\n\nNo sources found; mark as verified=false."
        src_lines = []
        for i, s in enumerate(sources, 1):
            src_lines.append(f"[{i}] {s['title']} — {s['url']}  \n   {s['snippet'][:300]}")
        src_block = "\n".join(src_lines)
        system = ("You are a meticulous research writer. Synthesize the findings "
                  "into a structured report with an Executive Summary, Findings "
                  "(each citing [n] against the sources), and Next Steps. Do not "
                  "invent citations.")
        user = (f"Research question: {query}\n\n"
                f"{('Format spec: ' + format_spec + '\\n') if format_spec else ''}"
                f"Sources:\n{src_block}")
        text, err = self.exec_provider.execute(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            capabilities=["chat", "reasoning"],
            max_tokens=1600, task_id=task_id)
        if err or not text:
            text = self._fallback_report(query, sources)
        return text or f"# {query}\n\n(empty report)"

    def _fallback_report(self, query, sources):
        lines = [f"# {query}", "", "## Findings", ""]
        for i, s in enumerate(sources, 1):
            lines.append(f"- [{i}] {s['title']}: {s['snippet'][:200]}")
        lines += ["", "## Sources", ""]
        for i, s in enumerate(sources, 1):
            lines.append(f"[{i}] {s['url']}")
        return "\n".join(lines)


def build_search(cfg) -> SearchProvider:
    engine = (cfg.research.search_engine if cfg else "duckduckgo") or "duckduckgo"
    if engine == "tavily":
        key = (cfg.research.tavily_api_key if cfg else "")
        if key:
            return TavilySearch(key)
        return OfflineSearch()
    if engine == "offline":
        return OfflineSearch()
    return DuckDuckGoSearch()