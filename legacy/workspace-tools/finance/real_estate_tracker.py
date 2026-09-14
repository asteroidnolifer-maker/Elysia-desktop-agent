#!/usr/bin/env python3
"""
Real Estate Tracker for Elysia Finance
Track property investments, rental income, mortgage.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class RealEstateTracker:
    """Track real estate investments."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "realestate.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"properties": [], "transactions": []}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_property(self, name: str, address: str, purchase_price: float,
                     current_value: float, monthly_rent: float = 0,
                     mortgage_payment: float = 0) -> Dict[str, Any]:
        prop = {
            "id": f"prop_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "name": name, "address": address, "purchase_price": purchase_price,
            "current_value": current_value, "monthly_rent": monthly_rent,
            "mortgage_payment": mortgage_payment,
            "added": datetime.now().isoformat()
        }
        self.data["properties"].append(prop)
        self._save_data()
        return prop

    def update_value(self, property_id: str, new_value: float):
        for p in self.data["properties"]:
            if p["id"] == property_id:
                p["current_value"] = new_value
                self._save_data()
                return True
        return False

    def get_portfolio_value(self) -> Dict[str, Any]:
        total_cost = sum(p.get("purchase_price", 0) for p in self.data["properties"])
        total_value = sum(p.get("current_value", 0) for p in self.data["properties"])
        total_rent = sum(p.get("monthly_rent", 0) for p in self.data["properties"])
        total_mortgage = sum(p.get("mortgage_payment", 0) for p in self.data["properties"])
        return {
            "total_cost": total_cost, "total_value": total_value,
            "unrealized_pnl": total_value - total_cost,
            "total_monthly_rent": total_rent, "total_mortgage": total_mortgage,
            "net_monthly_income": total_rent - total_mortgage,
            "cap_rate": (total_rent * 12) / total_value * 100 if total_value > 0 else 0
        }

    def get_cash_flow(self) -> Dict[str, Any]:
        total = self.get_portfolio_value()
        expenses = total["total_mortgage"]
        income = total["total_monthly_rent"]
        return {
            "monthly_income": income, "monthly_expenses": expenses,
            "monthly_cash_flow": income - expenses,
            "annual_cash_flow": (income - expenses) * 12
        }


class MortgageCalculator:
    """Calculate mortgage payments and amortization."""

    @staticmethod
    def calculate_payment(principal: float, annual_rate: float, years: int) -> Dict[str, float]:
        monthly_rate = annual_rate / 12
        n_payments = years * 12
        if monthly_rate == 0:
            payment = principal / n_payments
        else:
            payment = principal * (monthly_rate * (1 + monthly_rate) ** n_payments) / \
                      ((1 + monthly_rate) ** n_payments - 1)
        return {
            "monthly_payment": payment,
            "total_paid": payment * n_payments,
            "total_interest": payment * n_payments - principal
        }

    @staticmethod
    def amortization_schedule(principal: float, annual_rate: float, years: int) -> List[Dict[str, Any]]:
        monthly_rate = annual_rate / 12
        n_payments = years * 12
        if monthly_rate == 0:
            payment = principal / n_payments
        else:
            payment = principal * (monthly_rate * (1 + monthly_rate) ** n_payments) / \
                      ((1 + monthly_rate) ** n_payments - 1)
        schedule = []
        balance = principal
        for month in range(1, n_payments + 1):
            interest = balance * monthly_rate
            principal_paid = payment - interest
            balance -= principal_paid
            schedule.append({
                "month": month, "payment": payment,
                "principal": principal_paid, "interest": interest,
                "balance": max(0, balance)
            })
        return schedule

    @staticmethod
    def calculate_home_equity(current_value: float, mortgage_balance: float) -> Dict[str, Any]:
        equity = current_value - mortgage_balance
        ltv = mortgage_balance / current_value * 100 if current_value > 0 else 0
        return {
            "equity": equity, "ltv_ratio": ltv,
            "equity_pct": equity / current_value * 100 if current_value > 0 else 0
        }


def main():
    import sys

    if len(sys.argv) < 2:
        print("Real Estate Tracker")
        print("=" * 40)
        print("\nCommands:")
        print("  add <name> <address> <price> <value> [rent] [mortgage]")
        print("  portfolio              - Portfolio value")
        print("  cashflow               - Cash flow")
        print("  mortgage <principal> <rate> <years> - Mortgage calc")
        print("  amortize <principal> <rate> <years> - Amortization")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add" and len(sys.argv) >= 5:
        tracker = RealEstateTracker()
        rent = float(sys.argv[5]) if len(sys.argv) > 5 else 0
        mortgage = float(sys.argv[6]) if len(sys.argv) > 6 else 0
        tracker.add_property(sys.argv[2], sys.argv[3], float(sys.argv[4]),
                            float(sys.argv[4]), rent, mortgage)
        print("Property added")

    elif cmd == "portfolio":
        tracker = RealEstateTracker()
        p = tracker.get_portfolio_value()
        print(f"Total Value: ${p['total_value']:,.0f}")
        print(f"Net Equity: ${p['total_value'] - p['total_cost']:,.0f}")
        print(f"Cap Rate: {p['cap_rate']:.1f}%")

    elif cmd == "cashflow":
        tracker = RealEstateTracker()
        cf = tracker.get_cash_flow()
        print(f"Monthly Cash Flow: ${cf['monthly_cash_flow']:,.0f}")

    elif cmd == "mortgage" and len(sys.argv) >= 5:
        result = MortgageCalculator.calculate_payment(
            float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]))
        print(f"Monthly Payment: ${result['monthly_payment']:,.2f}")
        print(f"Total Interest: ${result['total_interest']:,.2f}")

    elif cmd == "amortize" and len(sys.argv) >= 5:
        schedule = MortgageCalculator.amortization_schedule(
            float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4]))
        for s in schedule[:12]:
            print(f"  Month {s['month']}: ${s['payment']:.2f} (P: ${s['principal']:.2f} I: ${s['interest']:.2f})")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
