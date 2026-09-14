#!/usr/bin/env python3
"""
Expense Tracker for Elysia Finance
Track daily expenses, categorize, and analyze spending.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime, timedelta


class ExpenseTracker:
    """Track and categorize daily expenses."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "expenses.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"expenses": [], "categories": {}, "monthly_budgets": {}}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_expense(self, amount: float, category: str, description: str,
                    date: str = None) -> Dict[str, Any]:
        expense = {
            "id": f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "amount": amount, "category": category, "description": description,
            "date": date or datetime.now().isoformat()[:10]
        }
        self.data["expenses"].append(expense)
        if category not in self.data["categories"]:
            self.data["categories"][category] = {"total": 0, "count": 0}
        self.data["categories"][category]["total"] += amount
        self.data["categories"][category]["count"] += 1
        self._save_data()
        return expense

    def get_expenses(self, category: str = None, days: int = 30) -> List[Dict[str, Any]]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()[:10]
        expenses = [e for e in self.data["expenses"] if e.get("date", "") >= cutoff]
        if category:
            expenses = [e for e in expenses if e.get("category") == category]
        return expenses

    def get_monthly_total(self, month: int = None, year: int = None) -> float:
        now = datetime.now()
        month = month or now.month
        year = year or now.year
        return sum(
            e["amount"] for e in self.data["expenses"]
            if e.get("date", "").startswith(f"{year}-{month:02d}")
        )

    def get_category_totals(self) -> Dict[str, Dict[str, float]]:
        totals = {}
        for e in self.data["expenses"]:
            cat = e.get("category", "other")
            if cat not in totals:
                totals[cat] = {"amount": 0, "count": 0}
            totals[cat]["amount"] += e.get("amount", 0)
            totals[cat]["count"] += 1
        return totals

    def get_daily_spending(self, days: int = 30) -> List[Dict[str, Any]]:
        daily = {}
        for e in self.data["expenses"]:
            day = e.get("date", "")[:10]
            daily[day] = daily.get(day, 0) + e.get("amount", 0)
        return [{"date": d, "amount": a} for d, a in sorted(daily.items())]

    def set_budget(self, category: str, monthly_limit: float):
        self.data["monthly_budgets"][category] = monthly_limit
        self._save_data()

    def check_budget(self) -> Dict[str, Any]:
        status = {}
        for cat, limit in self.data.get("monthly_budgets", {}).items():
            monthly = sum(
                e["amount"] for e in self.data["expenses"]
                if e.get("category") == cat and e.get("date", "").startswith(datetime.now().strftime("%Y-%m"))
            )
            status[cat] = {
                "budget": limit, "spent": monthly,
                "remaining": limit - monthly,
                "pct_used": monthly / limit * 100 if limit > 0 else 0
            }
        return status

    def get_summary(self) -> Dict[str, Any]:
        total = sum(e.get("amount", 0) for e in self.data["expenses"])
        monthly = self.get_monthly_total()
        return {
            "total_spent": total, "monthly_total": monthly,
            "expense_count": len(self.data["expenses"]),
            "avg_per_expense": total / len(self.data["expenses"]) if self.data["expenses"] else 0
        }


class ReceiptScanner:
    """Scan and categorize receipts (simulated)."""

    COMMON_ITEMS = {
        "coffee": "food", "lunch": "food", "dinner": "food",
        "uber": "transport", "gas": "transport", "parking": "transport",
        "netflix": "entertainment", "spotify": "entertainment",
        "rent": "housing", "electric": "utilities", "internet": "utilities"
    }

    @classmethod
    def auto_categorize(cls, description: str) -> str:
        desc_lower = description.lower()
        for keyword, category in cls.COMMON_ITEMS.items():
            if keyword in desc_lower:
                return category
        return "other"


def main():
    import sys
    tracker = ExpenseTracker()

    if len(sys.argv) < 2:
        print("Expense Tracker")
        print("=" * 40)
        print("\nCommands:")
        print("  add <amount> <category> <description>")
        print("  total [days]              - Total expenses")
        print("  monthly                   - Monthly total")
        print("  categories                - Category totals")
        print("  daily [days]              - Daily spending")
        print("  budget <category> <limit> - Set budget")
        print("  check-budget              - Check budgets")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add" and len(sys.argv) >= 5:
        cat = ReceiptScanner.auto_categorize(sys.argv[4]) if sys.argv[3] == "auto" else sys.argv[3]
        tracker.add_expense(float(sys.argv[2]), cat, sys.argv[4])
        print("Expense added")

    elif cmd == "total":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        expenses = tracker.get_expenses(days=days)
        total = sum(e["amount"] for e in expenses)
        print(f"Total ({days}d): ${total:,.2f}")

    elif cmd == "monthly":
        print(f"This month: ${tracker.get_monthly_total():,.2f}")

    elif cmd == "categories":
        for cat, data in tracker.get_category_totals().items():
            print(f"  {cat}: ${data['amount']:,.2f} ({data['count']} transactions)")

    elif cmd == "daily":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        for d in tracker.get_daily_spending(days):
            print(f"  {d['date']}: ${d['amount']:,.2f}")

    elif cmd == "budget" and len(sys.argv) >= 4:
        tracker.set_budget(sys.argv[2], float(sys.argv[3]))
        print(f"Budget set for {sys.argv[2]}")

    elif cmd == "check-budget":
        for cat, status in tracker.check_budget().items():
            emoji = "✓" if status["remaining"] >= 0 else "✗"
            print(f"  {emoji} {cat}: ${status['spent']:.0f}/${status['budget']:.0f} ({status['pct_used']:.0f}%)")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
