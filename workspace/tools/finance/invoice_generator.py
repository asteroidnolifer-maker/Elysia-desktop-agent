#!/usr/bin/env python3
"""
Invoice Generator for Elysia Financial Tools
PDF invoice generation for freelancers.
"""
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path


class InvoiceGenerator:
    """Generate professional invoices."""

    def __init__(self, business_info: Dict[str, str] = None):
        self.business_info = business_info or {
            "name": "Elysia Services",
            "address": "123 Tech Street",
            "city": "San Francisco, CA 94102",
            "email": "billing@elysia.ai",
            "phone": "+1 (555) 123-4567"
        }
        self.invoice_dir = Path(__file__).parent / "invoices"
        self.invoice_dir.mkdir(exist_ok=True)

    def create_invoice(self, client_info: Dict[str, str],
                       items: List[Dict[str, Any]],
                       tax_rate: float = 0.08,
                       notes: str = "") -> Dict[str, Any]:
        """Create a new invoice."""
        invoice_id = f"INV-{datetime.now().strftime('%Y%m%d')}-{len(list(self.invoice_dir.glob('*.json'))) + 1:04d}"

        subtotal = sum(item["quantity"] * item["rate"] for item in items)
        tax_amount = subtotal * tax_rate
        total = subtotal + tax_amount

        invoice = {
            "invoice_id": invoice_id,
            "date": datetime.now().isoformat(),
            "due_date": (datetime.now() + __import__('datetime').timedelta(days=30)).isoformat(),
            "business": self.business_info,
            "client": client_info,
            "items": [],
            "subtotal": subtotal,
            "tax_rate": tax_rate,
            "tax_amount": tax_amount,
            "total": total,
            "notes": notes,
            "status": "draft"
        }

        for item in items:
            line_total = item["quantity"] * item["rate"]
            invoice["items"].append({
                "description": item["description"],
                "quantity": item["quantity"],
                "rate": item["rate"],
                "total": line_total
            })

        # Save invoice
        invoice_path = self.invoice_dir / f"{invoice_id}.json"
        invoice_path.write_text(json.dumps(invoice, indent=2))

        print(f"[+] Invoice created: {invoice_id}")
        print(f"    Total: ${total:,.2f}")
        return invoice

    def generate_html(self, invoice: Dict[str, Any]) -> str:
        """Generate HTML version of invoice."""
        items_html = ""
        for item in invoice["items"]:
            items_html += f"""
            <tr>
                <td>{item['description']}</td>
                <td>{item['quantity']}</td>
                <td>${item['rate']:,.2f}</td>
                <td>${item['total']:,.2f}</td>
            </tr>"""

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Invoice {invoice['invoice_id']}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .header {{ display: flex; justify-content: space-between; margin-bottom: 30px; }}
        .business {{ font-size: 24px; font-weight: bold; color: #333; }}
        .invoice-id {{ font-size: 20px; color: #666; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #f5f5f5; }}
        .total {{ font-size: 18px; font-weight: bold; text-align: right; margin-top: 20px; }}
        .notes {{ margin-top: 30px; padding: 15px; background-color: #f9f9f9; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="business">{invoice['business']['name']}</div>
        <div class="invoice-id">{invoice['invoice_id']}</div>
    </div>

    <div style="margin-bottom: 30px;">
        <strong>Bill To:</strong><br>
        {invoice['client']['name']}<br>
        {invoice['client'].get('address', '')}<br>
        {invoice['client'].get('email', '')}
    </div>

    <div style="margin-bottom: 20px;">
        <strong>Date:</strong> {invoice['date'][:10]}<br>
        <strong>Due Date:</strong> {invoice['due_date'][:10]}
    </div>

    <table>
        <thead>
            <tr>
                <th>Description</th>
                <th>Quantity</th>
                <th>Rate</th>
                <th>Total</th>
            </tr>
        </thead>
        <tbody>
            {items_html}
        </tbody>
    </table>

    <div class="total">
        Subtotal: ${invoice['subtotal']:,.2f}<br>
        Tax ({invoice['tax_rate']*100:.1f}%): ${invoice['tax_amount']:,.2f}<br>
        <strong>Total: ${invoice['total']:,.2f}</strong>
    </div>

    {f'<div class="notes"><strong>Notes:</strong> {invoice["notes"]}</div>' if invoice.get('notes') else ''}

    <div style="margin-top: 40px; text-align: center; color: #666;">
        Thank you for your business!
    </div>
</body>
</html>"""
        return html

    def save_html(self, invoice: Dict[str, Any]) -> str:
        """Save invoice as HTML file."""
        html = self.generate_html(invoice)
        html_path = self.invoice_dir / f"{invoice['invoice_id']}.html"
        html_path.write_text(html)
        print(f"[+] HTML invoice saved: {html_path}")
        return str(html_path)

    def list_invoices(self) -> List[Dict[str, Any]]:
        """List all invoices."""
        invoices = []
        for path in self.invoice_dir.glob("*.json"):
            invoice = json.loads(path.read_text())
            invoices.append({
                "id": invoice["invoice_id"],
                "client": invoice["client"]["name"],
                "total": invoice["total"],
                "status": invoice["status"],
                "date": invoice["date"][:10]
            })
        return sorted(invoices, key=lambda x: x["date"], reverse=True)

    def mark_paid(self, invoice_id: str) -> bool:
        """Mark invoice as paid."""
        invoice_path = self.invoice_dir / f"{invoice_id}.json"
        if invoice_path.exists():
            invoice = json.loads(invoice_path.read_text())
            invoice["status"] = "paid"
            invoice["paid_date"] = datetime.now().isoformat()
            invoice_path.write_text(json.dumps(invoice, indent=2))
            print(f"[+] Invoice {invoice_id} marked as paid")
            return True
        return False


def main():
    """CLI entry point."""
    generator = InvoiceGenerator()

    if len(sys.argv) < 2:
        print("Invoice Generator")
        print("=" * 40)
        print("\nCommands:")
        print("  list              - List all invoices")
        print("  create            - Create new invoice")
        print("  html <invoice_id> - Generate HTML")
        print("  paid <invoice_id> - Mark as paid")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "list":
        invoices = generator.list_invoices()
        print(f"\nInvoices ({len(invoices)}):")
        for inv in invoices:
            print(f"  {inv['id']} - {inv['client']} - ${inv['total']:,.2f} [{inv['status']}]")

    elif cmd == "create":
        # Sample invoice creation
        client = {
            "name": "Acme Corporation",
            "address": "456 Business Ave",
            "email": "accounts@acme.com"
        }
        items = [
            {"description": "Web Development", "quantity": 40, "rate": 150},
            {"description": "UI/UX Design", "quantity": 20, "rate": 125}
        ]
        generator.create_invoice(client, items, notes="Net 30 terms")

    elif cmd == "html" and len(sys.argv) >= 3:
        invoice_path = generator.invoice_dir / f"{sys.argv[2]}.json"
        if invoice_path.exists():
            invoice = json.loads(invoice_path.read_text())
            generator.save_html(invoice)
        else:
            print(f"[-] Invoice not found: {sys.argv[2]}")

    elif cmd == "paid" and len(sys.argv) >= 3:
        generator.mark_paid(sys.argv[2])

    else:
        print("Unknown command. Run without args for help.")


if __name__ == "__main__":
    main()
