"""Adapter Registry — LoRA/PEFT adapter management with compatibility checks."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


@dataclass
class AdapterEntry:
    """A LoRA/PEFT adapter."""
    id: str = field(default_factory=lambda: f"adp-{__import__('uuid').uuid4().hex[:8]}")
    name: str = ""
    base_model: str = ""  # e.g., "llama-7b", "mistral-7b"
    architecture: str = ""  # llama, mistral, gpt, etc.
    version: str = ""
    source: str = ""  # huggingface, local, trained
    license: str = "unknown"
    domain: str = ""  # coding, finance, medical, etc.
    task: str = ""  # specific task adapter was trained for
    size: str = ""  # e.g., "8MB", "rank-8"
    rank: int = 8
    compatible_models: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # other adapters needed
    content_hash: str = ""
    trust: str = "community"  # official, verified, community, unknown
    quality: str = "unknown"
    evaluation: dict = field(default_factory=dict)
    local_path: str = ""
    state: str = "discovered"  # discovered, downloading, installed, loading, loaded, active, idle, unloading, unloaded, failed

    def to_dict(self) -> dict:
        return asdict(self)


class AdapterRegistry:
    """Registry for LoRA/PEFT adapters with compatibility checking."""

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.db_path = os.path.join(workspace_root, ".elysia", "adapters.db")
        self.adapters_dir = os.path.join(workspace_root, "adapters")
        os.makedirs(self.adapters_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS adapters (
                    id TEXT PRIMARY KEY,
                    name TEXT,
                    base_model TEXT,
                    architecture TEXT,
                    version TEXT,
                    source TEXT,
                    license TEXT,
                    domain TEXT,
                    task TEXT,
                    size TEXT,
                    rank INTEGER,
                    compatible_models TEXT,
                    dependencies TEXT,
                    content_hash TEXT,
                    trust TEXT,
                    quality TEXT,
                    evaluation TEXT,
                    local_path TEXT,
                    state TEXT
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_adp_base ON adapters(base_model)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_adp_domain ON adapters(domain)")
            con.commit()

    def _connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def add(self, entry: AdapterEntry) -> str:
        with self._connect() as con:
            con.execute("""
                INSERT OR REPLACE INTO adapters VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                entry.id, entry.name, entry.base_model, entry.architecture,
                entry.version, entry.source, entry.license, entry.domain,
                entry.task, entry.size, entry.rank,
                json.dumps(entry.compatible_models), json.dumps(entry.dependencies),
                entry.content_hash, entry.trust, entry.quality,
                json.dumps(entry.evaluation), entry.local_path, entry.state
            ))
            con.commit()
        return entry.id

    def get(self, entry_id: str) -> Optional[AdapterEntry]:
        with self._connect() as con:
            row = con.execute("SELECT * FROM adapters WHERE id=?", (entry_id,)).fetchone()
        if not row:
            return None
        return self._row_to_entry(row)

    def list(self, base_model: str = None, domain: str = None,
             state: str = None) -> list[AdapterEntry]:
        with self._connect() as con:
            sql = "SELECT * FROM adapters WHERE 1=1"
            params = []
            if base_model:
                sql += " AND base_model=?"
                params.append(base_model)
            if domain:
                sql += " AND domain=?"
                params.append(domain)
            if state:
                sql += " AND state=?"
                params.append(state)
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def _row_to_entry(self, row) -> AdapterEntry:
        return AdapterEntry(
            id=row["id"], name=row["name"], base_model=row["base_model"],
            architecture=row["architecture"], version=row["version"],
            source=row["source"], license=row["license"], domain=row["domain"],
            task=row["task"], size=row["size"], rank=row["rank"],
            compatible_models=json.loads(row["compatible_models"] or "[]"),
            dependencies=json.loads(row["dependencies"] or "[]"),
            content_hash=row["content_hash"], trust=row["trust"],
            quality=row["quality"], evaluation=json.loads(row["evaluation"] or "{}"),
            local_path=row["local_path"], state=row["state"]
        )

    def check_compatibility(self, adapter_id: str, base_model: str) -> dict:
        """Check if adapter is compatible with a base model."""
        adapter = self.get(adapter_id)
        if not adapter:
            return {"compatible": False, "reason": "adapter not found"}

        # Check base model match
        if adapter.base_model != base_model:
            if base_model not in adapter.compatible_models:
                return {"compatible": False,
                        "reason": f"base model mismatch: {adapter.base_model} != {base_model}"}

        # Check architecture
        # (would check tokenizer, target modules, etc. in real impl)

        return {"compatible": True, "adapter": adapter.to_dict()}

    def check_stacking(self, adapter_ids: list[str]) -> dict:
        """Check if multiple adapters can be stacked."""
        adapters = [self.get(aid) for aid in adapter_ids]
        missing = [aid for aid, a in zip(adapter_ids, adapters) if not a]
        if missing:
            return {"compatible": False, "reason": f"adapters not found: {missing}"}

        # Check for conflicts: same target modules, rank conflicts, etc.
        # Simplified check
        for a in adapters:
            if a.architecture != adapters[0].architecture:
                return {"compatible": False, "reason": "architecture mismatch"}

        return {"compatible": True, "adapters": [a.to_dict() for a in adapters]}


class AdapterRouter:
    """Select appropriate adapters for a task."""

    def __init__(self, registry: AdapterRegistry):
        self.registry = registry

    def select(self, task: dict, domain: str, base_model: str,
               required_capabilities: list[str] = None,
               available_adapters: list[AdapterEntry] = None,
               resource_state: dict = None) -> list[str]:
        """Select adapters for the given task."""
        if available_adapters is None:
            available_adapters = self.registry.list(base_model=base_model, domain=domain)

        # Filter by domain
        candidates = [a for a in available_adapters if a.domain == domain or domain == "general"]
        if not candidates:
            candidates = available_adapters

        # Check compatibility with base model
        compatible = []
        for a in candidates:
            compat = self.registry.check_compatibility(a.id, base_model)
            if compat["compatible"]:
                compatible.append(a)

        # Score by relevance (domain match, task match, quality, eval scores)
        scored = []
        for a in compatible:
            score = 0
            if a.domain == domain:
                score += 10
            if required_capabilities and any(c in a.task.lower() for c in required_capabilities):
                score += 5
            if a.quality == "high":
                score += 3
            scored.append((score, a))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Resource-aware: limit to 1-2 adapters max
        max_adapters = 2
        if resource_state and resource_state.get("memory_pressure"):
            max_adapters = 1

        return [a.id for _, a in scored[:max_adapters]]