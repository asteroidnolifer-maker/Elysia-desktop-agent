"""Embedding Manager — local/remote embeddings with caching and LRU."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Optional
from collections import OrderedDict


@dataclass
class EmbeddingModel:
    name: str
    version: str
    dimensions: int
    distance_metric: str = "cosine"
    local: bool = True
    provider: str = "local"
    max_batch: int = 32
    config: dict = field(default_factory=dict)


class EmbeddingCache:
    """LRU cache for embeddings with content-hash keys."""

    def __init__(self, max_size: int = 10000, db_path: str = None):
        self.max_size = max_size
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = threading.Lock()
        self.db_path = db_path
        if db_path:
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            self._init_db()

    def _init_db(self):
        import sqlite3
        con = sqlite3.connect(self.db_path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                content_hash TEXT PRIMARY KEY,
                model_name TEXT,
                embedding TEXT,
                created_at TEXT
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_emb_model ON embeddings(model_name)")
        con.commit()
        con.close()

    def get(self, content_hash: str, model_name: str) -> Optional[list[float]]:
        key = f"{model_name}:{content_hash}"
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        # Try disk
        if self.db_path:
            import sqlite3
            con = sqlite3.connect(self.db_path)
            row = con.execute(
                "SELECT embedding FROM embeddings WHERE content_hash=? AND model_name=?",
                (content_hash, model_name)
            ).fetchone()
            con.close()
            if row:
                emb = json.loads(row[0])
                with self._lock:
                    self._cache[key] = emb
                    if len(self._cache) > self.max_size:
                        self._cache.popitem(last=False)
                return emb
        return None

    def set(self, content_hash: str, model_name: str, embedding: list[float]):
        key = f"{model_name}:{content_hash}"
        with self._lock:
            self._cache[key] = embedding
            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)
        if self.db_path:
            import sqlite3
            con = sqlite3.connect(self.db_path)
            con.execute(
                "INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?)",
                (content_hash, model_name, json.dumps(embedding),
                 datetime.now().isoformat())
            )
            con.commit()
            con.close()


from datetime import datetime
from typing import Optional


class EmbeddingManager:
    """Manages embedding models with resource-aware loading."""

    def __init__(self, workspace_root: str, config=None):
        self.workspace_root = workspace_root
        self.config = config
        self.models: dict[str, EmbeddingModel] = {}
        self._loaded_model: Optional[Any] = None
        self._loaded_name: Optional[str] = None
        self._lock = threading.Lock()
        self.cache = EmbeddingCache(
            max_size=10000,
            db_path=os.path.join(workspace_root, ".elysia", "embeddings.db")
        )
        # Default models
        self.register(EmbeddingModel(
            name="sentence-transformers/all-MiniLM-L6-v2",
            version="1.0",
            dimensions=384,
            local=True,
            provider="sentence-transformers",
            config={"device": "cpu"}
        ))

    def register(self, model: EmbeddingModel):
        self.models[model.name] = model

    def load(self, model_name: str) -> bool:
        """Load a model into memory (LRU - unload previous)."""
        with self._lock:
            if self._loaded_name == model_name:
                return True
            if self._loaded_model is not None:
                self._unload_current()
            model = self.models.get(model_name)
            if not model:
                return False
            # In real implementation, load the actual model here
            # self._loaded_model = SentenceTransformer(model_name, device=model.config.get("device", "cpu"))
            self._loaded_name = model_name
            return True

    def _unload_current(self):
        if self._loaded_model:
            # Release GPU/CPU memory
            self._loaded_model = None
            self._loaded_name = None

    def embed(self, texts: list[str], model_name: str = None) -> list[list[float]]:
        """Embed texts with caching."""
        if model_name is None:
            model_name = self._loaded_name or list(self.models.keys())[0]
        self.load(model_name)

        results = []
        to_compute = []
        to_compute_idx = []

        # Check cache
        for i, text in enumerate(texts):
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            cached = self.cache.get(content_hash, model_name)
            if cached:
                results.append(cached)
            else:
                to_compute.append(text)
                to_compute_idx.append(i)
                results.append(None)

        # Compute missing
        if to_compute:
            # In real implementation: self._loaded_model.encode(to_compute)
            # For now, return deterministic fake embeddings
            computed = self._fake_embed(to_compute, self.models[model_name].dimensions)
            for idx, emb in zip(to_compute_idx, computed):
                content_hash = hashlib.sha256(to_compute[to_compute_idx.index(idx)].encode()).hexdigest()
                self.cache.set(content_hash, model_name, emb)
                results[idx] = emb

        return results

    def _fake_embed(self, texts: list[str], dim: int) -> list[list[float]]:
        """Deterministic fake embeddings for testing."""
        import random
        out = []
        for t in texts:
            random.seed(hashlib.md5(t.encode()).hexdigest()[:8])
            out.append([random.uniform(-1, 1) for _ in range(dim)])
        return out

    def unload(self, model_name: str = None):
        """Unload a specific model or current model."""
        with self._lock:
            if model_name is None or model_name == self._loaded_name:
                self._unload_current()

    def get_model_info(self, model_name: str) -> Optional[EmbeddingModel]:
        return self.models.get(model_name)

    def list_models(self) -> list[EmbeddingModel]:
        return list(self.models.values())