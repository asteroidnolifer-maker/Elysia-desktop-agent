#!/usr/bin/env python3
"""
Subscription Tracker for Elysia Finance
Track recurring subscriptions and identify savings.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class SubscriptionTracker:
    """Track and manage recurring subscriptions."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "subscriptions.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"subscriptions": [], "categories": {}}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_subscription(self, name: str, cost: float, billing_cycle: str,
                         category: str = "other", start_date: str = None) -> Dict[str, Any]:
        monthly_cost = cost
        if billing_cycle == "yearly":
            monthly_cost = cost / 12
        elif billing_cycle == "weekly":
            monthly_cost = cost * 4

        sub = {
            "id": f"sub_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "name": name, "cost": cost, "billing_cycle": billing_cycle,
            "monthly_cost": monthly_cost, "category": category,
            "start_date": start_date or datetime.now().isoformat(),
            "active": True
        }
        self.data["subscriptions"].append(sub)
        self._save_data()
        return sub

    def cancel_subscription(self, sub_id: str):
        for s in self.data["subscriptions"]:
            if s["id"] == sub_id:
                s["active"] = False
                self._save_data()
                return True
        return False

    def get_active(self) -> List[Dict[str, Any]]:
        return [s for s in self.data["subscriptions"] if s.get("active", True)]

    def get_total_monthly(self) -> float:
        return sum(s.get("monthly_cost", 0) for s in self.get_active())

    def get_total_yearly(self) -> float:
        return self.get_total_monthly() * 12

    def get_by_category(self) -> Dict[str, float]:
        categories = {}
        for s in self.get_active():
            cat = s.get("category", "other")
            categories[cat] = categories.get(cat, 0) + s.get("monthly_cost", 0)
        return categories

    def identify_savings(self) -> List[Dict[str, Any]]:
        suggestions = []
        for s in self.get_active():
            if s.get("billing_cycle") == "monthly":
                suggestions.append({
                    "subscription": s["name"],
                    "action": "Switch to yearly",
                    "potential_savings": s.get("cost", 0) * 0.2
                })
        return suggestions

    def get_recommendations(self) -> List[str]:
        recs = []
        total = self.get_total_monthly()
        if total > 100:
            recs.append("Consider canceling unused subscriptions")
        if total > 200:
            recs.append("Review all subscriptions for necessity")
        return recs


class CostOptimization:
    """Identify cost savings opportunities."""

    @staticmethod
    def analyze_spending(transactions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        categories = {}
        for t in transactions:
            cat = t.get("category", "other")
            categories[cat] = categories.get(cat, 0) + t.get("amount", 0)
        sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
        return [{"category": c, "total": t} for c, t in sorted_cats]


def main():
    import sys
    tracker = SubscriptionTracker()

    if len(sys.argv) < 2:
        print("Subscription Tracker")
        print("=" * 40)
        print("\nCommands:")
        print("  add <name> <cost> <cycle> [category]")
        print("  list                  - Active subscriptions")
        print("  total                 - Total monthly cost")
        print("  cancel <id>           - Cancel subscription")
        print("  savings               - Savings suggestions")
        print("  categories            - Spending by category")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add" and len(sys.argv) >= 4:
        cat = sys.argv[4] if len(sys.argv) > 4 else "other"
        tracker.add_subscription(sys.argv[2], float(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else "monthly", cat)
        print("Subscription added")
    elif cmd == "list":
        for s in tracker.get_active():
            print(f"  {s['name']}: ${s['monthly_cost']:.2f}/mo ({s['billing_cycle']})")
    elif cmd == "total":
        print(f"Total: ${tracker.get_total_monthly():.2f}/mo (${tracker.get_total_yearly():.2f}/yr)")
    elif cmd == "cancel" and len(sys.argv) >= 3:
        tracker.cancel_subscription(sys.argv[2])
        print("Subscription cancelled")
    elif cmd == "savings":
        for s in tracker.identify_savings():
            print(f"  {s['subscription']}: Save ${s['potential_savings']:.2f}/mo")
    elif cmd == "categories":
        for cat, cost in tracker.get_by_category().items():
            print(f"  {cat}: ${cost:.2f}/mo")
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
