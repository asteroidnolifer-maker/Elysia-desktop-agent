#!/usr/bin/env python3
"""
Elysia Role-Based Access Control - Tasks 1251-1253
Multi-user support with roles, permissions, and access control.
"""
import hashlib
import json
import secrets
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class RBAC:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "rbac")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.users: Dict[str, Dict[str, Any]] = {}
        self.roles: Dict[str, Dict[str, Any]] = {
            "admin": {"permissions": ["*"], "description": "Full access"},
            "editor": {"permissions": ["read", "write", "edit"], "description": "Can edit content"},
            "viewer": {"permissions": ["read"], "description": "Read-only access"},
            "worker": {"permissions": ["read", "claim", "complete"], "description": "Task worker"}
        }
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def create_user(self, username: str, password: str,
                    role: str = "viewer") -> Dict[str, Any]:
        salt = secrets.token_hex(16)
        pw_hash = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        user = {
            "username": username,
            "password_hash": pw_hash,
            "salt": salt,
            "role": role,
            "created": datetime.now().isoformat(),
            "active": True
        }
        self.users[username] = user
        return {"username": username, "role": role, "created": user["created"]}

    def authenticate(self, username: str, password: str) -> Optional[str]:
        user = self.users.get(username)
        if not user or not user.get("active"):
            return None
        pw_hash = hashlib.sha256(f"{user['salt']}:{password}".encode()).hexdigest()
        if pw_hash != user["password_hash"]:
            return None
        token = secrets.token_hex(32)
        self.sessions[token] = {
            "username": username,
            "role": user["role"],
            "created": datetime.now().isoformat()
        }
        return token

    def check_permission(self, token: str, permission: str) -> bool:
        session = self.sessions.get(token)
        if not session:
            return False
        role = session["role"]
        role_perms = self.roles.get(role, {}).get("permissions", [])
        return "*" in role_perms or permission in role_perms

    def authorize(self, token: str, permission: str,
                  resource: str = "") -> Dict[str, Any]:
        allowed = self.check_permission(token, permission)
        return {
            "allowed": allowed,
            "permission": permission,
            "resource": resource,
            "timestamp": datetime.now().isoformat()
        }

    def add_role(self, name: str, permissions: List[str], description: str = ""):
        self.roles[name] = {"permissions": permissions, "description": description}

    def assign_role(self, username: str, role: str) -> bool:
        if username in self.users and role in self.roles:
            self.users[username]["role"] = role
            return True
        return False

    def list_users(self) -> List[Dict[str, Any]]:
        return [{"username": u["username"], "role": u["role"],
                "active": u["active"]} for u in self.users.values()]

    def list_roles(self) -> Dict[str, Any]:
        return self.roles

    def logout(self, token: str):
        self.sessions.pop(token, None)


def main():
    rbac = RBAC()
    if len(sys.argv) < 2:
        print("Elysia RBAC")
        print("Commands: create-user <user> <pass> <role>, login <user> <pass>, "
              "check <token> <perm>, roles, users")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "create-user" and len(sys.argv) >= 5:
        result = rbac.create_user(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"[+] User created: {result}")
    elif cmd == "login" and len(sys.argv) >= 4:
        token = rbac.authenticate(sys.argv[2], sys.argv[3])
        if token:
            print(f"[+] Token: {token[:16]}...")
        else:
            print("[-] Authentication failed")
    elif cmd == "check" and len(sys.argv) >= 4:
        allowed = rbac.check_permission(sys.argv[2], sys.argv[3])
        print(f"Permission: {'granted' if allowed else 'denied'}")
    elif cmd == "roles":
        for name, role in rbac.list_roles().items():
            print(f"  {name}: {', '.join(role['permissions'])} - {role['description']}")
    elif cmd == "users":
        for u in rbac.list_users():
            print(f"  {u['username']}: {u['role']} [{'active' if u['active'] else 'inactive'}]")


if __name__ == "__main__":
    main()
