#!/usr/bin/env python3
"""
Composio Discord Integration for Elysia
Tool calling interface for Discord operations via Composio.
"""
import os
import json
from typing import Optional, Dict, Any, List

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "ak_46fOkxnX44Dl2ktKdyu5")


class DiscordTool:
    """Discord tool using Composio for AI agent tool calling."""

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
            print("[-] composio-core not installed")
            return False
        except Exception as e:
            print(f"[-] Init failed: {e}")
            return False

    def get_tools(self) -> List[Dict[str, Any]]:
        if not self._initialized:
            self.initialize()
        try:
            tools = self.toolset.get_tools(app=["discord"])
            return [{"name": t.name, "description": t.description, "parameters": t.parameters} for t in tools]
        except Exception as e:
            return []

    def execute(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self._initialized:
            self.initialize()
        try:
            result = self.toolset.execute_tool(tool=tool_name, params=params)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def send_message(self, channel_id: str, content: str) -> Dict[str, Any]:
        return self.execute("DISCORD_SEND_MESSAGE", {"channel_id": channel_id, "content": content})

    def list_channels(self, guild_id: str) -> Dict[str, Any]:
        return self.execute("DISCORD_LIST_CHANNELS", {"guild_id": guild_id})

    def list_guilds(self) -> Dict[str, Any]:
        return self.execute("DISCORD_LIST_GUILDS", {})

    def create_channel(self, guild_id: str, name: str, channel_type: int = 0) -> Dict[str, Any]:
        return self.execute("DISCORD_CREATE_CHANNEL", {"guild_id": guild_id, "name": name, "type": channel_type})

    def delete_channel(self, channel_id: str) -> Dict[str, Any]:
        return self.execute("DISCORD_DELETE_CHANNEL", {"channel_id": channel_id})

    def get_channel_messages(self, channel_id: str, limit: int = 50) -> Dict[str, Any]:
        return self.execute("DISCORD_GET_MESSAGES", {"channel_id": channel_id, "limit": limit})

    def create_role(self, guild_id: str, name: str, color: int = 0) -> Dict[str, Any]:
        return self.execute("DISCORD_CREATE_ROLE", {"guild_id": guild_id, "name": name, "color": color})

    def kick_member(self, guild_id: str, user_id: str) -> Dict[str, Any]:
        return self.execute("DISCORD_KICK_MEMBER", {"guild_id": guild_id, "user_id": user_id})

    def ban_member(self, guild_id: str, user_id: str) -> Dict[str, Any]:
        return self.execute("DISCORD_BAN_MEMBER", {"guild_id": guild_id, "user_id": user_id})

    def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> Dict[str, Any]:
        return self.execute("DISCORD_ADD_REACTION", {"channel_id": channel_id, "message_id": message_id, "emoji": emoji})


TOOL_DEFINITIONS = [
    {"name": "discord_send_message", "description": "Send a message to a Discord channel", "parameters": {"type": "object", "properties": {"channel_id": {"type": "string"}, "content": {"type": "string"}}, "required": ["channel_id", "content"]}, "handler": "send_message"},
    {"name": "discord_list_channels", "description": "List channels in a Discord server", "parameters": {"type": "object", "properties": {"guild_id": {"type": "string"}}, "required": ["guild_id"]}, "handler": "list_channels"},
    {"name": "discord_list_guilds", "description": "List Discord servers", "parameters": {"type": "object", "properties": {}}, "handler": "list_guilds"},
    {"name": "discord_create_channel", "description": "Create a Discord channel", "parameters": {"type": "object", "properties": {"guild_id": {"type": "string"}, "name": {"type": "string"}}, "required": ["guild_id", "name"]}, "handler": "create_channel"},
]


def get_tool_for_agent():
    tool = DiscordTool()
    tool.initialize()
    return tool


if __name__ == "__main__":
    tool = DiscordTool()
    if tool.initialize():
        print("[+] Discord tool initialized")
        tools = tool.get_tools()
        print(f"[+] {len(tools)} Discord tools available")
    else:
        print("[-] Failed to initialize Discord tool")
