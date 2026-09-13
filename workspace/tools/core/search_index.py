#!/usr/bin/env python3
"""
Elysia Search Indexing - Task 1246
Inverted index creation, incremental updates, and relevance scoring.
"""
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set


class SearchIndexer:
    def __init__(self, index_dir: str = None):
        self.index_dir = Path(index_dir or Path(__file__).parent / ".data" / "search_idx")
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.inverted_index: Dict[str, Dict[str, float]] = defaultdict(dict)
        self.doc_count = 0
        self.doc_lengths: Dict[str, int] = {}
        self.avg_doc_length = 0

    def _tokenize(self, text: str) -> List[str]:
        stop_words = {"the", "a", "an", "is", "are", "was", "in", "to", "of",
                      "and", "or", "for", "on", "with", "at", "by", "from"}
        tokens = re.findall(r'\w+', text.lower())
        return [t for t in tokens if t not in stop_words and len(t) > 1]

    def _compute_tf(self, term_freq: int, doc_length: int) -> float:
        return term_freq / max(doc_length, 1)

    def _compute_idf(self, doc_freq: int) -> float:
        return math.log((self.doc_count + 1) / (doc_freq + 1)) + 1

    def add_document(self, doc_id: str, content: str):
        tokens = self._tokenize(content)
        self.doc_lengths[doc_id] = len(tokens)
        self.doc_count += 1
        self.avg_doc_length = sum(self.doc_lengths.values()) / max(len(self.doc_lengths), 1)

        term_freqs: Dict[str, int] = defaultdict(int)
        for token in tokens:
            term_freqs[token] += 1

        for term, freq in term_freqs.items():
            tf = self._compute_tf(freq, len(tokens))
            self.inverted_index[term][doc_id] = tf

    def search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        query_tokens = self._tokenize(query)
        scores: Dict[str, float] = defaultdict(float)

        for token in query_tokens:
            if token in self.inverted_index:
                df = len(self.inverted_index[token])
                idf = self._compute_idf(df)
                for doc_id, tf in self.inverted_index[token].items():
                    scores[doc_id] += tf * idf

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [{"doc_id": doc_id, "score": round(score, 4)}
                for doc_id, score in ranked]

    def remove_document(self, doc_id: str):
        for term in list(self.inverted_index.keys()):
            self.inverted_index[term].pop(doc_id, None)
            if not self.inverted_index[term]:
                del self.inverted_index[term]
        self.doc_lengths.pop(doc_id, None)
        self.doc_count = max(0, self.doc_count - 1)

    def save(self):
        data = {
            "inverted_index": {k: v for k, v in self.inverted_index.items()},
            "doc_count": self.doc_count,
            "doc_lengths": self.doc_lengths,
            "avg_doc_length": self.avg_doc_length
        }
        path = self.index_dir / "index.json"
        path.write_text(json.dumps(data, indent=2))

    def load(self):
        path = self.index_dir / "index.json"
        if path.exists():
            data = json.loads(path.read_text())
            self.inverted_index = defaultdict(dict, data.get("inverted_index", {}))
            self.doc_count = data.get("doc_count", 0)
            self.doc_lengths = data.get("doc_lengths", {})
            self.avg_doc_length = data.get("avg_doc_length", 0)

    def stats(self) -> Dict[str, Any]:
        return {
            "total_terms": len(self.inverted_index),
            "total_documents": self.doc_count,
            "avg_doc_length": round(self.avg_doc_length, 1)
        }


def main():
    indexer = SearchIndexer()
    if len(sys.argv) < 2:
        print("Elysia Search Indexer")
        print("Commands: index <file>, search <query>, stats, bulk-index <dir>")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "index" and len(sys.argv) >= 3:
        content = Path(sys.argv[2]).read_text(errors="ignore")
        indexer.add_document(sys.argv[2], content)
        indexer.save()
        print(f"[+] Indexed: {sys.argv[2]}")
    elif cmd == "search" and len(sys.argv) >= 3:
        indexer.load()
        results = indexer.search(" ".join(sys.argv[2:]))
        for r in results:
            print(f"  {r['doc_id']}: score={r['score']}")
    elif cmd == "bulk-index" and len(sys.argv) >= 3:
        count = 0
        for f in Path(sys.argv[2]).rglob("*.py"):
            if ".data" in str(f) or "__pycache__" in str(f):
                continue
            try:
                content = f.read_text(errors="ignore")
                indexer.add_document(str(f), content)
                count += 1
            except Exception:
                pass
        indexer.save()
        print(f"[+] Indexed {count} files")
    elif cmd == "stats":
        indexer.load()
        print(json.dumps(indexer.stats(), indent=2))


if __name__ == "__main__":
    main()
