#!/usr/bin/env python3
"""
Elysia Caching Layer - Task 1257
Multi-tier caching: in-memory LRU, disk cache, and TTL support.
"""
import hashlib
import json
import os
import sys
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class LRUCache:
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.cache: OrderedDict = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def put(self, key: str, value: Any):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def remove(self, key: str) -> bool:
        if key in self.cache:
            del self.cache[key]
            return True
        return False

    def clear(self):
        self.cache.clear()

    def size(self) -> int:
        return len(self.cache)

    def keys(self) -> list:
        return list(self.cache.keys())


class TTLCache:
    def __init__(self, default_ttl: int = 300):
        self.default_ttl = default_ttl
        self.cache: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self.cache.get(key)
        if not entry:
            return None
        if time.time() > entry["expires"]:
            del self.cache[key]
            return None
        return entry["value"]

    def put(self, key: str, value: Any, ttl: int = None):
        self.cache[key] = {
            "value": value,
            "expires": time.time() + (ttl or self.default_ttl),
            "created": time.time()
        }

    def remove(self, key: str) -> bool:
        if key in self.cache:
            del self.cache[key]
            return True
        return False

    def cleanup(self):
        now = time.time()
        expired = [k for k, v in self.cache.items() if now > v["expires"]]
        for k in expired:
            del self.cache[k]

    def size(self) -> int:
        return len(self.cache)


class DiskCache:
    def __init__(self, cache_dir: str = None, max_size_mb: int = 100):
        self.cache_dir = Path(cache_dir or Path(__file__).parent / ".data" / "disk_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_size_mb = max_size_mb

    def _key_path(self, key: str) -> Path:
        safe_key = hashlib.md5(key.encode()).hexdigest()
        return self.cache_dir / f"{safe_key}.json"

    def get(self, key: str) -> Optional[Any]:
        path = self._key_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            if data.get("expires") and time.time() > data["expires"]:
                path.unlink()
                return None
            return data.get("value")
        except Exception:
            return None

    def put(self, key: str, value: Any, ttl: int = None):
        data = {"key": key, "value": value, "created": time.time()}
        if ttl:
            data["expires"] = time.time() + ttl
        path = self._key_path(key)
        path.write_text(json.dumps(data, default=str))

    def remove(self, key: str) -> bool:
        path = self._key_path(key)
        if path.exists():
            path.unlink()
            return True
        return False

    def size(self) -> int:
        return len(list(self.cache_dir.glob("*.json")))

    def clear(self):
        for f in self.cache_dir.glob("*.json"):
            f.unlink()


class MultiTierCache:
    def __init__(self, memory_size: int = 500, default_ttl: int = 300):
        self.l1 = LRUCache(memory_size)
        self.l2 = TTLCache(default_ttl)
        self.disk = DiskCache()
        self.hits = {"l1": 0, "l2": 0, "disk": 0, "miss": 0}

    def get(self, key: str) -> Optional[Any]:
        val = self.l1.get(key)
        if val is not None:
            self.hits["l1"] += 1
            return val
        val = self.l2.get(key)
        if val is not None:
            self.hits["l2"] += 1
            self.l1.put(key, val)
            return val
        val = self.disk.get(key)
        if val is not None:
            self.hits["disk"] += 1
            self.l1.put(key, val)
            self.l2.put(key, val)
            return val
        self.hits["miss"] += 1
        return None

    def put(self, key: str, value: Any, ttl: int = None):
        self.l1.put(key, value)
        self.l2.put(key, value, ttl)
        self.disk.put(key, value, ttl)

    def remove(self, key: str):
        self.l1.remove(key)
        self.l2.remove(key)
        self.disk.remove(key)

    def stats(self) -> Dict[str, Any]:
        total = sum(self.hits.values())
        return {
            "hits": dict(self.hits),
            "hit_rate": {k: v / max(total, 1) * 100 for k, v in self.hits.items()},
            "l1_size": self.l1.size(),
            "l2_size": self.l2.size(),
            "disk_size": self.disk.size()
        }


def main():
    cache = MultiTierCache()
    if len(sys.argv) < 2:
        print("Elysia Multi-Tier Cache")
        print("Commands: put <key> <value>, get <key>, remove <key>, stats, clear")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "put" and len(sys.argv) >= 4:
        cache.put(sys.argv[2], sys.argv[3])
        print(f"[+] Cached: {sys.argv[2]}")
    elif cmd == "get" and len(sys.argv) >= 3:
        val = cache.get(sys.argv[2])
        print(f"Value: {val}" if val else "Cache miss")
    elif cmd == "remove" and len(sys.argv) >= 3:
        cache.remove(sys.argv[2])
        print(f"[+] Removed: {sys.argv[2]}")
    elif cmd == "stats":
        print(json.dumps(cache.stats(), indent=2))
    elif cmd == "clear":
        cache.l1.clear()
        cache.l2.clear()
        cache.disk.clear()
        print("[+] Cache cleared")


if __name__ == "__main__":
    main()
