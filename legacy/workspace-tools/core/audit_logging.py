#!/usr/bin/env python3
"""
Elysia Audit Logging - Task 1254
Immutable audit trail for security, compliance, and debugging.
"""
import json
import hashlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class AuditLogger:
    def __init__(self, log_dir: str = None):
        self.log_dir = Path(log_dir or Path(__file__).parent / ".data" / "audit")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.chain: List[Dict[str, Any]] = []

    def log(self, action: str, actor: str, resource: str = "",
            details: Dict[str, Any] = None, outcome: str = "success") -> Dict[str, Any]:
        prev_hash = self.chain[-1]["hash"] if self.chain else "0" * 64
        entry = {
            "id": len(self.chain) + 1,
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "actor": actor,
            "resource": resource,
            "details": details or {},
            "outcome": outcome,
            "prev_hash": prev_hash
        }
        entry_str = json.dumps(entry, sort_keys=True)
        entry["hash"] = hashlib.sha256(entry_str.encode()).hexdigest()
        self.chain.append(entry)

        log_file = self.log_dir / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return entry

    def query(self, actor: str = None, action: str = None,
              since: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        results = self.chain
        if actor:
            results = [e for e in results if e["actor"] == actor]
        if action:
            results = [e for e in results if e["action"] == action]
        if since:
            results = [e for e in results if e["timestamp"] >= since]
        return results[-limit:]

    def verify_chain(self) -> bool:
        for i in range(1, len(self.chain)):
            if self.chain[i]["prev_hash"] != self.chain[i-1]["hash"]:
                return False
        return True

    def get_actor_summary(self) -> Dict[str, int]:
        summary: Dict[str, int] = {}
        for entry in self.chain:
            actor = entry["actor"]
            summary[actor] = summary.get(actor, 0) + 1
        return summary

    def export(self, format: str = "json") -> str:
        if format == "json":
            return json.dumps(self.chain, indent=2)
        elif format == "csv":
            lines = ["timestamp,action,actor,resource,outcome"]
            for e in self.chain:
                lines.append(f"{e['timestamp']},{e['action']},{e['actor']},{e['resource']},{e['outcome']}")
            return "\n".join(lines)
        return ""


def main():
    logger = AuditLogger()
    if len(sys.argv) < 2:
        print("Elysia Audit Logger")
        print("Commands: log <action> <actor> [resource], query [actor] [action], verify, summary")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "log" and len(sys.argv) >= 4:
        resource = sys.argv[4] if len(sys.argv) > 4 else ""
        entry = logger.log(sys.argv[2], sys.argv[3], resource)
        print(f"[+] Audit entry #{entry['id']}: {entry['hash'][:16]}...")
    elif cmd == "query":
        actor = sys.argv[2] if len(sys.argv) > 2 else None
        action = sys.argv[3] if len(sys.argv) > 3 else None
        results = logger.query(actor=actor, action=action)
        for r in results:
            print(f"  #{r['id']} [{r['action']}] by {r['actor']} - {r['outcome']}")
    elif cmd == "verify":
        valid = logger.verify_chain()
        print(f"Chain integrity: {'VALID' if valid else 'BROKEN'}")
    elif cmd == "summary":
        print(json.dumps(logger.get_actor_summary(), indent=2))


if __name__ == "__main__":
    main()
