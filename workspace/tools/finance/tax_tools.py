#!/usr/bin/env python3
"""
Tax Tools for Elysia Finance
Tax estimation, deduction tracking, and preparation.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class TaxCalculator:
    """Calculate estimated taxes and deductions."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "tax_data.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"income": [], "deductions": [], "tax_credits": []}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_income(self, source: str, amount: float, category: str = "earned"):
        self.data["income"].append({
            "source": source, "amount": amount, "category": category,
            "date": datetime.now().isoformat()
        })
        self._save_data()

    def add_deduction(self, description: str, amount: float, category: str):
        self.data["deductions"].append({
            "description": description, "amount": amount, "category": category,
            "date": datetime.now().isoformat()
        })
        self._save_data()

    def add_tax_credit(self, description: str, amount: float):
        self.data["tax_credits"].append({
            "description": description, "amount": amount,
            "date": datetime.now().isoformat()
        })
        self._save_data()

    def get_total_income(self) -> float:
        return sum(i.get("amount", 0) for i in self.data.get("income", []))

    def get_total_deductions(self) -> float:
        return sum(d.get("amount", 0) for d in self.data.get("deductions", []))

    def get_total_credits(self) -> float:
        return sum(c.get("amount", 0) for c in self.data.get("tax_credits", []))

    def estimate_federal_tax(self, taxable_income: float) -> float:
        brackets = [
            (11000, 0.10), (44725, 0.12), (95375, 0.22),
            (182100, 0.24), (231250, 0.32), (578125, 0.35), (float("inf"), 0.37)
        ]
        tax = 0
        prev = 0
        for limit, rate in brackets:
            if taxable_income <= prev:
                break
            taxable = min(taxable_income, limit) - prev
            tax += taxable * rate
            prev = limit
        return tax

    def estimate_self_employment_tax(self, net_income: float) -> float:
        se_tax = net_income * 0.9235 * 0.153
        return se_tax

    def calculate_taxable_income(self, gross_income: float) -> Dict[str, float]:
        standard_deduction = 14600
        deductions = self.get_total_deductions()
        itemized = max(deductions, standard_deduction)
        taxable = max(0, gross_income - itemized)
        return {
            "gross_income": gross_income, "standard_deduction": standard_deduction,
            "itemized_deductions": deductions, "deduction_used": itemized,
            "taxable_income": taxable
        }

    def generate_tax_summary(self) -> Dict[str, Any]:
        total_income = self.get_total_income()
        total_deductions = self.get_total_deductions()
        total_credits = self.get_total_credits()
        taxable = self.calculate_taxable_income(total_income)
        federal_tax = self.estimate_federal_tax(taxable["taxable_income"])
        se_tax = self.estimate_self_employment_tax(total_income)
        return {
            "total_income": total_income, "total_deductions": total_deductions,
            "total_credits": total_credits, "taxable_income": taxable["taxable_income"],
            "estimated_federal_tax": federal_tax, "estimated_se_tax": se_tax,
            "total_tax": federal_tax + se_tax - total_credits,
            "effective_rate": (federal_tax + se_tax - total_credits) / total_income * 100 if total_income > 0 else 0
        }


class DeductionTracker:
    """Track potential tax deductions."""

    CATEGORIES = {
        "home_office": "Home office expenses",
        "medical": "Medical expenses",
        "charity": "Charitable donations",
        "education": "Education expenses",
        "business": "Business expenses",
        "state_local": "State and local taxes",
        "mortgage_interest": "Mortgage interest"
    }

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "deductions.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"deductions": []}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_deduction(self, category: str, amount: float, description: str, receipt_path: str = None):
        self.data["deductions"].append({
            "category": category, "amount": amount, "description": description,
            "receipt_path": receipt_path, "date": datetime.now().isoformat()
        })
        self._save_data()

    def get_by_category(self) -> Dict[str, float]:
        cats = {}
        for d in self.data.get("deductions", []):
            cat = d.get("category", "other")
            cats[cat] = cats.get(cat, 0) + d.get("amount", 0)
        return cats

    def get_total(self) -> float:
        return sum(d.get("amount", 0) for d in self.data.get("deductions", []))


def main():
    import sys

    if len(sys.argv) < 2:
        print("Tax Tools")
        print("=" * 40)
        print("\nCommands:")
        print("  income <source> <amount>     - Add income")
        print("  deduct <desc> <amount> <cat> - Add deduction")
        print("  summary                      - Tax summary")
        print("  estimate <income>            - Quick estimate")
        print("  deductions                   - Deduction categories")
        sys.exit(0)

    cmd = sys.argv[1]

    calc = TaxCalculator()

    if cmd == "income" and len(sys.argv) >= 4:
        calc.add_income(sys.argv[2], float(sys.argv[3]))
        print("Income added")

    elif cmd == "deduct" and len(sys.argv) >= 5:
        calc.add_deduction(sys.argv[2], float(sys.argv[3]), sys.argv[4])
        print("Deduction added")

    elif cmd == "summary":
        s = calc.generate_tax_summary()
        print(f"Income: ${s['total_income']:,.0f}")
        print(f"Deductions: ${s['total_deductions']:,.0f}")
        print(f"Taxable: ${s['taxable_income']:,.0f}")
        print(f"Est. Federal Tax: ${s['estimated_federal_tax']:,.0f}")
        print(f"Total Tax: ${s['total_tax']:,.0f} ({s['effective_rate']:.1f}%)")

    elif cmd == "estimate" and len(sys.argv) >= 3:
        income = float(sys.argv[2])
        taxable = calc.calculate_taxable_income(income)
        tax = calc.estimate_federal_tax(taxable["taxable_income"])
        print(f"Gross: ${income:,.0f}, Taxable: ${taxable['taxable_income']:,.0f}")
        print(f"Est. Federal Tax: ${tax:,.0f} ({tax/income*100:.1f}%)")

    elif cmd == "deductions":
        for cat, desc in DeductionTracker.CATEGORIES.items():
            print(f"  {cat}: {desc}")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
