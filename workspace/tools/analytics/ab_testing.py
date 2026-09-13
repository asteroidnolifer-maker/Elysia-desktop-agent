#!/usr/bin/env python3
"""
Elysia A/B Testing Framework - Task 1610
Experiment management with statistical significance calculation.
"""
import json
import math
import random
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class ABTest:
    def __init__(self, name: str, variants: List[str], traffic_split: List[float] = None):
        self.name = name
        self.variants = variants
        self.traffic_split = traffic_split or [1.0 / len(variants)] * len(variants)
        self.results: Dict[str, Dict[str, int]] = {v: {"impressions": 0, "conversions": 0} for v in variants}
        self.created = datetime.now().isoformat()
        self.status = "running"

    def assign_variant(self, user_id: str = None) -> str:
        r = random.random()
        cumulative = 0
        for i, variant in enumerate(self.variants):
            cumulative += self.traffic_split[i]
            if r <= cumulative:
                return variant
        return self.variants[-1]

    def record_impression(self, variant: str):
        if variant in self.results:
            self.results[variant]["impressions"] += 1

    def record_conversion(self, variant: str):
        if variant in self.results:
            self.results[variant]["conversions"] += 1

    def get_conversion_rate(self, variant: str) -> float:
        data = self.results.get(variant, {})
        impressions = data.get("impressions", 0)
        if impressions == 0:
            return 0
        return data["conversions"] / impressions * 100

    def calculate_significance(self) -> Dict[str, Any]:
        if len(self.variants) < 2:
            return {"significant": False, "reason": "need at least 2 variants"}

        control = self.variants[0]
        treatment = self.variants[1]
        c_data = self.results[control]
        t_data = self.results[treatment]

        if c_data["impressions"] < 30 or t_data["impressions"] < 30:
            return {"significant": False, "reason": "insufficient sample size",
                    "min_required": 30}

        c_rate = c_data["conversions"] / c_data["impressions"]
        t_rate = t_data["conversions"] / t_data["impressions"]
        c_n = c_data["impressions"]
        t_n = t_data["impressions"]

        pooled = (c_data["conversions"] + t_data["conversions"]) / (c_n + t_n)
        se = math.sqrt(pooled * (1 - pooled) * (1/c_n + 1/t_n))

        if se == 0:
            return {"significant": False, "reason": "zero standard error"}

        z_score = (t_rate - c_rate) / se
        p_value = 2 * (1 - _norm_cdf(abs(z_score)))
        significant = p_value < 0.05

        lift = ((t_rate - c_rate) / max(c_rate, 0.001)) * 100

        return {
            "significant": significant,
            "p_value": round(p_value, 4),
            "z_score": round(z_score, 4),
            "control_rate": round(c_rate * 100, 2),
            "treatment_rate": round(t_rate * 100, 2),
            "lift_pct": round(lift, 2),
            "winner": treatment if significant and t_rate > c_rate else control
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "variants": self.variants,
            "traffic_split": self.traffic_split,
            "results": self.results,
            "status": self.status,
            "created": self.created
        }


def _norm_cdf(x: float) -> float:
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x) / math.sqrt(2)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5*t + a4)*t) + a3)*t + a2)*t + a1) * t * math.exp(-x*x)
    return 0.5 * (1.0 + sign * y)


class ABTestManager:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "ab_tests")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tests: Dict[str, ABTest] = {}

    def create_test(self, name: str, variants: List[str],
                    traffic_split: List[float] = None) -> ABTest:
        test = ABTest(name, variants, traffic_split)
        self.tests[name] = test
        return test

    def get_test(self, name: str) -> Optional[ABTest]:
        return self.tests.get(name)

    def list_tests(self) -> List[Dict[str, Any]]:
        return [
            {"name": t.name, "variants": t.variants, "status": t.status}
            for t in self.tests.values()
        ]

    def simulate(self, test_name: str, impressions: int = 1000,
                 true_rates: Dict[str, float] = None):
        test = self.tests.get(test_name)
        if not test:
            return
        true_rates = true_rates or {v: 0.1 for v in test.variants}
        for _ in range(impressions):
            variant = test.assign_variant()
            test.record_impression(variant)
            if random.random() < true_rates.get(variant, 0.1):
                test.record_conversion(variant)

    def save(self):
        data = {name: t.to_dict() for name, t in self.tests.items()}
        path = self.data_dir / "tests.json"
        path.write_text(json.dumps(data, indent=2))


def main():
    manager = ABTestManager()

    if len(sys.argv) < 2:
        print("Elysia A/B Testing Framework")
        print("Commands: create <name> <variants>, simulate <name>, results <name>, list")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "create" and len(sys.argv) >= 4:
        variants = sys.argv[3].split(",")
        test = manager.create_test(sys.argv[2], variants)
        print(f"[+] Created test: {test.name} with {len(variants)} variants")
    elif cmd == "simulate" and len(sys.argv) >= 3:
        manager.simulate(sys.argv[2])
        print(f"[+] Simulated 1000 impressions")
    elif cmd == "results" and len(sys.argv) >= 3:
        test = manager.get_test(sys.argv[2])
        if test:
            sig = test.calculate_significance()
            print(f"\nTest: {test.name}")
            for v in test.variants:
                print(f"  {v}: {test.get_conversion_rate(v):.1f}% "
                      f"({test.results[v]['conversions']}/{test.results[v]['impressions']})")
            print(f"\nSignificance: {json.dumps(sig, indent=2)}")
    elif cmd == "list":
        tests = manager.list_tests()
        for t in tests:
            print(f"  {t['name']}: {', '.join(t['variants'])} [{t['status']}]")


if __name__ == "__main__":
    main()
