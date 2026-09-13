#!/usr/bin/env python3
"""
Elysia API Gateway - Tasks 1291-1294
Rate limiting, versioning, routing, and API management.
"""
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class RateLimiter:
    def __init__(self, max_requests: int = 100, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: Dict[str, List[float]] = defaultdict(list)

    def check(self, client_id: str) -> bool:
        now = time.time()
        cutoff = now - self.window
        self.requests[client_id] = [t for t in self.requests[client_id] if t > cutoff]
        if len(self.requests[client_id]) >= self.max_requests:
            return False
        self.requests[client_id].append(now)
        return True

    def remaining(self, client_id: str) -> int:
        now = time.time()
        cutoff = now - self.window
        recent = [t for t in self.requests[client_id] if t > cutoff]
        return max(0, self.max_requests - len(recent))

    def reset(self, client_id: str = None):
        if client_id:
            self.requests.pop(client_id, None)
        else:
            self.requests.clear()


class APIRouter:
    def __init__(self):
        self.routes: Dict[str, Dict[str, Any]] = {}
        self.middleware: List[Dict[str, Any]] = []

    def register(self, path: str, handler: str, methods: List[str] = None,
                 version: str = "v1"):
        key = f"{version}:{path}"
        self.routes[key] = {
            "path": path,
            "handler": handler,
            "methods": methods or ["GET"],
            "version": version,
            "created": datetime.now().isoformat()
        }

    def match(self, path: str, method: str = "GET",
              version: str = "v1") -> Optional[Dict[str, Any]]:
        key = f"{version}:{path}"
        route = self.routes.get(key)
        if route and method in route["methods"]:
            return route
        for k, r in self.routes.items():
            if r["path"] == path and r["version"] == version and method in r["methods"]:
                return r
        return None

    def list_routes(self) -> List[Dict[str, Any]]:
        return list(self.routes.values())


class APIGateway:
    def __init__(self, config_path: str = None):
        self.config_path = Path(config_path or Path(__file__).parent / ".data" / "gateway.json")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.rate_limiter = RateLimiter()
        self.router = APIRouter()
        self.request_log: List[Dict[str, Any]] = []
        self.api_keys: Dict[str, Dict[str, Any]] = {}

    def register_route(self, path: str, handler: str, version: str = "v1"):
        self.router.register(path, handler, version=version)

    def add_api_key(self, key: str, client: str, rate_limit: int = 100):
        self.api_keys[key] = {"client": client, "rate_limit": rate_limit,
                              "created": datetime.now().isoformat()}

    def handle_request(self, path: str, method: str = "GET",
                       api_key: str = None, version: str = "v1") -> Dict[str, Any]:
        request = {
            "path": path,
            "method": method,
            "version": version,
            "timestamp": datetime.now().isoformat()
        }

        if api_key:
            if api_key not in self.api_keys:
                return {"status": 401, "error": "Invalid API key"}
            client_id = self.api_keys[api_key]["client"]
            if not self.rate_limiter.check(client_id):
                return {"status": 429, "error": "Rate limit exceeded",
                        "remaining": self.rate_limiter.remaining(client_id)}
        else:
            client_id = "anonymous"

        route = self.router.match(path, method, version)
        if not route:
            return {"status": 404, "error": "Route not found"}

        request["handler"] = route["handler"]
        request["client"] = client_id
        self.request_log.append(request)

        return {"status": 200, "handler": route["handler"],
                "rate_limit_remaining": self.rate_limiter.remaining(client_id)}

    def get_stats(self) -> Dict[str, Any]:
        by_handler = defaultdict(int)
        for req in self.request_log:
            by_handler[req.get("handler", "unknown")] += 1
        return {
            "total_requests": len(self.request_log),
            "by_handler": dict(by_handler),
            "registered_routes": len(self.router.routes),
            "api_keys": len(self.api_keys)
        }


def main():
    gateway = APIGateway()
    if len(sys.argv) < 2:
        print("Elysia API Gateway")
        print("Commands: route <path> <handler>, request <path>, stats, keys <key> <client>")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "route" and len(sys.argv) >= 4:
        gateway.register_route(sys.argv[2], sys.argv[3])
        print(f"[+] Route: {sys.argv[2]} -> {sys.argv[3]}")
    elif cmd == "request" and len(sys.argv) >= 3:
        result = gateway.handle_request(sys.argv[2])
        print(json.dumps(result, indent=2))
    elif cmd == "keys" and len(sys.argv) >= 4:
        gateway.add_api_key(sys.argv[2], sys.argv[3])
        print(f"[+] API key added for {sys.argv[3]}")
    elif cmd == "stats":
        print(json.dumps(gateway.get_stats(), indent=2))


if __name__ == "__main__":
    main()
