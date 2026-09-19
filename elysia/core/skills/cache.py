"""Skill Cache — metadata, parsed content, validation results."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from .registry import SkillEntry


@dataclass
class CachedSkill:
    """Cached skill data."""
    entry: SkillEntry
    body: str = ""
    supporting_files: list = field(default_factory=list)
    validation_result: dict = field(default_factory=dict)
    last_accessed: str = field(default_factory=lambda: datetime.now().isoformat())
    access_count: int = 0


class SkillCache:
    """LRU cache for skill metadata and full content with disk persistence."""

    def __init__(self, workspace_root: str, max_size: int = 500):
        self.workspace_root = workspace_root
        self.max_size = max_size
        self._cache: OrderedDict[str, CachedSkill] = OrderedDict()
        self._lock = threading.Lock()
        self.db_path = os.path.join(workspace_root, ".elysia", "skill_cache.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS skill_cache (
                    skill_id TEXT PRIMARY KEY,
                    entry_json TEXT,
                    body TEXT,
                    supporting_json TEXT,
                    validation_json TEXT,
                    last_accessed TEXT,
                    access_count INTEGER DEFAULT 0
                )
            """)
            con.commit()

    def get(self, skill_id: str) -> Optional[CachedSkill]:
        with self._lock:
            if skill_id in self._cache:
                cached = self._cache[skill_id]
                cached.last_accessed = datetime.now().isoformat()
                cached.access_count += 1
                self._cache.move_to_end(skill_id)
                return cached

        # Try disk
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT * FROM skill_cache WHERE skill_id=?", (skill_id,)
            ).fetchone()
        if row:
            cached = CachedSkill(
                entry=SkillEntry(**json.loads(row["entry_json"])),
                body=row["body"],
                supporting_files=json.loads(row["supporting_json"] or "[]"),
                validation_result=json.loads(row["validation_json"] or "{}"),
                last_accessed=row["last_accessed"],
                access_count=row["access_count"]
            )
            with self._lock:
                self._cache[skill_id] = cached
                if len(self._cache) > self.max_size:
                    self._cache.popitem(last=False)
            return cached
        return None

    def set(self, skill_id: str, cached: CachedSkill):
        with self._lock:
            cached.last_accessed = datetime.now().isoformat()
            cached.access_count += 1
            self._cache[skill_id] = cached
            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

        # Persist to disk
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                INSERT OR REPLACE INTO skill_cache VALUES (?,?,?,?,?,?,?)
            """, (
                skill_id,
                json.dumps(cached.entry.to_dict()),
                cached.body,
                json.dumps(cached.supporting_files),
                json.dumps(cached.validation_result),
                cached.last_accessed,
                cached.access_count
            ))
            con.commit()

    def invalidate(self, skill_id: str):
        with self._lock:
            self._cache.pop(skill_id, None)
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM skill_cache WHERE skill_id=?", (skill_id,))
            con.commit()

    def clear(self):
        with self._lock:
            self._cache.clear()
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM skill_cache")
            con.commit()

    def stats(self) -> dict:
        with self._lock:
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "entries": list(self._cache.keys())
            }