"""Plugin system: isolated, permission-scoped extension modules.

A plugin is a directory with ``plugin.json`` + ``plugin.py`` exposing
``def register(api) -> None``. The API surface given to plugins is explicit
(state + tool registry), and each plugin declares the permissions it needs.
Plugins not in the allow-list are not loaded.
"""
from __future__ import annotations

import importlib.util
import json
import os

from .events import EventBus
from .tools import ToolRegistry, ToolResult

MANIFEST_SCHEMA = {
    "name": str, "description": str, "version": str,
    "permissions": list,
}


class PluginError(Exception):
    pass


class Plugin:
    def __init__(self, path: str, name: str = "", description: str = "",
                 version: str = "", permissions: list | None = None,
                 enabled: bool = False):
        self.path = path
        self.name = name
        self.description = description
        self.version = version
        self.permissions = permissions or []
        self.enabled = enabled
        self.loaded = False
        self.error: str | None = None

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description,
                "version": self.version, "path": self.path,
                "permissions": self.permissions, "enabled": self.enabled,
                "loaded": self.loaded, "error": self.error}


def load_plugin_manifest(path: str) -> Plugin:
    manifest_path = os.path.join(path, "plugin.json")
    if not os.path.isfile(manifest_path):
        raise PluginError(f"no plugin.json in {path}")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise PluginError(f"bad manifest {manifest_path}: {e}") from e
    if not isinstance(m, dict):
        raise PluginError("manifest must be an object")
    required = ["name", "description", "version"]
    for r in required:
        if not isinstance(m.get(r), str) or not m[r]:
            raise PluginError(f"manifest missing/invalid {r}")
    if not isinstance(m.get("permissions", []), list):
        raise PluginError("manifest permissions must be a list")
    return Plugin(path=path, name=m["name"], description=m["description"],
                  version=m["version"], permissions=m.get("permissions", []))


class PluginManager:
    def __init__(self, plugins_dir: str, allow_list: list | None = None,
                 events: EventBus | None = None):
        self.plugins_dir = os.path.realpath(plugins_dir)
        self.allow_list = set(allow_list or [])
        self.events = events or EventBus()
        self._plugins: dict[str, Plugin] = {}

    def discover(self) -> list[Plugin]:
        if not os.path.isdir(self.plugins_dir):
            return []
        found = []
        for name in sorted(os.listdir(self.plugins_dir)):
            pdir = os.path.join(self.plugins_dir, name)
            if not os.path.isdir(pdir):
                continue
            try:
                plugin = load_plugin_manifest(pdir)
            except PluginError as e:
                plugin = Plugin(path=pdir, name=name, description="",
                                version="", enabled=False, )
                plugin.error = str(e)
                plugin.enabled = False
            plugin.enabled = (not self.allow_list) or (name in self.allow_list)
            self._plugins[plugin.name] = plugin
            found.append(plugin)
        return found

    def load(self, name: str, tools: ToolRegistry) -> Plugin:
        plugin = self._plugins.get(name)
        if not plugin or not plugin.enabled:
            raise PluginError(f"plugin {name} not discovered/enabled")
        py = os.path.join(plugin.path, "plugin.py")
        if not os.path.isfile(py):
            plugin.error = "no plugin.py"
            return plugin
        spec = importlib.util.spec_from_file_location(f"elysia_plugin_{name}", py)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
            if not hasattr(mod, "register"):
                raise PluginError("plugin.py has no register(api)")
            api = {"tools": tools, "events": self.events,
                   "permissions": list(plugin.permissions)}
            mod.register(api)
            plugin.loaded = True
            plugin.error = None
        except Exception as e:  # noqa: BLE001
            plugin.error = f"{type(e).__name__}: {e}"
            plugin.loaded = False
        return plugin

    def list(self) -> list[Plugin]:
        if not self._plugins:
            self.discover()
        return list(self._plugins.values())