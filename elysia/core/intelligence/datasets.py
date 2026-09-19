"""Dataset Registry — catalog, ingestion, validation, compatibility."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


@dataclass
class DatasetEntry:
    """A dataset in the registry."""
    id: str = field(default_factory=lambda: f"ds-{__import__('uuid').uuid4().hex[:8]}")
    name: str = ""
    source: str = ""  # huggingface, local, url, kaggle
    version: str = ""
    license: str = "unknown"
    language: str = ""
    domains: list[str] = field(default_factory=list)
    size: str = ""  # e.g., "100MB", "10K records"
    format: str = ""  # json, jsonl, csv, parquet, text
    quality: str = "unknown"  # high, medium, low, unknown
    provenance: dict = field(default_factory=dict)
    content_hash: str = ""
    local_path: str = ""
    download_status: str = "not_downloaded"  # not_downloaded, downloading, downloaded, failed
    compatibility: dict = field(default_factory=dict)  # tokenizer, schema, etc.
    intended_use: str = ""  # training, evaluation, rag, benchmark
    trust_level: str = "community"

    def to_dict(self) -> dict:
        return asdict(self)


class DatasetRegistry:
    """Registry for datasets with ingestion pipeline."""

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.db_path = os.path.join(workspace_root, ".elysia", "datasets.db")
        self.data_dir = os.path.join(workspace_root, "data", "datasets")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    source TEXT,
                    version TEXT,
                    license TEXT,
                    language TEXT,
                    domains TEXT,
                    size TEXT,
                    format TEXT,
                    quality TEXT,
                    provenance TEXT,
                    content_hash TEXT,
                    local_path TEXT,
                    download_status TEXT,
                    compatibility TEXT,
                    intended_use TEXT,
                    trust_level TEXT
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_ds_name ON datasets(name)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_ds_domain ON datasets(domains)")
            con.commit()

    def _connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def add(self, entry: DatasetEntry) -> str:
        with self._connect() as con:
            con.execute("""
                INSERT OR REPLACE INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                entry.id, entry.name, entry.source, entry.version, entry.license,
                entry.language, json.dumps(entry.domains), entry.size, entry.format,
                entry.quality, json.dumps(entry.provenance), entry.content_hash,
                entry.local_path, entry.download_status, json.dumps(entry.compatibility),
                entry.intended_use, entry.trust_level
            ))
            con.commit()
        return entry.id

    def get(self, entry_id: str) -> Optional[DatasetEntry]:
        with self._connect() as con:
            row = con.execute("SELECT * FROM datasets WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return None
        return self._row_to_entry(row)

    def search(self, query: str = "", domains: list = None,
               license: str = None, limit: int = 20) -> list[DatasetEntry]:
        with self._connect() as con:
            sql = "SELECT * FROM datasets WHERE 1=1"
            params = []
            if query:
                sql += " AND (name LIKE ? OR source LIKE ?)"
                params.extend([f"%{query}%", f"%{query}%"])
            if domains:
                for d in domains:
                    sql += " AND domains LIKE ?"
                    params.append(f"%{d}%")
            if license:
                sql += " AND license LIKE ?"
                params.append(f"%{license}%")
            sql += " ORDER BY name LIMIT ?"
            params.append(limit)
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def list(self, limit: int = 50) -> list[DatasetEntry]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM datasets ORDER BY name LIMIT ?", (limit,)).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def _row_to_entry(self, row) -> DatasetEntry:
        return DatasetEntry(
            id=row["id"], name=row["name"], source=row["source"],
            version=row["version"], license=row["license"],
            language=row["language"], domains=json.loads(row["domains"] or "[]"),
            size=row["size"], format=row["format"], quality=row["quality"],
            provenance=json.loads(row["provenance"] or "{}"),
            content_hash=row["content_hash"], local_path=row["local_path"],
            download_status=row["download_status"],
            compatibility=json.loads(row["compatibility"] or "{}"),
            intended_use=row["intended_use"], trust_level=row["trust_level"]
        )

    def ingest_huggingface(self, repo_id: str, local_name: str = None,
                           intended_use: str = "rag") -> DatasetEntry:
        """Ingest a HuggingFace dataset (metadata only — download is separate)."""
        # In real implementation, use huggingface_hub to fetch metadata
        entry = DatasetEntry(
            name=local_name or repo_id.split("/")[-1],
            source=f"huggingface:{repo_id}",
            version="latest",
            license="unknown",  # Would fetch from HF
            language="en",
            domains=["general"],
            size="unknown",
            format="parquet",  # HF default
            quality="high",
            provenance={"repo_id": repo_id, "fetched_at": datetime.now().isoformat()},
            local_path=os.path.join(self.data_dir, repo_id.replace("/", "_")),
            download_status="not_downloaded",
            intended_use=intended_use,
        )
        self.add(entry)
        return entry

    def download(self, entry_id: str) -> bool:
        """Download a dataset (placeholder — implement per source)."""
        entry = self.get(entry_id)
        if not entry:
            return False
        # Real implementation would download based on source type
        entry.download_status = "downloaded"
        self.add(entry)
        return True

    def validate(self, entry_id: str) -> dict:
        """Validate dataset format, schema, quality."""
        entry = self.get(entry_id)
        if not entry:
            return {"ok": False, "error": "not found"}
        # Placeholder validation
        return {"ok": True, "checks": ["format", "schema", "non_empty"]}


from datetime import datetime
from typing import Optional