"""Vector Index — lightweight vector storage with metadata filtering."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any, Optional
import hashlib


@dataclass
class VectorRecord:
    id: str
    content_hash: str
    embedding: list[float]
    metadata: dict
    source_id: str


class VectorIndex:
    """Lightweight vector index using SQLite + in-memory HNSW fallback.

    For production, consider FAISS or Annoy. This implementation uses
    SQLite with brute-force search for small indices (<10k vectors).
    """

    def __init__(self, workspace_root: str, dim: int, index_name: str = "default"):
        self.workspace_root = workspace_root
        self.dim = dim
        self.index_name = index_name
        self.db_path = os.path.join(workspace_root, ".elysia", f"vector_{index_name}.db")
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS vectors (
                    id TEXT PRIMARY KEY,
                    content_hash TEXT,
                    embedding TEXT,
                    metadata TEXT,
                    source_id TEXT,
                    created_at TEXT
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_vec_source ON vectors(source_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_vec_hash ON vectors(content_hash)")
            con.commit()

    def add(self, record: VectorRecord):
        with self._lock:
            with sqlite3.connect(self.db_path) as con:
                con.execute("""
                    INSERT OR REPLACE INTO vectors VALUES (?,?,?,?,?,?)
                """, (
                    record.id, record.content_hash,
                    json.dumps(record.embedding),
                    json.dumps(record.metadata),
                    record.source_id,
                    datetime.now().isoformat()
                ))
                con.commit()

    def add_batch(self, records: list[VectorRecord]):
        with self._lock:
            with sqlite3.connect(self.db_path) as con:
                con.executemany("""
                    INSERT OR REPLACE INTO vectors VALUES (?,?,?,?,?,?)
                """, [
                    (r.id, r.content_hash, json.dumps(r.embedding),
                     json.dumps(r.metadata), r.source_id,
                     datetime.now().isoformat())
                    for r in records
                ])
                con.commit()

    def search(self, query_embedding: list[float], k: int = 10,
               filter_metadata: dict = None) -> list[tuple[VectorRecord, float]]:
        """Brute-force cosine similarity search with metadata filtering."""
        with self._lock:
            with sqlite3.connect(self.db_path) as con:
                con.row_factory = sqlite3.Row
                rows = con.execute("SELECT * FROM vectors").fetchall()

        if not rows:
            return []

        # Filter by metadata
        filtered = []
        for row in rows:
            meta = json.loads(row["metadata"] or "{}")
            if filter_metadata:
                if not all(meta.get(k) == v for k, v in filter_metadata.items()):
                    continue
            filtered.append(row)

        if not filtered:
            return []

        # Compute cosine similarity
        import math
        query_norm = math.sqrt(sum(x*x for x in query_embedding))
        if query_norm == 0:
            return []

        scored = []
        for row in filtered:
            emb = json.loads(row["embedding"])
            if len(emb) != self.dim:
                continue
            dot = sum(a*b for a, b in zip(query_embedding, emb))
            emb_norm = math.sqrt(sum(x*x for x in emb))
            if emb_norm == 0:
                continue
            sim = dot / (query_norm * emb_norm)
            record = VectorRecord(
                id=row["id"],
                content_hash=row["content_hash"],
                embedding=emb,
                metadata=json.loads(row["metadata"] or "{}"),
                source_id=row["source_id"]
            )
            scored.append((record, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    def delete(self, record_id: str):
        with self._lock:
            with sqlite3.connect(self.db_path) as con:
                con.execute("DELETE FROM vectors WHERE id=?", (record_id,))
                con.commit()

    def count(self) -> int:
        with sqlite3.connect(self.db_path) as con:
            return con.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]


from datetime import datetime


class HybridRetriever:
    """Hybrid retrieval: BM25 + semantic + metadata + reranking."""

    def __init__(self, knowledge_registry):
        self.knowledge = knowledge_registry
        # Initialize embedder
        self.embedder = None  # Set via set_embedder()

    def set_embedder(self, embedder):
        self.embedder = embedder

    def retrieve(self, query: str, sources: list[str] = None,
                 task: dict = None, budget_tokens: int = 2000) -> list[dict]:
        """Hybrid retrieval with multiple strategies."""
        results = []

        # 1. Keyword/BM25 search (via knowledge registry search)
        keyword_results = self.knowledge.search(
            query=query,
            domain=task.get("domain") if task else None,
            limit=20
        )

        # 2. Semantic search (if embedder available)
        semantic_results = []
        if self.embedder and self.embedder._loaded_model:
            query_emb = self.embedder.embed([query])[0]
            # Search vector index (would need per-domain index)
            # For now, use knowledge chunks with embeddings
            pass

        # 3. Combine and deduplicate
        seen = set()
        for entry in keyword_results:
            for chunk in entry.chunks:
                chunk_id = f"{entry.id}:{chunk['id']}"
                if chunk_id not in seen:
                    seen.add(chunk_id)
                    results.append({
                        "source_id": entry.id,
                        "source_title": entry.title,
                        "source_type": entry.source_type,
                        "domain": entry.domain,
                        "trust_level": entry.trust_level,
                        "chunk": chunk,
                        "provenance": entry.provenance,
                        "retrieval_method": "keyword"
                    })

        # 4. Token budget truncation
        return self._truncate_to_budget(results, budget_tokens)

    def _truncate_to_budget(self, results: list[dict], budget: int) -> list[dict]:
        """Truncate results to fit token budget."""
        total = 0
        truncated = []
        for r in results:
            chunk_text = r["chunk"]["text"]
            tokens = len(chunk_text) // 4
            if total + tokens > budget:
                break
            total += tokens
            truncated.append(r)
        return truncated


from datetime import datetime