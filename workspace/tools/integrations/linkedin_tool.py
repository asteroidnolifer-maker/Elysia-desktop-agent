#!/usr/bin/env python3
"""
Composio LinkedIn Integration for Elysia
Tool calling interface for LinkedIn operations via Composio.
"""
import os
import json
from typing import Optional, Dict, Any, List

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "ak_46fOkxnX44Dl2ktKdyu5")


class LinkedInTool:
    """LinkedIn tool using Composio for AI agent tool calling."""

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
            tools = self.toolset.get_tools(app=["linkedin"])
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

    def post_update(self, text: str) -> Dict[str, Any]:
        return self.execute("LINKEDIN_CREATE_POST", {"text": text})

    def get_profile(self) -> Dict[str, Any]:
        return self.execute("LINKEDIN_GET_PROFILE", {})

    def get_connections(self, start: int = 0, count: int = 25) -> Dict[str, Any]:
        return self.execute("LINKEDIN_GET_CONNECTIONS", {"start": start, "count": count})

    def send_connection_request(self, person_id: str, message: str = "") -> Dict[str, Any]:
        return self.execute("LINKEDIN_SEND_CONNECTION_REQUEST", {"person_id": person_id, "message": message})

    def search_people(self, keywords: str, count: int = 10) -> Dict[str, Any]:
        return self.execute("LINKEDIN_SEARCH_PEOPLE", {"keywords": keywords, "count": count})

    def search_jobs(self, keywords: str, location: str = "", count: int = 10) -> Dict[str, Any]:
        params = {"keywords": keywords, "count": count}
        if location:
            params["location"] = location
        return self.execute("LINKEDIN_SEARCH_JOBS", params)

    def get_job_details(self, job_id: str) -> Dict[str, Any]:
        return self.execute("LINKEDIN_GET_JOB_DETAILS", {"job_id": job_id})

    def like_post(self, post_id: str) -> Dict[str, Any]:
        return self.execute("LINKEDIN_LIKE_POST", {"post_id": post_id})

    def comment_on_post(self, post_id: str, text: str) -> Dict[str, Any]:
        return self.execute("LINKEDIN_COMMENT_POST", {"post_id": post_id, "text": text})

    def get_company_info(self, company_id: str) -> Dict[str, Any]:
        return self.execute("LINKEDIN_GET_COMPANY_INFO", {"company_id": company_id})


TOOL_DEFINITIONS = [
    {"name": "linkedin_post", "description": "Post an update on LinkedIn", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}, "handler": "post_update"},
    {"name": "linkedin_get_profile", "description": "Get LinkedIn profile", "parameters": {"type": "object", "properties": {}}, "handler": "get_profile"},
    {"name": "linkedin_search_jobs", "description": "Search LinkedIn jobs", "parameters": {"type": "object", "properties": {"keywords": {"type": "string"}, "location": {"type": "string"}}, "required": ["keywords"]}, "handler": "search_jobs"},
    {"name": "linkedin_search_people", "description": "Search LinkedIn people", "parameters": {"type": "object", "properties": {"keywords": {"type": "string"}}, "required": ["keywords"]}, "handler": "search_people"},
]


def get_tool_for_agent():
    tool = LinkedInTool()
    tool.initialize()
    return tool


if __name__ == "__main__":
    tool = LinkedInTool()
    if tool.initialize():
        print("[+] LinkedIn tool initialized")
        tools = tool.get_tools()
        print(f"[+] {len(tools)} LinkedIn tools available")
    else:
        print("[-] Failed to initialize LinkedIn tool")
