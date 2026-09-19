"""Provenance Tracker — trace every knowledge item back to source."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional


@dataclass
class ProvenanceRecord:
    """A single provenance entry."""
    id: str = field(default_factory=lambda: f"prov-{uuid.uuid4().hex[:8]}")
    knowledge_id: str = ""
    operation: str = ""  # ingest, chunk, embed, retrieve, transform
    input_hash: str = ""
    output_hash: str = ""
    tool: str = ""  # loader, chunker, embedder, retriever
    parameters: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    agent: str = ""  # which agent/request caused this
    run_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ProvenanceTracker:
    """Track full lineage of knowledge from source to retrieval."""

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.db_path = os.path.join(workspace_root, ".elysia", "provenance.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS provenance (
                    id TEXT PRIMARY KEY,
                    knowledge_id TEXT,
                    operation TEXT,
                    input_hash TEXT,
                    output_hash TEXT,
                    tool TEXT,
                    parameters TEXT,
                    timestamp TEXT,
                    agent TEXT,
                    run_id TEXT
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_prov_knowledge ON provenance(knowledge_id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_prov_run ON provenance(run_id)")
            con.commit()

    def record(self, record: ProvenanceRecord):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                INSERT INTO provenance VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                record.id, record.knowledge_id, record.operation,
                record.input_hash, record.output_hash, record.tool,
                json.dumps(record.parameters), record.timestamp,
                record.agent, record.run_id
            ))
            con.commit()

    def record_plan(self, plan) -> dict:
        """Record an IntelligencePlan creation."""
        run_id = plan.run_id if hasattr(plan, "run_id") else f"run-{uuid.uuid4().hex[:8]}"
        record = ProvenanceRecord(
            knowledge_id=plan.run_id,
            operation="plan_created",
            input_hash="",
            output_hash=hashlib.md5(plan.to_json().encode()).hexdigest()[:16],
            tool="IntelligenceFabric",
            parameters={
                "objective": plan.objective[:200],
                "skills": plan.skills,
                "sources": plan.knowledge_sources,
                "adapters": plan.adapters,
            },
            agent="fabric",
            run_id=run_id
        )
        self.record(record)
        return {"run_id": run_id, "operation": "plan_created"}

    def get_lineage(self, knowledge_id: str) -> list[ProvenanceRecord]:
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM provenance WHERE knowledge_id=? ORDER BY timestamp",
                (knowledge_id,)
            ).fetchall()
        return [ProvenanceRecord(**dict(r)) for r in rows]

    def get_run_trace(self, run_id: str) -> list[ProvenanceRecord]:
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT * FROM provenance WHERE run_id=? ORDER BY timestamp",
                (run_id,)
            ).fetchall()
        return [ProvenanceRecord(**dict(r)) for r in rows]

    def explain(self, knowledge_id: str) -> str:
        """Human-readable explanation of where knowledge came from."""
        lineage = self.get_lineage(knowledge_id)
        if not lineage:
            return f"No provenance found for {knowledge_id}"

        lines = [f"Provenance for {knowledge_id}:"]
        for i, r in enumerate(lineage, 1):
            lines.append(f"  {i}. {r.operation} by {r.tool} at {r.timestamp}")
            if r.parameters:
                lines.append(f"     params: {json.dumps(r.parameters)[:200]}")
        return "\n".join(lines)


import hashlib