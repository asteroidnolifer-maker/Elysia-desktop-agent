#!/usr/bin/env python3
"""
Elysia Plugin System - Task 1231
Dynamic plugin loading, lifecycle management, and hook system.
"""
import json
import os
import sys
import importlib.util
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class PluginMeta:
    def __init__(self, name: str, version: str, description: str,
                 author: str = "elysia", hooks: List[str] = None):
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.hooks = hooks or []


class Plugin:
    def __init__(self, meta: PluginMeta, instance: Any = None):
        self.meta = meta
        self.instance = instance
        self.enabled = True
        self.loaded_at = datetime.now().isoformat()


class HookSystem:
    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = {}

    def register(self, hook_name: str, callback: Callable):
        if hook_name not in self._hooks:
            self._hooks[hook_name] = []
        self._hooks[hook_name].append(callback)

    def unregister(self, hook_name: str, callback: Callable):
        if hook_name in self._hooks:
            self._hooks[hook_name] = [h for h in self._hooks[hook_name] if h != callback]

    def trigger(self, hook_name: str, *args, **kwargs) -> List[Any]:
        results = []
        for callback in self._hooks.get(hook_name, []):
            try:
                result = callback(*args, **kwargs)
                results.append(result)
            except Exception as e:
                results.append({"error": str(e)})
        return results

    def list_hooks(self) -> Dict[str, int]:
        return {name: len(callbacks) for name, callbacks in self._hooks.items()}


class PluginManager:
    def __init__(self, plugin_dir: str = None):
        self.plugin_dir = Path(plugin_dir or Path(__file__).parent / ".data" / "plugins")
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        self.plugins: Dict[str, Plugin] = {}
        self.hooks = HookSystem()
        self.registry_file = self.plugin_dir / "registry.json"
        self._load_registry()

    def _load_registry(self):
        if self.registry_file.exists():
            data = json.loads(self.registry_file.read_text())
            for name, info in data.items():
                meta = PluginMeta(**info.get("meta", {}))
                self.plugins[name] = Plugin(meta=meta, enabled=info.get("enabled", True))

    def _save_registry(self):
        data = {}
        for name, plugin in self.plugins.items():
            data[name] = {
                "meta": {
                    "name": plugin.meta.name,
                    "version": plugin.meta.version,
                    "description": plugin.meta.description,
                    "author": plugin.meta.author,
                    "hooks": plugin.meta.hooks
                },
                "enabled": plugin.enabled,
                "loaded_at": plugin.loaded_at
            }
        self.registry_file.write_text(json.dumps(data, indent=2))

    def load_from_file(self, path: str) -> bool:
        try:
            spec = importlib.util.spec_from_file_location("plugin", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "PLUGIN_META"):
                meta = module.PLUGIN_META
            else:
                meta = PluginMeta(
                    name=Path(path).stem,
                    version="0.0.1",
                    description="External plugin"
                )

            instance = module.Plugin() if hasattr(module, "Plugin") else None
            plugin = Plugin(meta=meta, instance=instance)

            for hook_name in meta.hooks:
                if hasattr(module, hook_name):
                    self.hooks.register(hook_name, getattr(module, hook_name))

            self.plugins[meta.name] = plugin
            self._save_registry()
            print(f"[+] Loaded plugin: {meta.name} v{meta.version}")
            return True
        except Exception as e:
            print(f"[-] Failed to load {path}: {e}")
            return False

    def register_plugin(self, name: str, version: str, description: str,
                        hooks: List[str] = None):
        meta = PluginMeta(name=name, version=version, description=description,
                          hooks=hooks or [])
        self.plugins[name] = Plugin(meta=meta)
        self._save_registry()
        print(f"[+] Registered plugin: {name}")

    def enable(self, name: str) -> bool:
        if name in self.plugins:
            self.plugins[name].enabled = True
            self._save_registry()
            return True
        return False

    def disable(self, name: str) -> bool:
        if name in self.plugins:
            self.plugins[name].enabled = False
            self._save_registry()
            return True
        return False

    def list_plugins(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": p.meta.name,
                "version": p.meta.version,
                "description": p.meta.description,
                "enabled": p.enabled,
                "hooks": p.meta.hooks
            }
            for p in self.plugins.values()
        ]

    def uninstall(self, name: str) -> bool:
        if name in self.plugins:
            del self.plugins[name]
            self._save_registry()
            print(f"[+] Uninstalled plugin: {name}")
            return True
        return False


def create_plugin_scaffold(name: str, directory: str = None):
    plugin_dir = Path(directory or Path(__file__).parent / ".data" / "plugins" / name)
    plugin_dir.mkdir(parents=True, exist_ok=True)

    init_code = f'''#!/usr/bin/env python3
"""
{name} - Elysia Plugin
"""

PLUGIN_META = {{
    "name": "{name}",
    "version": "0.1.0",
    "description": "A new Elysia plugin",
    "author": "elysia",
    "hooks": ["on_task_complete", "on_error"]
}}


class Plugin:
    def __init__(self):
        self.name = "{name}"
        self.state = {{}}

    def on_task_complete(self, task):
        print(f"[{name}] Task complete: {{task}}")

    def on_error(self, error):
        print(f"[{name}] Error: {{error}}")
'''
    (plugin_dir / "__init__.py").write_text(init_code)
    (plugin_dir / "plugin.json").write_text(json.dumps({
        "name": name, "version": "0.1.0", "entry": "__init__.py"
    }, indent=2))
    print(f"[+] Plugin scaffold created at {plugin_dir}")
    return str(plugin_dir)


def main():
    manager = PluginManager()

    if len(sys.argv) < 2:
        print("Elysia Plugin Manager")
        print("Commands: list, load <path>, create <name>, enable <name>, disable <name>, hooks, uninstall <name>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "list":
        plugins = manager.list_plugins()
        for p in plugins:
            status = "enabled" if p["enabled"] else "disabled"
            print(f"  {p['name']} v{p['version']} [{status}] - {p['description']}")
    elif cmd == "load" and len(sys.argv) >= 3:
        manager.load_from_file(sys.argv[2])
    elif cmd == "create" and len(sys.argv) >= 3:
        create_plugin_scaffold(sys.argv[2])
    elif cmd == "enable" and len(sys.argv) >= 3:
        manager.enable(sys.argv[2])
    elif cmd == "disable" and len(sys.argv) >= 3:
        manager.disable(sys.argv[2])
    elif cmd == "hooks":
        hooks = manager.hooks.list_hooks()
        for name, count in hooks.items():
            print(f"  {name}: {count} handlers")
    elif cmd == "uninstall" and len(sys.argv) >= 3:
        manager.uninstall(sys.argv[2])


if __name__ == "__main__":
    main()
