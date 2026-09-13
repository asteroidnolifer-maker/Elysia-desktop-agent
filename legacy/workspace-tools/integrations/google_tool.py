#!/usr/bin/env python3
"""
Composio Google Workspace Integration for Elysia
Gmail, Calendar, Drive, Sheets integration via Composio.
"""
import os
import json
from typing import Optional, Dict, Any, List
from pathlib import Path

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "ak_46fOkxnX44Dl2ktKdyu5")


class GoogleTool:
    """Google Workspace tool using Composio."""

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
            tools = self.toolset.get_tools(app=["google"])
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

    def gmail_send(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        return self.execute("GMAIL_SEND_EMAIL", {"to": to, "subject": subject, "body": body})

    def gmail_list(self, query: str = "in:inbox", max_results: int = 10) -> Dict[str, Any]:
        return self.execute("GMAIL_LIST_EMAILS", {"query": query, "max_results": max_results})

    def gmail_read(self, message_id: str) -> Dict[str, Any]:
        return self.execute("GMAIL_READ_EMAIL", {"message_id": message_id})

    def gmail_reply(self, message_id: str, body: str) -> Dict[str, Any]:
        return self.execute("GMAIL_REPLY_EMAIL", {"message_id": message_id, "body": body})

    def calendar_list_events(self, calendar_id: str = "primary", max_results: int = 10) -> Dict[str, Any]:
        return self.execute("GOOGLE_CALENDAR_LIST_EVENTS", {"calendar_id": calendar_id, "max_results": max_results})

    def calendar_create_event(self, summary: str, start_time: str, end_time: str, description: str = "") -> Dict[str, Any]:
        return self.execute("GOOGLE_CALENDAR_CREATE_EVENT", {"summary": summary, "start_time": start_time, "end_time": end_time, "description": description})

    def calendar_delete_event(self, event_id: str) -> Dict[str, Any]:
        return self.execute("GOOGLE_CALENDAR_DELETE_EVENT", {"event_id": event_id})

    def drive_list_files(self, query: str = "", max_results: int = 10) -> Dict[str, Any]:
        return self.execute("GOOGLE_DRIVE_LIST_FILES", {"query": query, "max_results": max_results})

    def drive_upload(self, file_path: str, folder_id: str = None) -> Dict[str, Any]:
        params = {"file_path": file_path}
        if folder_id:
            params["folder_id"] = folder_id
        return self.execute("GOOGLE_DRIVE_UPLOAD_FILE", params)

    def drive_download(self, file_id: str, output_path: str) -> Dict[str, Any]:
        return self.execute("GOOGLE_DRIVE_DOWNLOAD_FILE", {"file_id": file_id, "output_path": output_path})

    def sheets_read(self, spreadsheet_id: str, range_str: str = "A1:Z1000") -> Dict[str, Any]:
        return self.execute("GOOGLE_SHEETS_READ", {"spreadsheet_id": spreadsheet_id, "range": range_str})

    def sheets_write(self, spreadsheet_id: str, range_str: str, values: List[List[Any]]) -> Dict[str, Any]:
        return self.execute("GOOGLE_SHEETS_WRITE", {"spreadsheet_id": spreadsheet_id, "range": range_str, "values": values})


TOOL_DEFINITIONS = [
    {"name": "gmail_send", "description": "Send an email via Gmail", "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}, "handler": "gmail_send"},
    {"name": "gmail_list", "description": "List emails from Gmail", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": []}, "handler": "gmail_list"},
    {"name": "calendar_create", "description": "Create a Google Calendar event", "parameters": {"type": "object", "properties": {"summary": {"type": "string"}, "start_time": {"type": "string"}, "end_time": {"type": "string"}}, "required": ["summary", "start_time", "end_time"]}, "handler": "calendar_create_event"},
    {"name": "drive_upload", "description": "Upload a file to Google Drive", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]}, "handler": "drive_upload"},
    {"name": "sheets_read", "description": "Read from Google Sheets", "parameters": {"type": "object", "properties": {"spreadsheet_id": {"type": "string"}, "range": {"type": "string"}}, "required": ["spreadsheet_id"]}, "handler": "sheets_read"},
]


def get_tool_for_agent():
    tool = GoogleTool()
    tool.initialize()
    return tool


if __name__ == "__main__":
    tool = GoogleTool()
    if tool.initialize():
        print("[+] Google tool initialized")
        tools = tool.get_tools()
        print(f"[+] {len(tools)} Google tools available")
    else:
        print("[-] Failed to initialize Google tool")
