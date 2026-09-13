#!/usr/bin/env python3
"""
Budget Manager for Elysia Finance
Personal budget tracking, expense categorization, goals.
"""
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime, timedelta


class BudgetManager:
    """Personal budget management system."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "budget_data.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {
            "monthly_income": 0,
            "categories": {
                "housing": {"budget": 0, "spent": 0},
                "food": {"budget": 0, "spent": 0},
                "transport": {"budget": 0, "spent": 0},
                "utilities": {"budget": 0, "spent": 0},
                "entertainment": {"budget": 0, "spent": 0},
                "healthcare": {"budget": 0, "spent": 0},
                "savings": {"budget": 0, "spent": 0},
                "other": {"budget": 0, "spent": 0}
            },
            "transactions": [],
            "savings_goals": []
        }

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def set_monthly_income(self, amount: float):
        self.data["monthly_income"] = amount
        self._save_data()

    def set_category_budget(self, category: str, amount: float):
        if category not in self.data["categories"]:
            self.data["categories"][category] = {"budget": 0, "spent": 0}
        self.data["categories"][category]["budget"] = amount
        self._save_data()

    def add_expense(self, amount: float, category: str, description: str) -> Dict[str, Any]:
        transaction = {
            "type": "expense", "amount": amount, "category": category,
            "description": description, "date": datetime.now().isoformat()
        }
        self.data["transactions"].append(transaction)
        if category in self.data["categories"]:
            self.data["categories"][category]["spent"] += amount
        self._save_data()
        return transaction

    def add_income(self, amount: float, description: str) -> Dict[str, Any]:
        transaction = {
            "type": "income", "amount": amount, "category": "income",
            "description": description, "date": datetime.now().isoformat()
        }
        self.data["transactions"].append(transaction)
        self.data["monthly_income"] += amount
        self._save_data()
        return transaction

    def get_budget_status(self) -> Dict[str, Any]:
        status = {}
        for cat, data in self.data["categories"].items():
            budget = data.get("budget", 0)
            spent = data.get("spent", 0)
            remaining = budget - spent
            pct = (spent / budget * 100) if budget > 0 else 0
            status[cat] = {
                "budget": budget, "spent": spent, "remaining": remaining,
                "pct_used": pct, "status": "over" if remaining < 0 else "warning" if pct > 80 else "ok"
            }
        return status

    def get_monthly_summary(self) -> Dict[str, Any]:
        now = datetime.now()
        monthly = [t for t in self.data["transactions"]
                   if datetime.fromisoformat(t["date"]).month == now.month]
        income = sum(t["amount"] for t in monthly if t["type"] == "income")
        expenses = sum(t["amount"] for t in monthly if t["type"] == "expense")
        return {
            "income": income, "expenses": expenses, "net": income - expenses,
            "savings_rate": ((income - expenses) / income * 100) if income > 0 else 0
        }

    def add_savings_goal(self, name: str, target: float, deadline: str = None):
        self.data["savings_goals"].append({
            "name": name, "target": target, "current": 0,
            "deadline": deadline, "created": datetime.now().isoformat()
        })
        self._save_data()

    def contribute_to_goal(self, goal_name: str, amount: float):
        for goal in self.data["savings_goals"]:
            if goal["name"] == goal_name:
                goal["current"] += amount
                self._save_data()
                return True
        return False

    def get_goals_progress(self) -> List[Dict[str, Any]]:
        goals = []
        for g in self.data.get("savings_goals", []):
            progress = g["current"] / g["target"] * 100 if g["target"] > 0 else 0
            goals.append({**g, "progress_pct": progress, "remaining": g["target"] - g["current"]})
        return goals

    def get_spending_by_category(self) -> Dict[str, float]:
        return {cat: data["spent"] for cat, data in self.data["categories"].items()}

    def get_daily_spending(self, days: int = 30) -> List[Dict[str, Any]]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        daily = {}
        for t in self.data["transactions"]:
            if t["type"] == "expense" and t["date"] >= cutoff:
                day = t["date"][:10]
                daily[day] = daily.get(day, 0) + t["amount"]
        return [{"date": d, "amount": a} for d, a in sorted(daily.items())]

    def reset_monthly(self):
        for cat in self.data["categories"]:
            self.data["categories"][cat]["spent"] = 0
        self._save_data()


class BillReminders:
    """Track and remind about bills."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "bills.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"bills": [], "paid": []}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_bill(self, name: str, amount: float, due_day: int, category: str = "other"):
        self.data["bills"].append({
            "name": name, "amount": amount, "due_day": due_day,
            "category": category, "added": datetime.now().isoformat()
        })
        self._save_data()

    def get_upcoming_bills(self, days: int = 7) -> List[Dict[str, Any]]:
        today = datetime.now().day
        upcoming = []
        for bill in self.data["bills"]:
            due = bill["due_day"]
            days_until = (due - today) % 30
            if 0 <= days_until <= days:
                upcoming.append({**bill, "days_until_due": days_until})
        return sorted(upcoming, key=lambda x: x["days_until_due"])

    def mark_paid(self, bill_name: str):
        self.data["paid"].append({"name": bill_name, "paid_date": datetime.now().isoformat()})
        self._save_data()


def main():
    import sys
    mgr = BudgetManager()

    if len(sys.argv) < 2:
        print("Budget Manager")
        print("=" * 40)
        print("\nCommands:")
        print("  income <amount> <desc>    - Add income")
        print("  expense <amount> <cat> <desc> - Add expense")
        print("  budget                    - Budget status")
        print("  summary                   - Monthly summary")
        print("  goals                     - Savings goals")
        print("  spending                  - Spending by category")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "income" and len(sys.argv) >= 4:
        mgr.add_income(float(sys.argv[2]), sys.argv[3])
        print(f"Income added: ${float(sys.argv[2]):,.2f}")
    elif cmd == "expense" and len(sys.argv) >= 5:
        mgr.add_expense(float(sys.argv[2]), sys.argv[3], sys.argv[4])
        print(f"Expense added: ${float(sys.argv[2]):,.2f}")
    elif cmd == "budget":
        for cat, status in mgr.get_budget_status().items():
            emoji = "✓" if status["status"] == "ok" else "!" if status["status"] == "warning" else "✗"
            print(f"  {emoji} {cat}: ${status['spent']:.0f}/${status['budget']:.0f} ({status['pct_used']:.0f}%)")
    elif cmd == "summary":
        s = mgr.get_monthly_summary()
        print(f"Income: ${s['income']:,.2f}, Expenses: ${s['expenses']:,.2f}, Net: ${s['net']:+,.2f}")
    elif cmd == "goals":
        for g in mgr.get_goals_progress():
            print(f"  {g['name']}: ${g['current']:,.0f}/${g['target']:,.0f} ({g['progress_pct']:.0f}%)")
    elif cmd == "spending":
        for cat, amount in mgr.get_spending_by_category().items():
            print(f"  {cat}: ${amount:,.2f}")
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
