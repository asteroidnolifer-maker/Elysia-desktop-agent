#!/usr/bin/env python3
"""
Elysia Configuration Manager - Task 1217
Hierarchical config with env overrides, validation, and hot reload.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_CONFIG = {
    "version": "1.0.0",
    "environment": "development",
    "logging": {
        "level": "INFO",
        "max_bytes": 10000000,
        "backup_count": 5
    },
    "inference": {
        "host": "127.0.0.1",
        "port": 11434,
        "model": "qwen2.5-coder:7b",
        "ctx_size": 8192,
        "timeout": 120
    },
    "agent_core": {
        "host": "127.0.0.1",
        "port": 8085
    },
    "hud": {
        "host": "127.0.0.1",
        "port": 8087
    },
    "worker": {
        "max_per_task": 3,
        "max_concurrent": 8,
        "ram_reserve_mb": 1536,
        "worker_ram_mb": 600
    },
    "database": {
        "path": "orchestrator/taskboard.sqlite",
        "wal_mode": True
    },
    "security": {
        "sandbox_writes": True,
        "max_prompt_tokens": 4000,
        "allowed_paths": ["workspace/"]
    },
    "notifications": {
        "enabled": False,
        "channels": ["log"]
    },
    "analytics": {
        "enabled": True,
        "retention_days": 90
    }
}


class ConfigManager:
    def __init__(self, config_dir: str = None):
        self.config_dir = Path(config_dir or Path(__file__).parent.parent / "config")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "elysia.json"
        self._config = {}
        self._watchers = []
        self._load()

    def _load(self):
        if self.config_file.exists():
            self._config = json.loads(self.config_file.read_text())
        else:
            self._config = DEFAULT_CONFIG.copy()
            self._save()
        self._apply_env_overrides()
        self._config["_loaded_at"] = datetime.now().isoformat()

    def _apply_env_overrides(self):
        prefix = "ELYSIA_"
        for key, val in os.environ.items():
            if not key.startswith(prefix):
                continue
            parts = key[len(prefix):].lower().split("_")
            cfg = self._config
            for p in parts[:-1]:
                if p not in cfg:
                    cfg[p] = {}
                cfg = cfg[p]
            try:
                cfg[parts[-1]] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                cfg[parts[-1]] = val

    def _save(self):
        data = {k: v for k, v in self._config.items() if not k.startswith("_")}
        self.config_file.write_text(json.dumps(data, indent=2))

    def get(self, path: str, default: Any = None) -> Any:
        keys = path.split(".")
        cfg = self._config
        for k in keys:
            if isinstance(cfg, dict) and k in cfg:
                cfg = cfg[k]
            else:
                return default
        return cfg

    def set(self, path: str, value: Any, persist: bool = True):
        keys = path.split(".")
        cfg = self._config
        for k in keys[:-1]:
            if k not in cfg:
                cfg[k] = {}
            cfg = cfg[k]
        old = cfg.get(keys[-1])
        cfg[keys[-1]] = value
        if persist:
            self._save()
        for w in self._watchers:
            w(path, old, value)

    def watch(self, callback):
        self._watchers.append(callback)

    def validate(self, schema: Dict[str, Any] = None) -> List[str]:
        errors = []
        schema = schema or {
            "inference.port": {"type": "int", "min": 1, "max": 65535},
            "worker.max_concurrent": {"type": "int", "min": 1, "max": 32},
            "worker.ram_reserve_mb": {"type": "int", "min": 256},
            "logging.level": {"type": "str", "values": ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]}
        }
        for path, rules in schema.items():
            val = self.get(path)
            if val is None:
                continue
            if "type" in rules:
                expected = rules["type"]
                actual = type(val).__name__
                if expected == "int" and not isinstance(val, int):
                    errors.append(f"{path}: expected int, got {actual}")
                elif expected == "str" and not isinstance(val, str):
                    errors.append(f"{path}: expected str, got {actual}")
            if "min" in rules and isinstance(val, (int, float)):
                if val < rules["min"]:
                    errors.append(f"{path}: {val} < min({rules['min']})")
            if "max" in rules and isinstance(val, (int, float)):
                if val > rules["max"]:
                    errors.append(f"{path}: {val} > max({rules['max']})")
            if "values" in rules and val not in rules["values"]:
                errors.append(f"{path}: '{val}' not in {rules['values']}")
        return errors

    def get_all(self, mask_secrets: bool = True) -> Dict[str, Any]:
        config = {k: v for k, v in self._config.items() if not k.startswith("_")}
        if mask_secrets:
            for k in list(config.keys()):
                if "key" in k.lower() or "secret" in k.lower() or "password" in k.lower():
                    if isinstance(config[k], str) and len(config[k]) > 4:
                        config[k] = config[k][:4] + "***"
        return config

    def export_env(self) -> str:
        lines = []
        def flatten(d, prefix=""):
            for k, v in d.items():
                key = f"ELYSIA_{prefix}{k}".upper()
                if isinstance(v, dict):
                    flatten(v, f"{k}_")
                else:
                    lines.append(f"export {key}={json.dumps(v)}")
        flatten(self._config)
        return "\n".join(lines)

    def reset(self):
        self._config = DEFAULT_CONFIG.copy()
        self._save()


def main():
    config = ConfigManager()

    if len(sys.argv) < 2:
        print("Elysia Config Manager")
        print("Commands: get <path>, set <path> <value>, list, validate, export-env, reset")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "get" and len(sys.argv) >= 3:
        val = config.get(sys.argv[2])
        print(json.dumps(val, indent=2) if isinstance(val, (dict, list)) else val)
    elif cmd == "set" and len(sys.argv) >= 4:
        try:
            val = json.loads(sys.argv[3])
        except json.JSONDecodeError:
            val = sys.argv[3]
        config.set(sys.argv[2], val)
        print(f"[+] Set {sys.argv[2]} = {val}")
    elif cmd == "list":
        print(json.dumps(config.get_all(), indent=2))
    elif cmd == "validate":
        errors = config.validate()
        if errors:
            for e in errors:
                print(f"[-] {e}")
        else:
            print("[+] Config valid")
    elif cmd == "export-env":
        print(config.export_env())
    elif cmd == "reset":
        config.reset()
        print("[+] Config reset to defaults")


if __name__ == "__main__":
    main()
