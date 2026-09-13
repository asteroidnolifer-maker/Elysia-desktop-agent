"""Structured memory/context.

Project/task/agent/provider/run state is structured (JSON) rather than giant
markdown. Human-readable docs are generated on top of this layer.
"""
from __future__ import annotations

import json
import os


class MemoryStore:
    def __init__(self, state_dir: str):
        self.dir = state_dir
        os.makedirs(self.dir, exist_ok=True)

    def _path(self, key: str) -> str:
        safe = key.replace("/", "_").replace("\\", "_").replace("..", "_")
        return os.path.join(self.dir, safe + ".json")

    def set(self, key: str, value) -> None:
        with open(self._path(key), "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, default=str)

    def get(self, key: str, default=None):
        try:
            with open(self._path(key), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return default

    def update(self, key: str, **fields) -> dict:
        data = dict(self.get(key, {}) or {})
        data.update(fields)
        self.set(key, data)
        return data

    def delete(self, key: str) -> None:
        try:
            os.remove(self._path(key))
        except OSError:
            pass

    def keys(self) -> list[str]:
        if not os.path.isdir(self.dir):
            return []
        return [f[:-5] for f in os.listdir(self.dir) if f.endswith(".json")]