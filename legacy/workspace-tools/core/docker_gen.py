#!/usr/bin/env python3
"""
Elysia Docker Containerization - Task 1230
Dockerfile and docker-compose generation for Elysia components.
"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


class DockerGenerator:
    def __init__(self, output_dir: str = None):
        self.output_dir = Path(output_dir or ".")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_dockerfile(self, service: str = "orchestrator") -> str:
        dockerfiles = {
            "orchestrator": """FROM python:3.12-slim
WORKDIR /app
COPY orchestrator/ /app/orchestrator/
COPY workspace/ /app/workspace/
RUN pip install --no-cache-dir sqlite3
EXPOSE 8087
CMD ["python3", "orchestrator/server.py", "--port", "8087"]
""",
            "worker": """FROM python:3.12-slim
WORKDIR /app
COPY orchestrator/ /app/orchestrator/
COPY workspace/ /app/workspace/
RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*
CMD ["python3", "orchestrator/worker_local.py", "docker-worker", "/app/workspace", "10"]
""",
            "monitor": """FROM python:3.12-slim
WORKDIR /app
COPY orchestrator/ /app/orchestrator/
CMD ["python3", "orchestrator/monitor.py"]
""",
            "inference": """FROM ubuntu:22.04
RUN apt-get update && apt-get install -y llama-cpp-python curl
EXPOSE 11434
CMD ["llama-server", "-m", "/models/qwen15b-q4.gguf", "--ctx-size", "8192", "--port", "11434"]
"""
        }
        content = dockerfiles.get(service, dockerfiles["orchestrator"])
        path = self.output_dir / f"Dockerfile.{service}"
        path.write_text(content)
        return str(path)

    def generate_compose(self) -> str:
        compose = """version: '3.8'
services:
  inference:
    build:
      dockerfile: Dockerfile.inference
    ports:
      - "11434:11434"
    volumes:
      - ./models:/models
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 4G

  orchestrator:
    build:
      dockerfile: Dockerfile.orchestrator
    ports:
      - "8087:8087"
    depends_on:
      - inference
    environment:
      - INFERENCE_URL=http://inference:11434
    restart: unless-stopped

  worker:
    build:
      dockerfile: Dockerfile.worker
    depends_on:
      - inference
      - orchestrator
    environment:
      - INFERENCE_URL=http://inference:11434
      - ORCHESTRATOR_URL=http://orchestrator:8087
    restart: unless-stopped
    deploy:
      replicas: 4
      resources:
        limits:
          memory: 600M

  monitor:
    build:
      dockerfile: Dockerfile.monitor
    depends_on:
      - orchestrator
    restart: unless-stopped
"""
        path = self.output_dir / "docker-compose.yml"
        path.write_text(compose)
        return str(path)

    def generate_nginx(self) -> str:
        nginx = """server {
    listen 80;
    server_name localhost;

    location / {
        proxy_pass http://orchestrator:8087;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    location /api/ {
        proxy_pass http://orchestrator:8087/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
"""
        path = self.output_dir / "nginx.conf"
        path.write_text(nginx)
        return str(path)


def main():
    gen = DockerGenerator()
    if len(sys.argv) < 2:
        print("Elysia Docker Generator")
        print("Commands: dockerfile <service>, compose, nginx")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "dockerfile" and len(sys.argv) >= 3:
        path = gen.generate_dockerfile(sys.argv[2])
        print(f"[+] Dockerfile: {path}")
    elif cmd == "compose":
        path = gen.generate_compose()
        print(f"[+] docker-compose.yml: {path}")
    elif cmd == "nginx":
        path = gen.generate_nginx()
        print(f"[+] nginx.conf: {path}")


if __name__ == "__main__":
    main()
