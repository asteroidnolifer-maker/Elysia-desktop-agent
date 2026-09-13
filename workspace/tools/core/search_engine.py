#!/usr/bin/env python3
"""
Elysia Search Engine - Task 1243
Full-text search across workspace files with indexing and filters.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import Counter


class SearchIndex:
    def __init__(self, index_path: str = None):
        self.index_path = Path(index_path or Path(__file__).parent / ".data" / "search_index.json")
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index: Dict[str, Dict[str, Any]] = {}
        self.file_stats: Dict[str, Dict[str, Any]] = {}

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r'\w+', text.lower())

    def _extract_content(self, path: Path) -> str:
        try:
            return path.read_text(errors="ignore")[:50000]
        except Exception:
            return ""

    def build_index(self, directory: str, extensions: List[str] = None):
        extensions = extensions or [".py", ".md", ".json", ".ts", ".js", ".sh", ".txt"]
        root = Path(directory)
        self.index = {}
        self.file_stats = {}

        for ext in extensions:
            for path in root.rglob(f"*{ext}"):
                if ".data" in str(path) or "__pycache__" in str(path):
                    continue
                rel = str(path.relative_to(root))
                content = self._extract_content(path)
                tokens = self._tokenize(content)
                freq = Counter(tokens)
                self.index[rel] = {
                    "tokens": dict(freq.most_common(500)),
                    "size": path.stat().st_size,
                    "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat()
                }
                self.file_stats[rel] = {
                    "lines": content.count("\n") + 1,
                    "words": len(tokens)
                }

        self.index_path.write_text(json.dumps({
            "files": self.index,
            "stats": self.file_stats,
            "built_at": datetime.now().isoformat(),
            "total_files": len(self.index)
        }, indent=2))
        print(f"[+] Indexed {len(self.index)} files")
        return len(self.index)

    def load_index(self) -> bool:
        if not self.index_path.exists():
            return False
        data = json.loads(self.index_path.read_text())
        self.index = data.get("files", {})
        self.file_stats = data.get("stats", {})
        return True

    def search(self, query: str, limit: int = 20,
               file_pattern: str = None) -> List[Dict[str, Any]]:
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []

        scores = {}
        for filepath, data in self.index.items():
            if file_pattern and file_pattern not in filepath:
                continue
            tokens = data.get("tokens", {})
            score = sum(tokens.get(t, 0) for t in query_tokens)
            if score > 0:
                scores[filepath] = score

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        results = []
        for filepath, score in ranked:
            results.append({
                "path": filepath,
                "score": score,
                "stats": self.file_stats.get(filepath, {}),
                "snippet": self._get_snippet(filepath, query_tokens)
            })
        return results

    def _get_snippet(self, filepath: str, query_tokens: List[str],
                     context_chars: int = 100) -> str:
        root = Path(self.index_path).parent.parent.parent
        path = root / filepath
        try:
            content = path.read_text(errors="ignore")
        except Exception:
            return ""
        content_lower = content.lower()
        for token in query_tokens:
            idx = content_lower.find(token)
            if idx >= 0:
                start = max(0, idx - context_chars)
                end = min(len(content), idx + context_chars)
                snippet = content[start:end].replace("\n", " ").strip()
                return f"...{snippet}..."
        return ""

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_files": len(self.index),
            "total_words": sum(s.get("words", 0) for s in self.file_stats.values()),
            "total_lines": sum(s.get("lines", 0) for s in self.file_stats.values())
        }


def main():
    idx = SearchIndex()

    if len(sys.argv) < 2:
        print("Elysia Search Engine")
        print("Commands: build <dir>, search <query>, stats")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "build" and len(sys.argv) >= 3:
        idx.build_index(sys.argv[2])
    elif cmd == "search" and len(sys.argv) >= 3:
        idx.load_index()
        query = " ".join(sys.argv[2:])
        results = idx.search(query)
        print(f"Found {len(results)} results:")
        for r in results:
            print(f"  {r['path']} (score: {r['score']})")
            if r["snippet"]:
                print(f"    {r['snippet'][:120]}")
    elif cmd == "stats":
        idx.load_index()
        print(json.dumps(idx.get_stats(), indent=2))


if __name__ == "__main__":
    main()
