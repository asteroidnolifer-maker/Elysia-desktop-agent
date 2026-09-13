"""Core configuration system for Elysia.

One validated configuration source. Paths are derived from the repository root
or explicit environment variables — never hard-coded machine paths.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict


@dataclass
class ProviderConfig:
    kind: str = "openai"            # openai | llama | nim | cli
    label: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    capabilities: list = field(default_factory=lambda: ["chat"])
    concurrency: int = 1
    timeout_s: int = 300
    max_tokens: int = 2048
    temperature: float = 0.2


@dataclass
class WorkspaceConfig:
    root: str = ""                  # absolute path to the writable workspace
    max_read_chars: int = 9000      # context budget for attached reference files


@dataclass
class SchedulerConfig:
    max_concurrency: int = 4        # logical workers allowed at once
    max_attempts: int = 3
    lease_seconds: int = 1200       # task lease before auto-release
    heartbeat_grace_s: int = 60
    resource_reserve_mb: int = 1536  # keep this much RAM free
    worker_est_mb: int = 600        # estimated RAM per local worker


@dataclass
class GitConfig:
    auto_checkpoint: bool = False
    checkpoint_prefix: str = "elysia-checkpoint"


@dataclass
class ApiConfig:
    host: str = "127.0.0.1"
    port: int = 8087
    api_key: str = ""
    rate_limit_per_min: int = 60


@dataclass
class Config:
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    providers: list = field(default_factory=list)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    git: GitConfig = field(default_factory=GitConfig)
    api: ApiConfig = field(default_factory=ApiConfig)


def repo_root(start=None) -> str:
    """Absolute path of the repository root, discovered from the package file
    location (portable — works after cloning anywhere)."""
    here = os.path.dirname(os.path.abspath(start or __file__))
    # <root>/elysia/core/config.py -> dirname twice reaches the repo root.
    root = os.path.dirname(os.path.dirname(here))
    return root


def resolve_repo_path(value: str) -> str:
    """Resolve a possibly-relative path against the repo root (absolute result)."""
    value = os.path.expanduser(value)
    if os.path.isabs(value):
        return os.path.realpath(value)
    return os.path.realpath(os.path.join(repo_root(), value))


def env_path(name: str, default: str) -> str:
    """Expand an environment-provided path (absolute, or relative to the repo
    root). If the env var is unset, expand `default` the same way."""
    raw = os.environ.get(name, "")
    return resolve_repo_path(raw if raw else default)


def default_config() -> Config:
    cfg = Config()
    root = repo_root()
    cfg.workspace.root = env_path("ELYSIA_WS", os.path.join(root, "workspace"))
    # Standard local provider (llama.cpp / Ollama on :11434).
    cfg.providers.append(ProviderConfig(
        kind="openai",
        label="local",
        base_url=os.environ.get("ELYSIA_LLM_URL", "http://127.0.0.1:11434/v1"),
        api_key=os.environ.get("ELYSIA_LLM_KEY", "none"),
        model=os.environ.get("ELYSIA_MODEL", "qwen2.5-coder:7b"),
        capabilities=["chat", "coding"],
        concurrency=2,
        timeout_s=900,
    ))
    return cfg


def load_config(path: str | None = None) -> Config:
    """Load a JSON config on top of defaults. Missing file -> defaults."""
    cfg = default_config()
    if not path:
        path = os.environ.get("ELYSIA_CONFIG", os.path.join(repo_root(), "elysia", "config.json"))
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            apply_dict(cfg, data)
        except (json.JSONDecodeError, OSError) as e:
            raise ValueError(f"invalid config {path}: {e}")
    return cfg


def apply_dict(cfg: Config, data: dict) -> None:
    if not isinstance(data, dict):
        return
    if isinstance(data.get("workspace"), dict):
        w = data["workspace"]
        if isinstance(w.get("root"), str) and w["root"]:
            cfg.workspace.root = resolve_repo_path(w["root"])
        if isinstance(w.get("max_read_chars"), int):
            cfg.workspace.max_read_chars = w["max_read_chars"]
    if isinstance(data.get("scheduler"), dict):
        s = data["scheduler"]
        for k in ("max_concurrency", "max_attempts", "lease_seconds",
                  "heartbeat_grace_s", "resource_reserve_mb", "worker_est_mb"):
            if isinstance(s.get(k), int) and s[k] > 0:
                setattr(cfg.scheduler, k, s[k])
    if isinstance(data.get("git"), dict):
        g = data["git"]
        if isinstance(g.get("auto_checkpoint"), bool):
            cfg.git.auto_checkpoint = g["auto_checkpoint"]
        if isinstance(g.get("checkpoint_prefix"), str) and g["checkpoint_prefix"]:
            cfg.git.checkpoint_prefix = g["checkpoint_prefix"]
    if isinstance(data.get("api"), dict):
        a = data["api"]
        if isinstance(a.get("host"), str):
            cfg.api.host = a["host"]
        if isinstance(a.get("port"), int) and 0 < a["port"] < 65536:
            cfg.api.port = a["port"]
        if isinstance(a.get("api_key"), str):
            cfg.api.api_key = a["api_key"]
        if isinstance(a.get("rate_limit_per_min"), int) and a["rate_limit_per_min"] > 0:
            cfg.api.rate_limit_per_min = a["rate_limit_per_min"]
    if isinstance(data.get("providers"), list) and data["providers"]:
        # A recursive config overrides the default local provider list entirely.
        cfg.providers = []
        for p in data["providers"]:
            if isinstance(p, dict) and isinstance(p.get("model"), str) and p["model"]:
                label = p.get("label") or f"{p.get('kind', 'openai')}:{p['model']}"
                cfg.providers.append(ProviderConfig(
                    kind=p.get("kind", "openai"),
                    label=label,
                    base_url=p.get("base_url", ""),
                    api_key=p.get("api_key", ""),
                    model=p["model"],
                    capabilities=p.get("capabilities") or ["chat"],
                    concurrency=max(1, int(p.get("concurrency") or 1)),
                    timeout_s=int(p.get("timeout_s") or 300),
                    max_tokens=int(p.get("max_tokens") or 2048),
                    temperature=float(p.get("temperature") or 0.2),
                ))


def to_dict(cfg: Config) -> dict:
    return asdict(cfg)