#!/usr/bin/env python3
"""
Financial Forecasting for Elysia Finance
Financial projections, scenario planning, and what-if analysis.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class FinancialForecaster:
    """Financial forecasting and projections."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "forecast_data.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"assumptions": {}, "projections": [], "scenarios": {}}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def set_assumptions(self, monthly_income: float, monthly_expenses: float,
                        savings_rate: float, investment_return: float = 0.07,
                        inflation_rate: float = 0.03):
        self.data["assumptions"] = {
            "monthly_income": monthly_income, "monthly_expenses": monthly_expenses,
            "savings_rate": savings_rate, "investment_return": investment_return,
            "inflation_rate": inflation_rate
        }
        self._save_data()

    def project_net_worth(self, years: int = 10) -> List[Dict[str, Any]]:
        a = self.data.get("assumptions", {})
        monthly_savings = a.get("monthly_income", 0) - a.get("monthly_expenses", 0)
        annual_return = a.get("investment_return", 0.07)
        projections = []
        net_worth = 0
        for year in range(1, years + 1):
            net_worth = net_worth * (1 + annual_return) + monthly_savings * 12
            projections.append({
                "year": year, "net_worth": net_worth,
                "annual_savings": monthly_savings * 12,
                "investment_growth": net_worth * annual_return
            })
        return projections

    def run_scenario(self, name: str, income_change: float = 0,
                     expense_change: float = 0, return_change: float = 0) -> Dict[str, Any]:
        a = self.data.get("assumptions", {})
        scenario = {
            "name": name,
            "monthly_income": a.get("monthly_income", 0) * (1 + income_change),
            "monthly_expenses": a.get("monthly_expenses", 0) * (1 + expense_change),
            "investment_return": a.get("investment_return", 0.07) + return_change
        }
        self.data["scenarios"][name] = scenario
        self._save_data()
        return scenario

    def what_if(self, monthly_contribution: float, years: int = 10,
                annual_return: float = 0.07) -> Dict[str, Any]:
        total_contributed = monthly_contribution * 12 * years
        balance = 0
        yearly = []
        for year in range(1, years + 1):
            balance = balance * (1 + annual_return) + monthly_contribution * 12
            yearly.append({"year": year, "balance": balance})
        return {
            "total_contributed": total_contributed,
            "final_balance": balance,
            "total_growth": balance - total_contributed,
            "yearly": yearly
        }

    def retirement_calculator(self, current_age: int, retirement_age: int,
                               current_savings: float, monthly_contribution: float,
                               annual_return: float = 0.07, annual_expenses: float = 40000) -> Dict[str, Any]:
        years_to_retirement = retirement_age - current_age
        balance = current_savings
        for _ in range(years_to_retirement):
            balance = balance * (1 + annual_return) + monthly_contribution * 12
        annual_withdrawal = annual_expenses
        years_in_retirement = 30
        sustainable_withdrawal = balance * 0.04
        return {
            "years_to_retirement": years_to_retirement,
            "projected_savings": balance,
            "annual_expenses": annual_expenses,
            "sustainable_annual_withdrawal": sustainable_withdrawal,
            "years_funded": balance / annual_withdrawal if annual_withdrawal > 0 else 0,
            "on_track": sustainable_withdrawal >= annual_expenses
        }

    def savings_calculator(self, goal_amount: float, monthly_contribution: float,
                           annual_return: float = 0.05) -> Dict[str, Any]:
        monthly_rate = annual_return / 12
        if monthly_rate == 0:
            months = goal_amount / monthly_contribution if monthly_contribution > 0 else 0
        else:
            import math
            months = math.log((goal_amount * monthly_rate / monthly_contribution) + 1) / math.log(1 + monthly_rate)
        return {
            "goal": goal_amount, "monthly_contribution": monthly_contribution,
            "months_to_goal": int(months), "years_to_goal": months / 12,
            "total_contributed": monthly_contribution * months
        }


class EmergencyFund:
    """Track emergency fund progress."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "emergency_fund.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"target": 0, "current": 0, "monthly_expenses": 0}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def set_target(self, monthly_expenses: float, months: int = 6):
        self.data["monthly_expenses"] = monthly_expenses
        self.data["target"] = monthly_expenses * months
        self._save_data()

    def contribute(self, amount: float):
        self.data["current"] += amount
        self._save_data()

    def get_progress(self) -> Dict[str, Any]:
        target = self.data.get("target", 0)
        current = self.data.get("current", 0)
        return {
            "target": target, "current": current,
            "progress_pct": current / target * 100 if target > 0 else 0,
            "remaining": target - current,
            "months_covered": current / self.data.get("monthly_expenses", 1)
        }


def main():
    import sys

    if len(sys.argv) < 2:
        print("Financial Forecasting")
        print("=" * 40)
        print("\nCommands:")
        print("  project <years>          - Net worth projection")
        print("  whatif <monthly> <years> - What-if scenario")
        print("  retire <age> <ret_age> <savings> <monthly> - Retirement calc")
        print("  savings <goal> <monthly> - Savings calculator")
        print("  emergency <expenses>     - Set emergency fund target")
        sys.exit(0)

    cmd = sys.argv[1]

    forecaster = FinancialForecaster()
    forecaster.set_assumptions(5000, 3000, 0.4)

    if cmd == "project" and len(sys.argv) >= 3:
        projections = forecaster.project_net_worth(int(sys.argv[2]))
        for p in projections:
            print(f"  Year {p['year']}: ${p['net_worth']:,.0f}")

    elif cmd == "whatif" and len(sys.argv) >= 4:
        result = forecaster.what_if(float(sys.argv[2]), int(sys.argv[3]))
        print(f"Final balance: ${result['final_balance']:,.0f}")

    elif cmd == "retire" and len(sys.argv) >= 6:
        result = forecaster.retirement_calculator(
            int(sys.argv[2]), int(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]))
        print(f"Projected savings: ${result['projected_savings']:,.0f}")
        print(f"On track: {result['on_track']}")

    elif cmd == "savings" and len(sys.argv) >= 4:
        result = forecaster.savings_calculator(float(sys.argv[2]), float(sys.argv[3]))
        print(f"Months to goal: {result['months_to_goal']}")

    elif cmd == "emergency" and len(sys.argv) >= 3:
        fund = EmergencyFund()
        fund.set_target(float(sys.argv[2]))
        print(f"Emergency fund target set")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
