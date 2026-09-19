"""Canonical Skill Registry — SQLite-backed skill store with full metadata."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, List


@dataclass
class SkillEntry:
    """A skill in the registry with all required metadata (per prompt §3)."""
    # Core identity
    id: str = field(default_factory=lambda: f"sk-{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    license: str = "unknown"
    source: str = ""  # local, git, zip, url
    source_repo: str = ""
    homepage: str = ""
    local_path: str = ""

    # Metadata
    tags: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # skill IDs
    required_tools: list[str] = field(default_factory=list)
    required_credentials: list[str] = field(default_factory=list)
    compatibility: dict = field(default_factory=dict)  # platform, python version, etc.

    # Risk & trust
    risk_level: str = "safe"  # safe, low, moderate, high
    trust_status: str = "community"  # trusted, verified, community, unverified, blocked

    # Resource estimates
    resource_cost: dict = field(default_factory=dict)  # cpu, ram, network, disk, llm_calls, latency

    # Operational
    enabled: bool = True
    health: str = "unknown"  # healthy, degraded, failed
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    content_hash: str = ""
    install_date: str = field(default_factory=lambda: datetime.now().isoformat())

    # Runtime tracking
    usage_count: int = 0
    success_rate: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SkillEntry":
        return cls(**data)

    def is_blocked(self) -> bool:
        return self.trust_status == "blocked" or self.risk_level == "high"

    @property
    def risk(self) -> str:
        """Alias for risk_level for backward compatibility."""
        return self.risk_level


class SkillRegistry:
    """Canonical skill registry with SQLite persistence.

    Fields tracked (per prompt §3):
    - id, name, description, version, author, license, source, source_repo,
      homepage, local_path, tags, domains, dependencies, required_tools,
      required_credentials, compatibility, risk_level, trust_status,
      resource_cost, enabled, health, last_updated, content_hash,
      install_date, usage_count, success_rate
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS skills (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        version TEXT NOT NULL DEFAULT '1.0.0',
        author TEXT,
        license TEXT,
        source TEXT,
        source_repo TEXT,
        homepage TEXT,
        local_path TEXT,
        tags TEXT,
        domains TEXT,
        dependencies TEXT,
        required_tools TEXT,
        required_credentials TEXT,
        compatibility TEXT,
        risk_level TEXT,
        trust_status TEXT,
        resource_cost TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        health TEXT,
        last_updated TEXT,
        content_hash TEXT,
        install_date TEXT,
        usage_count INTEGER NOT NULL DEFAULT 0,
        success_rate REAL NOT NULL DEFAULT 0.0
    );
    CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name);
    CREATE INDEX IF NOT EXISTS idx_skills_domain ON skills(domains);
    CREATE INDEX IF NOT EXISTS idx_skills_risk ON skills(risk_level);
    CREATE INDEX IF NOT EXISTS idx_skills_trust ON skills(trust_status);
    CREATE INDEX IF NOT EXISTS idx_skills_enabled ON skills(enabled);
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.executescript(self.SCHEMA)
            con.commit()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _row_to_entry(self, row) -> SkillEntry:
        return SkillEntry(
            id=row["id"], name=row["name"], description=row["description"],
            version=row["version"], author=row["author"], license=row["license"],
            source=row["source"], source_repo=row["source_repo"], homepage=row["homepage"],
            local_path=row["local_path"], tags=json.loads(row["tags"] or "[]"),
            domains=json.loads(row["domains"] or "[]"),
            dependencies=json.loads(row["dependencies"] or "[]"),
            required_tools=json.loads(row["required_tools"] or "[]"),
            required_credentials=json.loads(row["required_credentials"] or "[]"),
            compatibility=json.loads(row["compatibility"] or "{}"),
            risk_level=row["risk_level"], trust_status=row["trust_status"],
            resource_cost=json.loads(row["resource_cost"] or "{}"),
            enabled=bool(row["enabled"]), health=row["health"],
            last_updated=row["last_updated"], content_hash=row["content_hash"],
            install_date=row["install_date"], usage_count=row["usage_count"],
            success_rate=row["success_rate"]
        )

    def add(self, entry: SkillEntry) -> str:
        """Add or update a skill entry."""
        with self._connect() as con:
            con.execute("""
                INSERT OR REPLACE INTO skills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                entry.id, entry.name, entry.description, entry.version,
                entry.author, entry.license, entry.source, entry.source_repo,
                entry.homepage, entry.local_path, json.dumps(entry.tags),
                json.dumps(entry.domains), json.dumps(entry.dependencies),
                json.dumps(entry.required_tools), json.dumps(entry.required_credentials),
                json.dumps(entry.compatibility), entry.risk_level, entry.trust_status,
                json.dumps(entry.resource_cost), int(entry.enabled), entry.health,
                entry.last_updated, entry.content_hash, entry.install_date,
                entry.usage_count, entry.success_rate
            ))
            con.commit()
        return entry.id

    def get(self, skill_id: str) -> Optional[SkillEntry]:
        with self._connect() as con:
            row = con.execute("SELECT * FROM skills WHERE id=?", (skill_id,)).fetchone()
        return self._row_to_entry(row) if row else None

    def get_by_name(self, name: str) -> Optional[SkillEntry]:
        with self._connect() as con:
            row = con.execute("SELECT * FROM skills WHERE name=?", (name,)).fetchone()
        return self._row_to_entry(row) if row else None

    def list(self, enabled_only: bool = True, domain: str = None,
             risk: str = None, trust: str = None, limit: int = 100) -> List[SkillEntry]:
        with self._connect() as con:
            sql = "SELECT * FROM skills WHERE 1=1"
            params = []
            if enabled_only:
                sql += " AND enabled=1"
            if domain:
                sql += " AND domains LIKE ?"
                params.append(f"%{domain}%")
            if risk:
                sql += " AND risk_level=?"
                params.append(risk)
            if trust:
                sql += " AND trust_status=?"
                params.append(trust)
            sql += " ORDER BY name LIMIT ?"
            params.append(limit)
            rows = con.execute(sql, params).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def enable(self, skill_id: str) -> bool:
        with self._connect() as con:
            cur = con.execute("UPDATE skills SET enabled=1 WHERE id=?", (skill_id,))
            con.commit()
            return cur.rowcount > 0

    def disable(self, skill_id: str) -> bool:
        with self._connect() as con:
            cur = con.execute("UPDATE skills SET enabled=0 WHERE id=?", (skill_id,))
            con.commit()
            return cur.rowcount > 0

    def update_health(self, skill_id: str, health: str) -> bool:
        with self._connect() as con:
            cur = con.execute("UPDATE skills SET health=?, last_updated=? WHERE id=?",
                              (health, datetime.now().isoformat(), skill_id))
            con.commit()
            return cur.rowcount > 0

    def record_usage(self, skill_id: str, success: bool):
        with self._connect() as con:
            entry = self.get(skill_id)
            if not entry:
                return
            entry.usage_count += 1
            # Update success rate with exponential moving average
            alpha = 0.1
            entry.success_rate = entry.success_rate * (1 - alpha) + (1.0 if success else 0.0) * alpha
            entry.last_updated = datetime.now().isoformat()
            self.add(entry)

    def stats(self) -> dict:
        with self._connect() as con:
            total = con.execute("SELECT COUNT(*) FROM skills").fetchone()[0]
            enabled = con.execute("SELECT COUNT(*) FROM skills WHERE enabled=1").fetchone()[0]
            by_domain = dict(con.execute("""
                SELECT domain, COUNT(*) FROM (
                    SELECT json_each.value as domain FROM skills, json_each(domains)
                ) GROUP BY domain
            """).fetchall())
            by_risk = dict(con.execute("SELECT risk_level, COUNT(*) FROM skills GROUP BY risk_level").fetchall())
            by_trust = dict(con.execute("SELECT trust_status, COUNT(*) FROM skills GROUP BY trust_status").fetchall())
            by_health = dict(con.execute("SELECT health, COUNT(*) FROM skills GROUP BY health").fetchall())
        return {
            "total": total, "enabled": enabled, "disabled": total - enabled,
            "by_domain": by_domain, "by_risk": by_risk,
            "by_trust": by_trust, "by_health": by_health
        }

    def find_duplicates(self) -> List[List[SkillEntry]]:
        """Find skills with identical content_hash."""
        with self._connect() as con:
            rows = con.execute("""
                SELECT content_hash, COUNT(*) as cnt FROM skills
                WHERE content_hash IS NOT NULL AND content_hash != ''
                GROUP BY content_hash HAVING cnt > 1
            """).fetchall()
        duplicates = []
        for row in rows:
            entries = self.list(enabled_only=False)
            matching = [e for e in entries if e.content_hash == row["content_hash"]]
            if len(matching) > 1:
                duplicates.append(matching)
        return duplicates

    def resolve_dependencies(self, skill_ids: List[str]) -> tuple[List[str], List[str]]:
        """Resolve skill dependencies topologically. Returns (ordered_ids, missing_ids)."""
        # Build adjacency
        skills = {s.id: s for s in self.list(enabled_only=False)}
        adj = {sid: [] for sid in skill_ids}
        indegree = {sid: 0 for sid in skill_ids}
        missing = []

        for sid in skill_ids:
            skill = skills.get(sid)
            if not skill:
                missing.append(sid)
                continue
            for dep in skill.dependencies:
                if dep in skill_ids:
                    adj[dep].append(sid)
                    indegree[sid] += 1
                elif dep not in skills:
                    missing.append(dep)

        if missing:
            return [], list(set(missing))

        # Topological sort
        queue = [sid for sid in skill_ids if indegree[sid] == 0]
        ordered = []
        while queue:
            sid = queue.pop(0)
            ordered.append(sid)
            for nxt in adj[sid]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)

        if len(ordered) != len(skill_ids):
            return [], ["circular dependency detected"]

        return ordered, []


import json
from datetime import datetime
from typing import Any, Optional, List