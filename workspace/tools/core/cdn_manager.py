#!/usr/bin/env python3
"""
Elysia CDN Manager - Task 1258
Static asset distribution, cache headers, and origin configuration.
"""
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class CDNManager:
    def __init__(self, static_dir: str = None):
        self.static_dir = Path(static_dir or Path(__file__).parent / ".data" / "cdn")
        self.static_dir.mkdir(parents=True, exist_ok=True)
        self.assets: Dict[str, Dict[str, Any]] = {}
        self.config = {
            "origin": "http://localhost:8087",
            "cache_ttl": 86400,
            "gzip": True,
            "brotli": False
        }

    def register_asset(self, filepath: str, content_type: str = "auto") -> Dict[str, Any]:
        path = Path(filepath)
        if not path.exists():
            return {"error": "File not found"}
        content = path.read_bytes()
        asset_hash = hashlib.md5(content).hexdigest()[:12]
        ext_map = {
            ".css": "text/css", ".js": "application/javascript",
            ".png": "image/png", ".jpg": "image/jpeg",
            ".svg": "image/svg+xml", ".html": "text/html",
            ".json": "application/json", ".woff2": "font/woff2"
        }
        if content_type == "auto":
            content_type = ext_map.get(path.suffix, "application/octet-stream")

        asset = {
            "path": str(path),
            "hash": asset_hash,
            "content_type": content_type,
            "size": len(content),
            "cdn_url": f"/assets/{asset_hash}{path.suffix}",
            "cached_until": (datetime.now().timestamp() + self.config["cache_ttl"]),
            "registered": datetime.now().isoformat()
        }
        self.assets[str(path)] = asset
        return asset

    def get_headers(self, filepath: str) -> Dict[str, str]:
        asset = self.assets.get(filepath, {})
        headers = {
            "Content-Type": asset.get("content_type", "application/octet-stream"),
            "Cache-Control": f"public, max-age={self.config['cache_ttl']}",
            "ETag": f'"{asset.get("hash", "")}"'
        }
        return headers

    def generate_nginx_config(self) -> str:
        lines = [
            "# Elysia CDN Configuration",
            "server {",
            "    listen 80;",
            "    server_name cdn.localhost;",
            "",
            "    location /assets/ {",
            "        alias /data/elysia/workspace/.data/cdn/;",
            "        expires 1y;",
            "        add_header Cache-Control \"public, immutable\";",
            "        add_header Vary \"Accept-Encoding\";",
            "",
            "        # Security headers",
            "        add_header X-Content-Type-Options nosniff;",
            "        add_header X-Frame-Options DENY;",
            "    }",
            "}"
        ]
        return "\n".join(lines)

    def list_assets(self) -> List[Dict[str, Any]]:
        return list(self.assets.values())

    def get_stats(self) -> Dict[str, Any]:
        total_size = sum(a.get("size", 0) for a in self.assets.values())
        return {
            "total_assets": len(self.assets),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "cache_ttl": self.config["cache_ttl"]
        }


def main():
    cdn = CDNManager()
    if len(sys.argv) < 2:
        print("Elysia CDN Manager")
        print("Commands: register <file>, headers <file>, nginx-config, stats")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "register" and len(sys.argv) >= 3:
        result = cdn.register_asset(sys.argv[2])
        print(json.dumps(result, indent=2))
    elif cmd == "headers" and len(sys.argv) >= 3:
        headers = cdn.get_headers(sys.argv[2])
        for k, v in headers.items():
            print(f"  {k}: {v}")
    elif cmd == "nginx-config":
        print(cdn.generate_nginx_config())
    elif cmd == "stats":
        print(json.dumps(cdn.get_stats(), indent=2))


if __name__ == "__main__":
    main()
