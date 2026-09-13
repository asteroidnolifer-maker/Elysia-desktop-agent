#!/usr/bin/env python3
"""
Insurance Tracker for Elysia Finance
Track insurance policies, coverage, and claims.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class InsuranceTracker:
    """Track insurance policies and coverage."""

    def __init__(self, data_path: str = None):
        self.data_path = data_path or Path(__file__).parent / "insurance_data.json"
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        if self.data_path.exists():
            return json.loads(self.data_path.read_text())
        return {"policies": [], "claims": []}

    def _save_data(self):
        self.data_path.write_text(json.dumps(self.data, indent=2))

    def add_policy(self, provider: str, policy_type: str, policy_number: str,
                   premium: float, coverage_amount: float, start_date: str,
                   end_date: str, details: Dict[str, Any] = None) -> Dict[str, Any]:
        policy = {
            "id": f"pol_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "provider": provider, "type": policy_type, "policy_number": policy_number,
            "premium": premium, "coverage_amount": coverage_amount,
            "start_date": start_date, "end_date": end_date,
            "details": details or {}, "added": datetime.now().isoformat()
        }
        self.data["policies"].append(policy)
        self._save_data()
        return policy

    def remove_policy(self, policy_id: str):
        self.data["policies"] = [p for p in self.data["policies"] if p["id"] != policy_id]
        self._save_data()

    def get_policies_by_type(self, policy_type: str) -> List[Dict[str, Any]]:
        return [p for p in self.data["policies"] if p.get("type") == policy_type]

    def get_total_coverage(self) -> Dict[str, Any]:
        total_premium = sum(p.get("premium", 0) for p in self.data["policies"])
        total_coverage = sum(p.get("coverage_amount", 0) for p in self.data["policies"])
        by_type = {}
        for p in self.data["policies"]:
            t = p.get("type", "other")
            if t not in by_type:
                by_type[t] = {"premium": 0, "coverage": 0}
            by_type[t]["premium"] += p.get("premium", 0)
            by_type[t]["coverage"] += p.get("coverage_amount", 0)
        return {
            "total_premium": total_premium, "total_coverage": total_coverage,
            "policy_count": len(self.data["policies"]), "by_type": by_type
        }

    def get_expiring_soon(self, days: int = 30) -> List[Dict[str, Any]]:
        from datetime import timedelta
        cutoff = (datetime.now() + timedelta(days=days)).isoformat()[:10]
        return [p for p in self.data["policies"] if p.get("end_date", "") <= cutoff]

    def add_claim(self, policy_id: str, claim_amount: float, description: str,
                  status: str = "filed") -> Dict[str, Any]:
        claim = {
            "id": f"clm_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "policy_id": policy_id, "claim_amount": claim_amount,
            "description": description, "status": status,
            "filed_date": datetime.now().isoformat()
        }
        self.data["claims"].append(claim)
        self._save_data()
        return claim

    def get_claims(self, status: str = None) -> List[Dict[str, Any]]:
        claims = self.data.get("claims", [])
        if status:
            claims = [c for c in claims if c.get("status") == status]
        return claims

    def identify_coverage_gaps(self) -> List[Dict[str, Any]]:
        types = {p.get("type") for p in self.data["policies"]}
        essential = ["health", "auto", "home", "life", "disability"]
        gaps = []
        for t in essential:
            if t not in types:
                gaps.append({"type": t, "status": "missing", "recommendation": f"Consider getting {t} insurance"})
        return gaps


class PolicyComparator:
    """Compare insurance policies."""

    @staticmethod
    def compare(policies: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not policies:
            return {"error": "No policies to compare"}
        comparison = {"policies": [], "best_value": None}
        best_ratio = float("inf")
        for p in policies:
            premium = p.get("premium", 0)
            coverage = p.get("coverage_amount", 1)
            ratio = premium / coverage if coverage > 0 else float("inf")
            comparison["policies"].append({
                "provider": p.get("provider"), "type": p.get("type"),
                "premium": premium, "coverage": coverage, "ratio": ratio
            })
            if ratio < best_ratio:
                best_ratio = ratio
                comparison["best_value"] = p.get("provider")
        return comparison


def main():
    import sys
    tracker = InsuranceTracker()

    if len(sys.argv) < 2:
        print("Insurance Tracker")
        print("=" * 40)
        print("\nCommands:")
        print("  add <provider> <type> <number> <premium> <coverage> <start> <end>")
        print("  policies              - List policies")
        print("  coverage              - Total coverage")
        print("  expiring [days]       - Expiring policies")
        print("  claim <policy_id> <amount> <desc>")
        print("  gaps                  - Coverage gaps")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "add" and len(sys.argv) >= 8:
        tracker.add_policy(sys.argv[2], sys.argv[3], sys.argv[4],
                          float(sys.argv[5]), float(sys.argv[6]),
                          sys.argv[7], sys.argv[8] if len(sys.argv) > 8 else "")
        print("Policy added")
    elif cmd == "policies":
        for p in tracker.data["policies"]:
            print(f"  {p['type']}: {p['provider']} - ${p['premium']:.2f}/mo (${p['coverage_amount']:,.0f} coverage)")
    elif cmd == "coverage":
        total = tracker.get_total_coverage()
        print(f"Total Coverage: ${total['total_coverage']:,.0f}")
        print(f"Total Premium: ${total['total_premium']:,.2f}/mo")
    elif cmd == "expiring":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        for p in tracker.get_expiring_soon(days):
            print(f"  {p['type']} ({p['provider']}) expires: {p['end_date']}")
    elif cmd == "claim" and len(sys.argv) >= 5:
        tracker.add_claim(sys.argv[2], float(sys.argv[3]), sys.argv[4])
        print("Claim filed")
    elif cmd == "gaps":
        for gap in tracker.identify_coverage_gaps():
            print(f"  [{gap['status']}] {gap['type']}: {gap['recommendation']}")
    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
