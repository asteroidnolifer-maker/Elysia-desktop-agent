#!/usr/bin/env python3
"""
Android Widget for Elysia
Home screen widget data provider.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class WidgetProvider:
    """Provide data for Android home screen widget."""

    def __init__(self, hud_url: str = "http://127.0.0.1:8087"):
        self.hud_url = hud_url
        self.widget_path = Path(__file__).parent / "widget_data.json"

    def get_widget_data(self) -> Dict[str, Any]:
        try:
            import urllib.request
            with urllib.request.urlopen(f"{self.hud_url}/api/state", timeout=5) as resp:
                state = json.loads(resp.read())

            counts = state.get("counts", {})
            return {
                "open": counts.get("open", 0),
                "claimed": counts.get("claimed", 0),
                "done": counts.get("done", 0),
                "failed": counts.get("failed", 0),
                "health": state.get("health", {}),
                "timestamp": datetime.now().isoformat(),
                "widget_title": f"Elysia: {counts.get('open', 0)} open tasks"
            }
        except Exception as e:
            return {"error": str(e), "open": 0, "claimed": 0, "done": 0}

    def get_compact_data(self) -> Dict[str, Any]:
        data = self.get_widget_data()
        return {
            "title": data.get("widget_title", "Elysia"),
            "subtitle": f"{data.get('done', 0)} done | {data.get('failed', 0)} failed",
            "open_count": data.get("open", 0),
            "health_ok": data.get("health", {}).get("model", False)
        }

    def save_widget_data(self):
        data = self.get_compact_data()
        self.widget_path.write_text(json.dumps(data, indent=2))
        return data

    def get_widget_actions(self) -> List[Dict[str, str]]:
        return [
            {"id": "view_tasks", "label": "View Tasks", "icon": "list"},
            {"id": "add_task", "label": "Add Task", "icon": "add"},
            {"id": "start_pool", "label": "Start Workers", "icon": "play"},
            {"id": "stop_pool", "label": "Stop Workers", "icon": "stop"},
            {"id": "status", "label": "System Status", "icon": "info"}
        ]


class WidgetConfig:
    """Widget configuration for Android."""

    SIZES = {
        "small": {"width": 2, "height": 1, "max_items": 3},
        "medium": {"width": 4, "height": 2, "max_items": 6},
        "large": {"width": 4, "height": 3, "max_items": 10}
    }

    THEMES = {
        "dark": {"bg": "#1a1a2e", "text": "#ffffff", "accent": "#269395"},
        "light": {"bg": "#ffffff", "text": "#000000", "accent": "#269395"},
        "transparent": {"bg": "#00000000", "text": "#ffffff", "accent": "#269395"}
    }

    @classmethod
    def get_config(cls, size: str = "medium", theme: str = "dark") -> Dict[str, Any]:
        return {
            "size": cls.SIZES.get(size, cls.SIZES["medium"]),
            "theme": cls.THEMES.get(theme, cls.THEMES["dark"]),
            "refresh_interval": 300,
            "show_agents": True,
            "show_health": True
        }


def main():
    import sys
    provider = WidgetProvider()

    if len(sys.argv) < 2:
        print("Widget Data Provider")
        print("=" * 40)
        print("\nCommands:")
        print("  data       - Get widget data")
        print("  compact    - Get compact widget data")
        print("  actions    - Get widget actions")
        print("  save       - Save widget data to file")
        print("  config     - Widget config")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "data":
        data = provider.get_widget_data()
        print(json.dumps(data, indent=2))

    elif cmd == "compact":
        data = provider.get_compact_data()
        print(f"Title: {data['title']}")
        print(f"Subtitle: {data['subtitle']}")
        print(f"Open: {data['open_count']}")

    elif cmd == "actions":
        actions = provider.get_widget_actions()
        for a in actions:
            print(f"  {a['id']}: {a['label']}")

    elif cmd == "save":
        data = provider.save_widget_data()
        print(f"Saved: {data}")

    elif cmd == "config":
        config = WidgetConfig.get_config()
        print(json.dumps(config, indent=2))

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
