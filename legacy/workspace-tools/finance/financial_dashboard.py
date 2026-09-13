#!/usr/bin/env python3
"""
Financial Dashboard for Elysia
Net worth tracking, budget management, expense categorization.
"""
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass
from enum import Enum


class ExpenseCategory(Enum):
    HOUSING = "housing"
    FOOD = "food"
    TRANSPORT = "transport"
    UTILITIES = "utilities"
    ENTERTAINMENT = "entertainment"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    SAVINGS = "savings"
    OTHER = "other"


@dataclass
class Transaction:
    id: str
    amount: float
    category: str
    description: str
    date: str
    is_income: bool = False


class FinancialDashboard:
    """Financial management dashboard."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "financial_data.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        """Load financial data."""
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {
            "accounts": {
                "checking": {"balance": 5000.00, "name": "Main Checking"},
                "savings": {"balance": 15000.00, "name": "Savings"},
                "investment": {"balance": 25000.00, "name": "Investment Portfolio"}
            },
            "transactions": [],
            "budget": {
                "housing": 1500,
                "food": 600,
                "transport": 300,
                "utilities": 200,
                "entertainment": 200,
                "healthcare": 150,
                "education": 100,
                "other": 200
            },
            "monthly_income": 6000.00,
            "savings_goals": [
                {"name": "Emergency Fund", "target": 20000, "current": 15000},
                {"name": "Vacation", "target": 5000, "current": 2000}
            ]
        }

    def _save_data(self):
        """Save financial data."""
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_transaction(self, amount: float, category: str,
                        description: str, is_income: bool = False) -> Transaction:
        """Add a transaction."""
        transaction = Transaction(
            id=f"txn_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            amount=amount,
            category=category,
            description=description,
            date=datetime.now().isoformat(),
            is_income=is_income
        )

        self.data["transactions"].append({
            "id": transaction.id,
            "amount": transaction.amount,
            "category": transaction.category,
            "description": transaction.description,
            "date": transaction.date,
            "is_income": transaction.is_income
        })

        # Update account balance
        if is_income:
            self.data["accounts"]["checking"]["balance"] += amount
        else:
            self.data["accounts"]["checking"]["balance"] -= amount

        self._save_data()
        print(f"[+] Transaction added: {'Income' if is_income else 'Expense'} ${amount:.2f} - {description}")
        return transaction

    def get_net_worth(self) -> Dict[str, Any]:
        """Calculate total net worth."""
        total_assets = sum(acc["balance"] for acc in self.data["accounts"].values())
        total_goals = sum(goal["current"] for goal in self.data["savings_goals"])

        return {
            "total_assets": total_assets,
            "accounts": self.data["accounts"],
            "savings_progress": total_goals,
            "net_worth": total_assets
        }

    def get_monthly_summary(self, month: Optional[int] = None,
                            year: Optional[int] = None) -> Dict[str, Any]:
        """Get monthly financial summary."""
        now = datetime.now()
        month = month or now.month
        year = year or now.year

        # Filter transactions for the month
        monthly_transactions = [
            t for t in self.data["transactions"]
            if datetime.fromisoformat(t["date"]).month == month
            and datetime.fromisoformat(t["date"]).year == year
        ]

        income = sum(t["amount"] for t in monthly_transactions if t["is_income"])
        expenses = sum(t["amount"] for t in monthly_transactions if not t["is_income"])

        # Category breakdown
        category_totals = {}
        for t in monthly_transactions:
            if not t["is_income"]:
                cat = t["category"]
                category_totals[cat] = category_totals.get(cat, 0) + t["amount"]

        return {
            "month": month,
            "year": year,
            "income": income,
            "expenses": expenses,
            "net": income - expenses,
            "savings_rate": ((income - expenses) / income * 100) if income > 0 else 0,
            "category_breakdown": category_totals,
            "transaction_count": len(monthly_transactions)
        }

    def check_budget(self) -> Dict[str, Any]:
        """Check budget status for current month."""
        summary = self.get_monthly_summary()
        budget_status = {}

        for category, budget_limit in self.data["budget"].items():
            spent = summary["category_breakdown"].get(category, 0)
            remaining = budget_limit - spent
            pct_used = (spent / budget_limit * 100) if budget_limit > 0 else 0

            budget_status[category] = {
                "budget": budget_limit,
                "spent": spent,
                "remaining": remaining,
                "pct_used": pct_used,
                "status": "over" if remaining < 0 else "warning" if pct_used > 80 else "ok"
            }

        return budget_status

    def get_savings_goals_progress(self) -> List[Dict[str, Any]]:
        """Check progress toward savings goals."""
        goals = []
        for goal in self.data["savings_goals"]:
            progress = goal["current"] / goal["target"] * 100
            goals.append({
                "name": goal["name"],
                "target": goal["target"],
                "current": goal["current"],
                "progress_pct": progress,
                "remaining": goal["target"] - goal["current"]
            })
        return goals

    def generate_report(self) -> str:
        """Generate a financial report."""
        net_worth = self.get_net_worth()
        monthly = self.get_monthly_summary()
        budget = self.check_budget()

        report = []
        report.append("=" * 50)
        report.append("  FINANCIAL DASHBOARD REPORT")
        report.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        report.append("=" * 50)

        report.append(f"\n  NET WORTH: ${net_worth['net_worth']:,.2f}")
        report.append("\n  Accounts:")
        for name, acc in net_worth["accounts"].items():
            report.append(f"    {acc['name']}: ${acc['balance']:,.2f}")

        report.append(f"\n  MONTHLY SUMMARY ({monthly['month']}/{monthly['year']})")
        report.append(f"    Income: ${monthly['income']:,.2f}")
        report.append(f"    Expenses: ${monthly['expenses']:,.2f}")
        report.append(f"    Net: ${monthly['net']:+,.2f}")
        report.append(f"    Savings Rate: {monthly['savings_rate']:.1f}%")

        report.append("\n  BUDGET STATUS:")
        for cat, status in budget.items():
            emoji = "✓" if status["status"] == "ok" else "!" if status["status"] == "warning" else "✗"
            report.append(f"    {emoji} {cat}: ${status['spent']:.0f}/${status['budget']:.0f} ({status['pct_used']:.0f}%)")

        report.append("\n  SAVINGS GOALS:")
        for goal in self.get_savings_goals_progress():
            bar_len = int(goal["progress_pct"] / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            report.append(f"    {goal['name']}: [{bar}] {goal['progress_pct']:.0f}%")

        return "\n".join(report)


def main():
    """CLI entry point."""
    dashboard = FinancialDashboard()

    if len(sys.argv) < 2:
        print("Financial Dashboard")
        print("=" * 40)
        print("\nCommands:")
        print("  report              - Full financial report")
        print("  networth            - Net worth summary")
        print("  budget              - Budget status")
        print("  goals               - Savings goals")
        print("  add <amt> <cat> <desc> - Add expense")
        print("  income <amt> <desc>    - Add income")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "report":
        print(dashboard.generate_report())

    elif cmd == "networth":
        nw = dashboard.get_net_worth()
        print(f"\nNet Worth: ${nw['net_worth']:,.2f}")
        for name, acc in nw["accounts"].items():
            print(f"  {acc['name']}: ${acc['balance']:,.2f}")

    elif cmd == "budget":
        budget = dashboard.check_budget()
        print("\nBudget Status:")
        for cat, status in budget.items():
            emoji = "✓" if status["status"] == "ok" else "!" if status["status"] == "warning" else "✗"
            print(f"  {emoji} {cat}: ${status['spent']:.0f}/${status['budget']:.0f}")

    elif cmd == "goals":
        goals = dashboard.get_savings_goals_progress()
        print("\nSavings Goals:")
        for g in goals:
            print(f"  {g['name']}: ${g['current']:,.0f}/${g['target']:,.0f} ({g['progress_pct']:.0f}%)")

    elif cmd == "add" and len(sys.argv) >= 5:
        dashboard.add_transaction(float(sys.argv[2]), sys.argv[3], sys.argv[4])

    elif cmd == "income" and len(sys.argv) >= 4:
        dashboard.add_transaction(float(sys.argv[2]), "income", sys.argv[3], is_income=True)

    else:
        print("Unknown command. Run without args for help.")


import sys
if __name__ == "__main__":
    main()
