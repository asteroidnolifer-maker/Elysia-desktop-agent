#!/usr/bin/env python3
"""
Composio Twitter/X Integration for Elysia
Tool calling interface for Twitter operations via Composio.
"""
import os
import json
from typing import Optional, Dict, Any, List

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "ak_46fOkxnX44Dl2ktKdyu5")


class TwitterTool:
    """Twitter/X tool using Composio for AI agent tool calling."""

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
            tools = self.toolset.get_tools(app=["twitter"])
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

    def post_tweet(self, text: str, reply_to: str = None) -> Dict[str, Any]:
        params = {"text": text}
        if reply_to:
            params["reply_to"] = reply_to
        return self.execute("TWITTER_CREATE_TWEET", params)

    def delete_tweet(self, tweet_id: str) -> Dict[str, Any]:
        return self.execute("TWITTER_DELETE_TWEET", {"tweet_id": tweet_id})

    def get_timeline(self, count: int = 20) -> Dict[str, Any]:
        return self.execute("TWITTER_GET_TIMELINE", {"count": count})

    def get_user_tweets(self, username: str, count: int = 20) -> Dict[str, Any]:
        return self.execute("TWITTER_GET_USER_TWEETS", {"username": username, "count": count})

    def search_tweets(self, query: str, count: int = 20) -> Dict[str, Any]:
        return self.execute("TWITTER_SEARCH_TWEETS", {"query": query, "count": count})

    def like_tweet(self, tweet_id: str) -> Dict[str, Any]:
        return self.execute("TWITTER_LIKE_TWEET", {"tweet_id": tweet_id})

    def retweet(self, tweet_id: str) -> Dict[str, Any]:
        return self.execute("TWITTER_RETWEET", {"tweet_id": tweet_id})

    def send_dm(self, recipient_id: str, text: str) -> Dict[str, Any]:
        return self.execute("TWITTER_SEND_DIRECT_MESSAGE", {"recipient_id": recipient_id, "text": text})

    def get_dm_messages(self, conversation_id: str) -> Dict[str, Any]:
        return self.execute("TWITTER_GET_DM_MESSAGES", {"conversation_id": conversation_id})

    def get_analytics(self) -> Dict[str, Any]:
        return self.execute("TWITTER_GET_ANALYTICS", {})

    def follow_user(self, username: str) -> Dict[str, Any]:
        return self.execute("TWITTER_FOLLOW_USER", {"username": username})

    def unfollow_user(self, username: str) -> Dict[str, Any]:
        return self.execute("TWITTER_UNFOLLOW_USER", {"username": username})

    def get_user_info(self, username: str) -> Dict[str, Any]:
        return self.execute("TWITTER_GET_USER_INFO", {"username": username})


TOOL_DEFINITIONS = [
    {"name": "twitter_post_tweet", "description": "Post a tweet", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, "handler": "post_tweet"},
    {"name": "twitter_search", "description": "Search tweets", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "count": {"type": "integer"}}, "required": ["query"]}, "handler": "search_tweets"},
    {"name": "twitter_get_timeline", "description": "Get home timeline", "parameters": {"type": "object", "properties": {"count": {"type": "integer"}}, "required": []}, "handler": "get_timeline"},
    {"name": "twitter_send_dm", "description": "Send a direct message", "parameters": {"type": "object", "properties": {"recipient_id": {"type": "string"}, "text": {"type": "string"}}, "required": ["recipient_id", "text"]}, "handler": "send_dm"},
]


def get_tool_for_agent():
    tool = TwitterTool()
    tool.initialize()
    return tool


if __name__ == "__main__":
    tool = TwitterTool()
    if tool.initialize():
        print("[+] Twitter tool initialized")
        tools = tool.get_tools()
        print(f"[+] {len(tools)} Twitter tools available")
    else:
        print("[-] Failed to initialize Twitter tool")
