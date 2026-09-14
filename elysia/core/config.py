"""Central, validated configuration for Elysia.

One configuration source: ``elysia/config.json`` (or ELYSIA_CONFIG env).
Paths are derived from the repository root — nothing hard-coded is allowed
except through environment overrides (ELYSIA_WS, ELYSIA_LLM_URL, ...).

Supports profiles conceptually (development/testing/production) by allowing
a ``profile`` key that overlays specific settings; secrets are never printed.
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
    estimated_cost_usd: float = 0.0     # per-request estimate (for budget)
    priority: int = 0                   # lower = tried first (fallback routing)
    retries: int = 0


@dataclass
class WorkspaceConfig:
    root: str = ""
    max_read_chars: int = 9000


@dataclass
class SchedulerConfig:
    max_concurrency: int = 4
    max_attempts: int = 3
    lease_seconds: int = 1200
    heartbeat_grace_s: int = 60
    resource_reserve_mb: int = 1536
    worker_est_mb: int = 600
    timeout_default_s: int = 0          # 0 = no default per-task timeout
    dedup_enabled: bool = True


@dataclass
class GitConfig:
    auto_checkpoint: bool = False
    checkpoint_prefix: str = "elysia-checkpoint"
    never_commit: list = field(default_factory=lambda: [
        ".env", "*.key", "*.pem", "*.p12", "*.sqlite", "*.db", "*.log",
        "*.gguf", "*.onnx", "*.jar", "pool.lock", "pids", "*.tmp", "*.cache"])
    auto_push: bool = False
    remote: str = "origin"


@dataclass
class ApiConfig:
    host: str = "127.0.0.1"
    port: int = 8087
    api_key: str = ""
    rate_limit_per_min: int = 60


@dataclass
class MemoryConfig:
    dir: str = "state/memory"
    max_entries: int = 20000
    embed: bool = False                # basic keyword search if no embeddings


@dataclass
class ResourcesConfig:
    max_local_workers: int = 4
    reserve_mb: int = 1536
    worker_est_mb: int = 600
    max_cpu_fraction: float = 0.8


@dataclass
class LoggingConfig:
    dir: str = "logs"
    events_file: str = "events.jsonl"
    level: str = "info"


@dataclass
class ResearchConfig:
    enabled: bool = True
    max_sources: int = 5
    timeout_s: int = 240
    search_engine: str = "duckduckgo"  # duckduckgo | tavily | none
    tavily_api_key: str = ""


@dataclass
class ToolsConfig:
    enabled: bool = True
    allow_high_risk: bool = False
    default_permissions: list = field(default_factory=lambda: [
        "workspace:read", "workspace:write", "system:info"])


@dataclass
class ModelRoutingConfig:
    default_capabilities: list = field(default_factory=lambda: ["chat"])
    role_capabilities: dict = field(default_factory=lambda: {
        "planner": ["chat", "reasoning"],
        "architect": ["chat", "reasoning"],
        "implementer": ["chat", "coding"],
        "tester": ["chat", "coding"],
        "debugger": ["chat", "coding", "reasoning"],
        "code_reviewer": ["chat", "reasoning"],
        "security_reviewer": ["chat", "reasoning"],
        "documentation_agent": ["chat"],
        "research_agent": ["chat", "reasoning"],
        "integration_agent": ["chat", "coding"],
        "release_agent": ["chat"],
    })


@dataclass
class PluginsConfig:
    dir: str = "elysia/plugins"
    enabled: list = field(default_factory=list)  # plugin names enabled by default


@dataclass
class Config:
    name: str = "default"
    profile: str = ""
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    providers: list = field(default_factory=list)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    git: GitConfig = field(default_factory=GitConfig)
    api: ApiConfig = field(default_factory=ApiConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    resources: ResourcesConfig = field(default_factory=ResourcesConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    research: ResearchConfig = field(default_factory=ResearchConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    model_routing: ModelRoutingConfig = field(default_factory=ModelRoutingConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def repo_root(start=None) -> str:
    here = os.path.dirname(os.path.abspath(start or __file__))
    # <root>/elysia/core/config.py -> repo root
    return os.path.dirname(os.path.dirname(here))


def resolve_repo_path(value: str) -> str:
    value = os.path.expanduser(value)
    if os.path.isabs(value):
        return os.path.realpath(value)
    return os.path.realpath(os.path.join(repo_root(), value))


def env_path(name: str, default: str) -> str:
    raw = os.environ.get(name, "")
    return resolve_repo_path(raw if raw else default)


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _strlist(value) -> list:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def default_config() -> Config:
    cfg = Config()
    root = repo_root()
    cfg.workspace.root = env_path("ELYSIA_WS", os.path.join(root, "workspace"))
    cfg.memory.dir = env_path("ELYSIA_MEMORY", os.path.join(root, "state/memory"))
    cfg.logging.dir = env_path("ELYSIA_LOGS", os.path.join(root, "logs"))
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
        max_tokens=2048,
        priority=0,
    ))
    return cfg


def load_config(path: str | None = None, env: dict | None = None) -> Config:
    """Load a JSON config on top of defaults."""
    if env:
        _apply_env(env)
    cfg = default_config()
    if not path:
        path = os.environ.get("ELYSIA_CONFIG",
                              os.path.join(repo_root(), "elysia", "config.json"))
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            apply_dict(cfg, data)
        except (json.JSONDecodeError, OSError) as e:
            raise ValueError(f"invalid config {path}: {e}")
    return cfg


def _apply_env(env: dict) -> None:
    for k, v in env.items():
        os.environ[k] = str(v)


def apply_dict(cfg: Config, data: dict) -> None:
    if not isinstance(data, dict):
        return
    if isinstance(data.get("name"), str) and data["name"]:
        cfg.name = data["name"]
    if isinstance(data.get("profile"), str):
        cfg.profile = data["profile"]
    if isinstance(data.get("workspace"), dict):
        w = data["workspace"]
        if isinstance(w.get("root"), str) and w["root"]:
            cfg.workspace.root = resolve_repo_path(w["root"])
        if isinstance(w.get("max_read_chars"), int):
            cfg.workspace.max_read_chars = w["max_read_chars"]
    if isinstance(data.get("scheduler"), dict):
        s = data["scheduler"]
        pairs = (("max_concurrency", "int"), ("max_attempts", "int"),
                 ("lease_seconds", "int"), ("heartbeat_grace_s", "int"),
                 ("resource_reserve_mb", "int"), ("worker_est_mb", "int"),
                 ("timeout_default_s", "int"), ("dedup_enabled", "bool"))
        for k, typ in pairs:
            if k in s and s[k] is not None:
                if typ == "int":
                    v = _int(s[k], 0)
                    if v > 0 or k == "timeout_default_s":
                        setattr(cfg.scheduler, k, v)
                else:
                    if isinstance(s[k], bool):
                        cfg.scheduler.dedup_enabled = s[k]
    if isinstance(data.get("git"), dict):
        g = data["git"]
        if isinstance(g.get("auto_checkpoint"), bool):
            cfg.git.auto_checkpoint = g["auto_checkpoint"]
        if isinstance(g.get("checkpoint_prefix"), str) and g["checkpoint_prefix"]:
            cfg.git.checkpoint_prefix = g["checkpoint_prefix"]
        if isinstance(g.get("auto_push"), bool):
            cfg.git.auto_push = g["auto_push"]
        if isinstance(g.get("remote"), str) and g["remote"]:
            cfg.git.remote = g["remote"]
        if isinstance(g.get("never_commit"), list):
            cfg.git.never_commit = [str(x) for x in g["never_commit"]]
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
    if isinstance(data.get("memory"), dict):
        m = data["memory"]
        if isinstance(m.get("dir"), str) and m["dir"]:
            cfg.memory.dir = resolve_repo_path(m["dir"])
        if isinstance(m.get("max_entries"), int) and m["max_entries"] > 0:
            cfg.memory.max_entries = m["max_entries"]
        if isinstance(m.get("embed"), bool):
            cfg.memory.embed = m["embed"]
    if isinstance(data.get("resources"), dict):
        r = data["resources"]
        for k in ("max_local_workers", "reserve_mb", "worker_est_mb"):
            if isinstance(r.get(k), int) and r[k] > 0:
                setattr(cfg.resources, k, r[k])
        if isinstance(r.get("max_cpu_fraction"), (int, float)):
            cfg.resources.max_cpu_fraction = _float(r["max_cpu_fraction"], 0.8)
    if isinstance(data.get("logging"), dict):
        lg = data["logging"]
        if isinstance(lg.get("dir"), str) and lg["dir"]:
            cfg.logging.dir = resolve_repo_path(lg["dir"])
        if isinstance(lg.get("events_file"), str) and lg["events_file"]:
            cfg.logging.events_file = lg["events_file"]
        if isinstance(lg.get("level"), str):
            cfg.logging.level = lg["level"]
    if isinstance(data.get("research"), dict):
        r = data["research"]
        if isinstance(r.get("enabled"), bool):
            cfg.research.enabled = r["enabled"]
        if isinstance(r.get("max_sources"), int) and r["max_sources"] > 0:
            cfg.research.max_sources = r["max_sources"]
        if isinstance(r.get("timeout_s"), int) and r["timeout_s"] > 0:
            cfg.research.timeout_s = r["timeout_s"]
        if isinstance(r.get("search_engine"), str) and r["search_engine"]:
            cfg.research.search_engine = r["search_engine"]
        if isinstance(r.get("tavily_api_key"), str):
            cfg.research.tavily_api_key = r["tavily_api_key"]
    if isinstance(data.get("tools"), dict):
        t = data["tools"]
        if isinstance(t.get("enabled"), bool):
            cfg.tools.enabled = t["enabled"]
        if isinstance(t.get("allow_high_risk"), bool):
            cfg.tools.allow_high_risk = t["allow_high_risk"]
        if isinstance(t.get("default_permissions"), list):
            cfg.tools.default_permissions = [str(x) for x in t["default_permissions"]]
    if isinstance(data.get("model_routing"), dict):
        mr = data["model_routing"]
        if isinstance(mr.get("default_capabilities"), list):
            cfg.model_routing.default_capabilities = [str(x) for x in mr["default_capabilities"]]
        if isinstance(mr.get("role_capabilities"), dict):
            cfg.model_routing.role_capabilities = {
                str(k): [str(x) for x in v] for k, v in mr["role_capabilities"].items()}
    if isinstance(data.get("plugins"), dict):
        p = data["plugins"]
        if isinstance(p.get("dir"), str) and p["dir"]:
            cfg.plugins.dir = resolve_repo_path(p["dir"])
        if isinstance(p.get("enabled"), list):
            cfg.plugins.enabled = [str(x) for x in p["enabled"]]
    if isinstance(data.get("providers"), list) and data["providers"]:
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
                    capabilities=_strlist(p.get("capabilities")) or ["chat"],
                    concurrency=max(1, _int(p.get("concurrency"), 1)),
                    timeout_s=_int(p.get("timeout_s"), 300),
                    max_tokens=_int(p.get("max_tokens"), 2048),
                    temperature=_float(p.get("temperature"), 0.2),
                    estimated_cost_usd=_float(p.get("estimated_cost_usd"), 0.0),
                    priority=_int(p.get("priority"), 0),
                    retries=_int(p.get("retries"), 0),
                ))


def to_dict(cfg: Config) -> dict:
    d = asdict(cfg)
    # Redact secrets before any display/serialization.
    return redact_config(d)


def redact_config(d: dict, seen=None) -> dict:
    """Deep-redact api_key / tokens so configs are safe to print/log."""
    if seen is None:
        seen = set()
    key = id(d)
    if key in seen:
        return d
    seen.add(key)
    if isinstance(d, dict):
        out = {}
        for k, v in d.items():
            if "api_key" in k or "token" in k or "secret" in k:
                out[k] = "***REDACTED***" if v else v
            else:
                out[k] = redact_config(v, seen)
        return out
    if isinstance(d, list):
        return [redact_config(x, seen) for x in d]
    return d


def validate(cfg: Config) -> list[str]:
    """Return a list of configuration problems (empty = fully valid)."""
    problems = []
    if not cfg.workspace.root:
        problems.append("workspace.root is empty")
    if not cfg.providers:
        problems.append("no providers configured")
    for p in cfg.providers:
        if not p.model:
            problems.append(f"provider {p.label or p.kind} has no model")
        if p.concurrency < 1:
            problems.append(f"provider {p.label} concurrency < 1")
    if cfg.api.port < 1 or cfg.api.port > 65535:
        problems.append(f"api.port out of range: {cfg.api.port}")
    if not os.path.isabs(cfg.workspace.root):
        problems.append(f"workspace.root not absolute: {cfg.workspace.root}")
    return problems
