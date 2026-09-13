#!/usr/bin/env python3
"""
Elysia Load Balancer - Task 1256
Round-robin, weighted, and least-connections load balancing.
"""
import json
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional


class Backend:
    def __init__(self, host: str, port: int, weight: int = 1):
        self.host = host
        self.port = port
        self.weight = weight
        self.active_connections = 0
        self.total_requests = 0
        self.failures = 0
        self.last_check = time.time()

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host, "port": self.port, "weight": self.weight,
            "active_connections": self.active_connections,
            "total_requests": self.total_requests,
            "failures": self.failures
        }


class LoadBalancer:
    def __init__(self):
        self.backends: List[Backend] = []
        self.rr_index = 0
        self.strategy = "round_robin"

    def add_backend(self, host: str, port: int, weight: int = 1):
        self.backends.append(Backend(host, port, weight))

    def remove_backend(self, host: str, port: int):
        self.backends = [b for b in self.backends
                        if not (b.host == host and b.port == port)]

    def next_backend(self) -> Optional[Backend]:
        healthy = [b for b in self.backends if b.failures < 5]
        if not healthy:
            return None

        if self.strategy == "round_robin":
            backend = healthy[self.rr_index % len(healthy)]
            self.rr_index += 1
        elif self.strategy == "weighted":
            total_weight = sum(b.weight for b in healthy)
            r = time.time() % total_weight
            cumulative = 0
            backend = healthy[0]
            for b in healthy:
                cumulative += b.weight
                if r <= cumulative:
                    backend = b
                    break
        elif self.strategy == "least_connections":
            backend = min(healthy, key=lambda b: b.active_connections)
        else:
            backend = healthy[self.rr_index % len(healthy)]
            self.rr_index += 1

        backend.active_connections += 1
        backend.total_requests += 1
        return backend

    def release_connection(self, backend: Backend):
        backend.active_connections = max(0, backend.active_connections - 1)

    def record_failure(self, backend: Backend):
        backend.failures += 1

    def get_status(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "backends": [b.to_dict() for b in self.backends],
            "total_backends": len(self.backends),
            "healthy_backends": len([b for b in self.backends if b.failures < 5])
        }


def main():
    lb = LoadBalancer()
    if len(sys.argv) < 2:
        print("Elysia Load Balancer")
        print("Commands: add <host> <port> [weight], next, status, strategy <name>")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "add" and len(sys.argv) >= 4:
        weight = int(sys.argv[4]) if len(sys.argv) > 4 else 1
        lb.add_backend(sys.argv[2], int(sys.argv[3]), weight)
        print(f"[+] Backend added: {sys.argv[2]}:{sys.argv[3]}")
    elif cmd == "next":
        backend = lb.next_backend()
        if backend:
            print(f"Backend: {backend.url}")
        else:
            print("No healthy backends")
    elif cmd == "strategy" and len(sys.argv) >= 3:
        lb.strategy = sys.argv[2]
        print(f"[+] Strategy: {lb.strategy}")
    elif cmd == "status":
        print(json.dumps(lb.get_status(), indent=2))


if __name__ == "__main__":
    main()
