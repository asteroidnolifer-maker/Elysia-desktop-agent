#!/usr/bin/env python3
"""
Composio Slack Integration for Elysia
Tool calling interface for Slack operations via Composio.
"""
import os
import json
from typing import Optional, Dict, Any, List
from pathlib import Path

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "ak_46fOkxnX44Dl2ktKdyu5")


class SlackTool:
    """Slack tool using Composio for AI agent tool calling."""

    def __init__(self):
        self.toolset = None
        self._initialized = False

    def initialize(self):
        """Initialize Composio toolset with Slack."""
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
        """Get available Slack tools."""
        if not self._initialized:
            self.initialize()
        try:
            tools = self.toolset.get_tools(app=["slack"])
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
                for tool in tools
            ]
        except Exception as e:
            print(f"[-] Error getting tools: {e}")
            return []

    def execute(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a Slack tool via Composio."""
        if not self._initialized:
            self.initialize()
        try:
            result = self.toolset.execute_tool(
                tool=tool_name,
                params=params
            )
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def send_message(self, channel: str, text: str) -> Dict[str, Any]:
        """Send a message to a Slack channel."""
        return self.execute("SLACK_SEND_MESSAGE", {
            "channel": channel,
            "text": text
        })

    def list_channels(self) -> Dict[str, Any]:
        """List Slack channels."""
        return self.execute("SLACK_LIST_CHANNELS", {})

    def get_channel_history(self, channel: str, limit: int = 10) -> Dict[str, Any]:
        """Get message history from a channel."""
        return self.execute("SLACK_GET_CHANNEL_HISTORY", {
            "channel": channel,
            "limit": limit
        })

    def upload_file(self, channel: str, file_path: str,
                    title: str = "") -> Dict[str, Any]:
        """Upload a file to Slack."""
        return self.execute("SLACK_UPLOAD_FILE", {
            "channel": channel,
            "file": file_path,
            "title": title
        })

    def create_channel(self, name: str, is_private: bool = False) -> Dict[str, Any]:
        """Create a new Slack channel."""
        return self.execute("SLACK_CREATE_CHANNEL", {
            "name": name,
            "is_private": is_private
        })

    def get_user_info(self, user_id: str) -> Dict[str, Any]:
        """Get Slack user information."""
        return self.execute("SLACK_GET_USER_INFO", {
            "user": user_id
        })


# Tool definitions for Elysia agent system
TOOL_DEFINITIONS = [
    {
        "name": "slack_send_message",
        "description": "Send a message to a Slack channel",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name or ID"},
                "text": {"type": "string", "description": "Message text"}
            },
            "required": ["channel", "text"]
        },
        "handler": "send_message"
    },
    {
        "name": "slack_list_channels",
        "description": "List available Slack channels",
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "handler": "list_channels"
    },
    {
        "name": "slack_get_history",
        "description": "Get message history from a Slack channel",
        "parameters": {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "Channel name or ID"},
                "limit": {"type": "integer", "description": "Number of messages"}
            },
            "required": ["channel"]
        },
        "handler": "get_channel_history"
    },
    {
        "name": "slack_create_channel",
        "description": "Create a new Slack channel",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Channel name"},
                "is_private": {"type": "boolean", "description": "Private channel?"}
            },
            "required": ["name"]
        },
        "handler": "create_channel"
    }
]


def get_tool_for_agent():
    """Get Slack tool instance for Elysia agent."""
    tool = SlackTool()
    tool.initialize()
    return tool


if __name__ == "__main__":
    # Test the tool
    tool = SlackTool()
    if tool.initialize():
        print("[+] Slack tool initialized")
        tools = tool.get_tools()
        print(f"[+] {len(tools)} Slack tools available:")
        for t in tools:
            print(f"    - {t['name']}: {t['description'][:50]}...")
    else:
        print("[-] Failed to initialize Slack tool")
