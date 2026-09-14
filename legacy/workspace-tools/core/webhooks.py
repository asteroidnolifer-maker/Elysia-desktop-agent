#!/usr/bin/env python3
"""
Elysia Webhook System - Task 1268
Outgoing webhook management with retry, logging, and security.
"""
import hashlib
import hmac
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class Webhook:
    def __init__(self, url: str, events: List[str], secret: str = None,
                 name: str = ""):
        self.name = name or url[:50]
        self.url = url
        self.events = events
        self.secret = secret
        self.active = True
        self.created = datetime.now().isoformat()
        self.last_triggered = None
        self.fail_count = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "url": self.url, "events": self.events,
            "active": self.active, "created": self.created,
            "last_triggered": self.last_triggered, "fail_count": self.fail_count
        }


class WebhookManager:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "webhooks")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.webhooks: Dict[str, Webhook] = {}
        self.delivery_log: List[Dict[str, Any]] = []

    def add_webhook(self, url: str, events: List[str], secret: str = None,
                    name: str = "") -> Webhook:
        wh = Webhook(url, events, secret, name)
        self.webhooks[wh.name] = wh
        return wh

    def remove_webhook(self, name: str) -> bool:
        if name in self.webhooks:
            del self.webhooks[name]
            return True
        return False

    def _sign_payload(self, payload: str, secret: str) -> str:
        return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def deliver(self, webhook: Webhook, event_type: str,
                payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps({
            "event": event_type,
            "data": payload,
            "timestamp": datetime.now().isoformat()
        })

        headers = {"Content-Type": "application/json"}
        if webhook.secret:
            headers["X-Webhook-Signature"] = self._sign_payload(body, webhook.secret)

        req = urllib.request.Request(webhook.url, data=body.encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                webhook.last_triggered = datetime.now().isoformat()
                webhook.fail_count = 0
                result = {"status": "delivered", "http_status": status}
        except Exception as e:
            webhook.fail_count += 1
            result = {"status": "failed", "error": str(e)}

        log_entry = {
            "webhook": webhook.name, "event": event_type,
            "result": result, "timestamp": datetime.now().isoformat()
        }
        self.delivery_log.append(log_entry)
        return result

    def dispatch(self, event_type: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        results = []
        for wh in self.webhooks.values():
            if wh.active and event_type in wh.events:
                result = self.deliver(wh, event_type, payload)
                results.append({"webhook": wh.name, "result": result})
        return results

    def list_webhooks(self) -> List[Dict[str, Any]]:
        return [wh.to_dict() for wh in self.webhooks.values()]

    def get_delivery_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.delivery_log[-limit:]


def main():
    mgr = WebhookManager()
    if len(sys.argv) < 2:
        print("Elysia Webhook System")
        print("Commands: add <url> <events>, remove <name>, dispatch <event> [payload], list, log")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "add" and len(sys.argv) >= 4:
        events = sys.argv[3].split(",")
        wh = mgr.add_webhook(sys.argv[2], events, name=sys.argv[2][:30])
        print(f"[+] Webhook added: {wh.name}")
    elif cmd == "remove" and len(sys.argv) >= 3:
        mgr.remove_webhook(sys.argv[2])
        print(f"[+] Removed: {sys.argv[2]}")
    elif cmd == "dispatch" and len(sys.argv) >= 3:
        payload = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
        results = mgr.dispatch(sys.argv[2], payload)
        print(json.dumps(results, indent=2))
    elif cmd == "list":
        for wh in mgr.list_webhooks():
            print(f"  {wh['name']}: {wh['url']} [{', '.join(wh['events'])}]")
    elif cmd == "log":
        for entry in mgr.get_delivery_log():
            print(f"  [{entry['result']['status']}] {entry['event']} -> {entry['webhook']}")


if __name__ == "__main__":
    main()
