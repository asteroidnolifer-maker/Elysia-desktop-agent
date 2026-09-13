#!/usr/bin/env python3
"""
Elysia Email Automation - Task 1806
Email templates, scheduling, tracking, and automated workflows.
"""
import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional


class EmailTemplate:
    def __init__(self, name: str, subject: str, body: str,
                 html: bool = False):
        self.name = name
        self.subject = subject
        self.body = body
        self.html = html

    def render(self, variables: Dict[str, str]) -> Dict[str, str]:
        subject = self.subject
        body = self.body
        for key, val in variables.items():
            subject = subject.replace(f"{{{{{key}}}}}", val)
            body = body.replace(f"{{{{{key}}}}}", val)
        return {"subject": subject, "body": body}


class EmailAutomation:
    def __init__(self, config_path: str = None):
        self.config_path = Path(config_path or Path(__file__).parent / ".data" / "email_config.json")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.templates: Dict[str, EmailTemplate] = {}
        self.queue: List[Dict[str, Any]] = []
        self.sent_log: List[Dict[str, Any]] = []
        self._load_config()

    def _load_config(self):
        if self.config_path.exists():
            self.config = json.loads(self.config_path.read_text())
        else:
            self.config = {
                "smtp_host": "",
                "smtp_port": 587,
                "username": "",
                "password": "",
                "from_name": "Elysia",
                "from_email": ""
            }
            self.config_path.write_text(json.dumps(self.config, indent=2))

    def add_template(self, name: str, subject: str, body: str):
        self.templates[name] = EmailTemplate(name, subject, body)

    def queue_email(self, to: str, template: str, variables: Dict[str, str],
                    scheduled_at: str = None):
        tmpl = self.templates.get(template)
        if not tmpl:
            return {"error": f"Template '{template}' not found"}
        rendered = tmpl.render(variables)
        entry = {
            "id": f"email_{len(self.queue) + len(self.sent_log)}",
            "to": to,
            "subject": rendered["subject"],
            "body": rendered["body"],
            "template": template,
            "status": "queued",
            "created": datetime.now().isoformat(),
            "scheduled_at": scheduled_at or datetime.now().isoformat()
        }
        self.queue.append(entry)
        return entry

    def send_email(self, to: str, subject: str, body: str,
                   html: bool = False) -> Dict[str, Any]:
        if not self.config.get("smtp_host"):
            result = {"status": "simulated", "to": to, "subject": subject}
            self.sent_log.append(result)
            return result

        msg = MIMEMultipart("alternative")
        msg["From"] = f"{self.config['from_name']} <{self.config['from_email']}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html" if html else "plain"))

        try:
            with smtplib.SMTP(self.config["smtp_host"], self.config["smtp_port"]) as s:
                s.starttls()
                s.login(self.config["username"], self.config["password"])
                s.send_message(msg)
            result = {"status": "sent", "to": to, "subject": subject,
                      "timestamp": datetime.now().isoformat()}
        except Exception as e:
            result = {"status": "failed", "to": to, "error": str(e)}

        self.sent_log.append(result)
        return result

    def process_queue(self) -> List[Dict[str, Any]]:
        results = []
        now = datetime.now()
        remaining = []
        for entry in self.queue:
            scheduled = datetime.fromisoformat(entry["scheduled_at"])
            if scheduled <= now:
                result = self.send_email(entry["to"], entry["subject"], entry["body"])
                result["id"] = entry["id"]
                entry["status"] = result["status"]
                self.sent_log.append(entry)
                results.append(result)
            else:
                remaining.append(entry)
        self.queue = remaining
        return results

    def get_stats(self) -> Dict[str, Any]:
        return {
            "queued": len(self.queue),
            "sent": len([e for e in self.sent_log if e.get("status") == "sent"]),
            "failed": len([e for e in self.sent_log if e.get("status") == "failed"]),
            "simulated": len([e for e in self.sent_log if e.get("status") == "simulated"])
        }


def main():
    automation = EmailAutomation()

    if len(sys.argv) < 2:
        print("Elysia Email Automation")
        print("Commands: add-template, queue, send <to> <subject> <body>, process, stats")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "add-template" and len(sys.argv) >= 5:
        automation.add_template(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
        print(f"[+] Template '{sys.argv[2]}' added")
    elif cmd == "queue" and len(sys.argv) >= 5:
        result = automation.queue_email(sys.argv[2], sys.argv[3],
                                         {"name": sys.argv[4] if len(sys.argv) > 4 else "User"})
        print(json.dumps(result, indent=2))
    elif cmd == "send" and len(sys.argv) >= 5:
        result = automation.send_email(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
        print(json.dumps(result, indent=2))
    elif cmd == "process":
        results = automation.process_queue()
        print(f"Processed {len(results)} emails")
    elif cmd == "stats":
        print(json.dumps(automation.get_stats(), indent=2))


if __name__ == "__main__":
    main()
