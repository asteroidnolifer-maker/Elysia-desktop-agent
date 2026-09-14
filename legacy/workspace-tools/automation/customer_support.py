#!/usr/bin/env python3
"""
Elysia Customer Support Automation - Task 1811
Ticket management, auto-routing, response templates, escalation.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum


class TicketPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    URGENT = 4


class TicketStatus(Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Ticket:
    def __init__(self, subject: str, body: str, customer: str,
                 priority: TicketPriority = TicketPriority.MEDIUM):
        self.id = f"TKT-{datetime.now().strftime('%Y%m%d')}-{id(self) % 10000:04d}"
        self.subject = subject
        self.body = body
        self.customer = customer
        self.priority = priority
        self.status = TicketStatus.OPEN
        self.category = self._auto_categorize(subject + " " + body)
        self.assigned_to = None
        self.responses: List[Dict[str, Any]] = []
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at

    def _auto_categorize(self, text: str) -> str:
        categories = {
            "billing": ["invoice", "payment", "charge", "refund", "billing"],
            "technical": ["bug", "error", "crash", "broken", "not working"],
            "account": ["login", "password", "account", "access", "locked"],
            "feature": ["feature", "request", "suggestion", "would be nice"],
        }
        text_lower = text.lower()
        for cat, keywords in categories.items():
            if any(kw in text_lower for kw in keywords):
                return cat
        return "general"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "subject": self.subject, "body": self.body,
            "customer": self.customer, "priority": self.priority.name,
            "status": self.status.value, "category": self.category,
            "assigned_to": self.assigned_to, "responses": self.responses,
            "created_at": self.created_at, "updated_at": self.updated_at
        }


class CustomerSupport:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "support")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tickets: Dict[str, Ticket] = {}
        self.response_templates: Dict[str, str] = {
            "acknowledgment": "Thank you for contacting support. Your ticket {ticket_id} has been created.",
            "escalation": "This ticket has been escalated to our specialist team.",
            "resolved": "Your issue has been resolved. Please let us know if you need further assistance."
        }
        self.routing_rules: Dict[str, str] = {
            "billing": "billing_team",
            "technical": "tech_team",
            "account": "account_team",
            "general": "general_support"
        }

    def create_ticket(self, subject: str, body: str, customer: str,
                      priority: str = "MEDIUM") -> Ticket:
        p = TicketPriority[priority.upper()]
        ticket = Ticket(subject, body, customer, p)
        self.tickets[ticket.id] = ticket
        auto_assign = self.routing_rules.get(ticket.category, "general_support")
        ticket.assigned_to = auto_assign
        return ticket

    def respond(self, ticket_id: str, agent: str, message: str) -> bool:
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            return False
        ticket.responses.append({
            "agent": agent,
            "message": message,
            "timestamp": datetime.now().isoformat()
        })
        ticket.updated_at = datetime.now().isoformat()
        return True

    def escalate(self, ticket_id: str, reason: str = "") -> bool:
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            return False
        ticket.assigned_to = "escalation_team"
        ticket.priority = TicketPriority.URGENT
        ticket.responses.append({
            "agent": "system",
            "message": f"Escalated: {reason}",
            "timestamp": datetime.now().isoformat()
        })
        return True

    def resolve(self, ticket_id: str) -> bool:
        ticket = self.tickets.get(ticket_id)
        if not ticket:
            return False
        ticket.status = TicketStatus.RESOLVED
        ticket.updated_at = datetime.now().isoformat()
        return True

    def get_stats(self) -> Dict[str, Any]:
        by_status = {}
        by_category = {}
        by_priority = {}
        for t in self.tickets.values():
            by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
            by_category[t.category] = by_category.get(t.category, 0) + 1
            by_priority[t.priority.name] = by_priority.get(t.priority.name, 0) + 1
        return {
            "total": len(self.tickets),
            "by_status": by_status,
            "by_category": by_category,
            "by_priority": by_priority
        }

    def get_open_tickets(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self.tickets.values()
                if t.status in (TicketStatus.OPEN, TicketStatus.IN_PROGRESS)]


def main():
    support = CustomerSupport()

    if len(sys.argv) < 2:
        print("Elysia Customer Support")
        print("Commands: create <subject> <body> <customer>, respond <id> <msg>, "
              "escalate <id>, resolve <id>, stats, open")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "create" and len(sys.argv) >= 5:
        ticket = support.create_ticket(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"[+] Ticket {ticket.id} created (category: {ticket.category}, "
              f"assigned: {ticket.assigned_to})")
    elif cmd == "respond" and len(sys.argv) >= 4:
        support.respond(sys.argv[2], "agent", " ".join(sys.argv[3:]))
        print("[+] Response added")
    elif cmd == "escalate" and len(sys.argv) >= 3:
        support.escalate(sys.argv[2])
        print("[+] Escalated")
    elif cmd == "resolve" and len(sys.argv) >= 3:
        support.resolve(sys.argv[2])
        print("[+] Resolved")
    elif cmd == "stats":
        print(json.dumps(support.get_stats(), indent=2))
    elif cmd == "open":
        tickets = support.get_open_tickets()
        for t in tickets:
            print(f"  {t['id']} [{t['priority']}] {t['subject']} -> {t['assigned_to']}")


if __name__ == "__main__":
    main()
