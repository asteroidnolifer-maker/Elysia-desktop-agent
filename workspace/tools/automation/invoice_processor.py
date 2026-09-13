#!/usr/bin/env python3
"""
Elysia Invoice Processing - Task 1819
Invoice generation, tracking, and automated processing.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class Invoice:
    def __init__(self, invoice_id: str, client: str, items: List[Dict[str, Any]],
                 tax_rate: float = 0.0, currency: str = "USD"):
        self.id = invoice_id
        self.client = client
        self.items = items
        self.tax_rate = tax_rate
        self.currency = currency
        self.status = "draft"
        self.created_at = datetime.now().isoformat()
        self.due_date = None
        self.paid_at = None

    def calculate_subtotal(self) -> float:
        return sum(item.get("quantity", 1) * item.get("price", 0) for item in self.items)

    def calculate_tax(self) -> float:
        return self.calculate_subtotal() * self.tax_rate

    def calculate_total(self) -> float:
        return self.calculate_subtotal() + self.calculate_tax()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "client": self.client, "items": self.items,
            "subtotal": self.calculate_subtotal(), "tax": self.calculate_tax(),
            "total": self.calculate_total(), "currency": self.currency,
            "status": self.status, "created_at": self.created_at,
            "due_date": self.due_date, "paid_at": self.paid_at
        }


class InvoiceProcessor:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "invoices")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.invoices: Dict[str, Invoice] = {}
        self.counter = 1000

    def create_invoice(self, client: str, items: List[Dict[str, Any]],
                       tax_rate: float = 0.0) -> Invoice:
        self.counter += 1
        inv = Invoice(f"INV-{self.counter}", client, items, tax_rate)
        self.invoices[inv.id] = inv
        return inv

    def send_invoice(self, invoice_id: str) -> bool:
        inv = self.invoices.get(invoice_id)
        if inv:
            inv.status = "sent"
            return True
        return False

    def mark_paid(self, invoice_id: str) -> bool:
        inv = self.invoices.get(invoice_id)
        if inv:
            inv.status = "paid"
            inv.paid_at = datetime.now().isoformat()
            return True
        return False

    def get_overdue(self) -> List[Dict[str, Any]]:
        now = datetime.now()
        overdue = []
        for inv in self.invoices.values():
            if inv.status == "sent" and inv.due_date:
                if datetime.fromisoformat(inv.due_date) < now:
                    overdue.append(inv.to_dict())
        return overdue

    def get_summary(self) -> Dict[str, Any]:
        total_revenue = sum(inv.calculate_total() for inv in self.invoices.values()
                           if inv.status == "paid")
        pending = sum(inv.calculate_total() for inv in self.invoices.values()
                     if inv.status in ("draft", "sent"))
        return {
            "total_invoices": len(self.invoices),
            "total_revenue": total_revenue,
            "pending_amount": pending,
            "by_status": {
                status: len([i for i in self.invoices.values() if i.status == status])
                for status in ["draft", "sent", "paid"]
            }
        }

    def format_invoice(self, invoice_id: str) -> str:
        inv = self.invoices.get(invoice_id)
        if not inv:
            return "Invoice not found"
        lines = [
            "=" * 50,
            f"INVOICE: {inv.id}",
            f"Client: {inv.client}",
            f"Date: {inv.created_at[:10]}",
            f"Status: {inv.status}",
            "-" * 50,
            f"{'Item':<25} {'Qty':>5} {'Price':>10} {'Total':>10}",
            "-" * 50
        ]
        for item in inv.items:
            qty = item.get("quantity", 1)
            price = item.get("price", 0)
            total = qty * price
            lines.append(f"{item.get('description', 'N/A'):<25} {qty:>5} "
                        f"${price:>9.2f} ${total:>9.2f}")
        lines.extend([
            "-" * 50,
            f"{'Subtotal':>40} ${inv.calculate_subtotal():>9.2f}",
            f"{'Tax':>40} ${inv.calculate_tax():>9.2f}",
            f"{'TOTAL':>40} ${inv.calculate_total():>9.2f}",
            "=" * 50
        ])
        return "\n".join(lines)


def main():
    processor = InvoiceProcessor()

    if len(sys.argv) < 2:
        print("Elysia Invoice Processing")
        print("Commands: create <client> <items_json>, send <id>, paid <id>, summary, format <id>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "create" and len(sys.argv) >= 4:
        items = json.loads(sys.argv[3])
        inv = processor.create_invoice(sys.argv[2], items)
        print(f"[+] Invoice {inv.id} created: ${inv.calculate_total():.2f}")
    elif cmd == "send" and len(sys.argv) >= 3:
        processor.send_invoice(sys.argv[2])
        print(f"[+] Invoice {sys.argv[2]} sent")
    elif cmd == "paid" and len(sys.argv) >= 3:
        processor.mark_paid(sys.argv[2])
        print(f"[+] Invoice {sys.argv[2]} marked paid")
    elif cmd == "summary":
        print(json.dumps(processor.get_summary(), indent=2))
    elif cmd == "format" and len(sys.argv) >= 3:
        print(processor.format_invoice(sys.argv[2]))


if __name__ == "__main__":
    main()
