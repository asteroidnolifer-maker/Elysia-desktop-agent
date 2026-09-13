#!/usr/bin/env python3
"""
Composio GitHub Integration for Elysia
Tool calling interface for GitHub operations via Composio.
"""
import os
import json
from typing import Optional, Dict, Any, List
from pathlib import Path

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "ak_46fOkxnX44Dl2ktKdyu5")


class GitHubTool:
    """GitHub tool using Composio for AI agent tool calling."""

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
            tools = self.toolset.get_tools(app=["github"])
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

    def list_repos(self, owner: Optional[str] = None) -> Dict[str, Any]:
        params = {}
        if owner:
            params["owner"] = owner
        return self.execute("GITHUB_LIST_REPOSITORIES", params)

    def get_repo(self, owner: str, repo: str) -> Dict[str, Any]:
        return self.execute("GITHUB_GET_REPOSITORY", {"owner": owner, "repo": repo})

    def create_issue(self, owner: str, repo: str, title: str, body: str = "") -> Dict[str, Any]:
        return self.execute("GITHUB_CREATE_ISSUE", {"owner": owner, "repo": repo, "title": title, "body": body})

    def create_pull_request(self, owner: str, repo: str, title: str, body: str = "", head: str = "main", base: str = "main") -> Dict[str, Any]:
        return self.execute("GITHUB_CREATE_PULL_REQUEST", {"owner": owner, "repo": repo, "title": title, "body": body, "head": head, "base": base})

    def get_issues(self, owner: str, repo: str, state: str = "open") -> Dict[str, Any]:
        return self.execute("GITHUB_LIST_ISSUES", {"owner": owner, "repo": repo, "state": state})

    def get_pull_requests(self, owner: str, repo: str, state: str = "open") -> Dict[str, Any]:
        return self.execute("GITHUB_LIST_PULL_REQUESTS", {"owner": owner, "repo": repo, "state": state})

    def get_file(self, owner: str, repo: str, path: str) -> Dict[str, Any]:
        return self.execute("GITHUB_GET_FILE_CONTENTS", {"owner": owner, "repo": repo, "path": path})

    def create_release(self, owner: str, repo: str, tag_name: str, name: str, body: str = "") -> Dict[str, Any]:
        return self.execute("GITHUB_CREATE_RELEASE", {"owner": owner, "repo": repo, "tag_name": tag_name, "name": name, "body": body})

    def fork_repo(self, owner: str, repo: str) -> Dict[str, Any]:
        return self.execute("GITHUB_FORK_REPOSITORY", {"owner": owner, "repo": repo})

    def search_repos(self, query: str) -> Dict[str, Any]:
        return self.execute("GITHUB_SEARCH_REPOSITORIES", {"query": query})


TOOL_DEFINITIONS = [
    {"name": "github_list_repos", "description": "List GitHub repositories", "parameters": {"type": "object", "properties": {"owner": {"type": "string"}}, "required": []}, "handler": "list_repos"},
    {"name": "github_create_issue", "description": "Create a GitHub issue", "parameters": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}}, "required": ["owner", "repo", "title"]}, "handler": "create_issue"},
    {"name": "github_create_pr", "description": "Create a pull request", "parameters": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}}, "required": ["owner", "repo", "title"]}, "handler": "create_pull_request"},
    {"name": "github_get_issues", "description": "List issues in a repository", "parameters": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}, "state": {"type": "string"}}, "required": ["owner", "repo"]}, "handler": "get_issues"},
    {"name": "github_get_file", "description": "Get file contents from a repo", "parameters": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}, "path": {"type": "string"}}, "required": ["owner", "repo", "path"]}, "handler": "get_file"},
]


def get_tool_for_agent():
    tool = GitHubTool()
    tool.initialize()
    return tool


if __name__ == "__main__":
    tool = GitHubTool()
    if tool.initialize():
        print("[+] GitHub tool initialized")
        tools = tool.get_tools()
        print(f"[+] {len(tools)} GitHub tools available")
        for t in tools:
            print(f"    - {t['name']}")
    else:
        print("[-] Failed to initialize GitHub tool")
