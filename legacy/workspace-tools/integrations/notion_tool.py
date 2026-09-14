#!/usr/bin/env python3
"""
Composio Notion Integration for Elysia
Tool calling interface for Notion operations via Composio.
"""
import os
import json
from typing import Optional, Dict, Any, List
from pathlib import Path

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "ak_46fOkxnX44Dl2ktKdyu5")


class NotionTool:
    """Notion tool using Composio for AI agent tool calling."""

    def __init__(self):
        self.toolset = None
        self._initialized = False

    def initialize(self):
        try:
            from composio import ComposioToolSet
            self.toolset = ComposioToolSet(api_key=COMPOSIO_API_KEY)
            self._initialized = True
            return True
        except ImportError:
            print("[-] composio-core not installed. Run: pip install composio-core")
            return False
        except Exception as e:
            print(f"[-] Init failed: {e}")
            return False

    def get_tools(self) -> List[Dict[str, Any]]:
        if not self._initialized:
            self.initialize()
        try:
            tools = self.toolset.get_tools(app=["notion"])
            return [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools]
        except Exception as e:
            print(f"[-] Error getting tools: {e}")
            return []

    def execute(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._initialized:
            self.initialize()
        try:
            result = self.toolset.execute_tool(tool=tool_name, params=params)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_page(self, parent_database_id: str, title: str, properties: Dict[str, Any] = None) -> Dict[str, Any]:
        return self.execute("NOTION_CREATE_PAGE", {"parent_database_id": parent_database_id, "title": title, "properties": properties or {}})

    def query_database(self, database_id: str, filter_obj: Dict[str, Any] = None, page_size: int = 10) -> Dict[str, Any]:
        return self.execute("NOTION_QUERY_DATABASE", {"database_id": database_id, "filter": filter_obj, "page_size": page_size})

    def update_page(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        return self.execute("NOTION_UPDATE_PAGE", {"page_id": page_id, "properties": properties})

    def get_page(self, page_id: str) -> Dict[str, Any]:
        return self.execute("NOTION_GET_PAGE", {"page_id": page_id})

    def create_database(self, parent_page_id: str, title: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        return self.execute("NOTION_CREATE_DATABASE", {"parent_page_id": parent_page_id, "title": title, "properties": properties})

    def append_block(self, block_id: str, children: List[Dict[str, Any]]) -> Dict[str, Any]:
        return self.execute("NOTION_APPEND_BLOCK", {"block_id": block_id, "children": children})

    def search(self, query: str, filter_type: str = None) -> Dict[str, Any]:
        params = {"query": query}
        if filter_type:
            params["filter"] = {"value": filter_type, "property": "object"}
        return self.execute("NOTION_SEARCH", params)

    def sync_with_taskboard(self, taskboard_path: str, database_id: str) -> Dict[str, Any]:
        """Sync local taskboard with Notion database."""
        try:
            with open(taskboard_path) as f:
                tasks = json.load(f)
            synced = 0
            for task in tasks.get("tasks", []):
                self.create_page(database_id, task.get("title", "Untitled"), {
                    "Status": {"select": {"name": task.get("status", "open")}},
                    "Priority": {"number": task.get("priority", 3)}
                })
                synced += 1
            return {"success": True, "synced": synced}
        except Exception as e:
            return {"success": False, "error": str(e)}


TOOL_DEFINITIONS = [
    {"name": "notion_create_page", "description": "Create a new Notion page", "parameters": {"type": "object", "properties": {"parent_database_id": {"type": "string"}, "title": {"type": "string"}}, "required": ["parent_database_id", "title"]}, "handler": "create_page"},
    {"name": "notion_query_database", "description": "Query a Notion database", "parameters": {"type": "object", "properties": {"database_id": {"type": "string"}, "page_size": {"type": "integer"}}, "required": ["database_id"]}, "handler": "query_database"},
    {"name": "notion_update_page", "description": "Update a Notion page", "parameters": {"type": "object", "properties": {"page_id": {"type": "string"}, "properties": {"type": "object"}}, "required": ["page_id", "properties"]}, "handler": "update_page"},
    {"name": "notion_search", "description": "Search Notion workspace", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}, "handler": "search"},
]


def get_tool_for_agent():
    tool = NotionTool()
    tool.initialize()
    return tool


if __name__ == "__main__":
    tool = NotionTool()
    if tool.initialize():
        print("[+] Notion tool initialized")
        tools = tool.get_tools()
        print(f"[+] {len(tools)} Notion tools available")
    else:
        print("[-] Failed to initialize Notion tool")
