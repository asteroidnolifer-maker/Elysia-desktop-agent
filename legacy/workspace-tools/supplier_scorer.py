#!/usr/bin/env python3
"""Task #1453: Supplier reliability scoring system."""
import json, os, random

WORKSPACE = "/data/elysia/workspace/tools"

def score_supplier(supplier_data):
    """Score supplier reliability on multiple factors."""
    scores = {}
    scores["communication"] = min(25, supplier_data.get("response_time_score", 0) * 0.25)
    scores["shipping"] = min(25, supplier_data.get("on_time_rate", 0) * 0.25)
    scores["quality"] = min(25, supplier_data.get("quality_score", 0) * 0.25)
    scores["pricing"] = min(25, 25 - supplier_data.get("price_premium", 0) * 0.5)
    total = sum(scores.values())
    grade = "A+" if total > 90 else "A" if total > 80 else "B+" if total > 70 else "B" if total > 60 else "C" if total > 50 else "D" if total > 40 else "F"
    return {"scores": {k: round(v, 1) for k, v in scores.items()}, "total": round(total, 1), "grade": grade, "recommendation": "reliable" if total > 70 else "caution" if total > 50 else "avoid"}

if __name__ == "__main__":
    result = score_supplier({"response_time_score": 90, "on_time_rate": 95, "quality_score": 85, "price_premium": 10})
    print(f"Supplier Score: {result['total']}/100 (Grade: {result['grade']})")
    print(f"Recommendation: {result['recommendation']}")
    for k, v in result['scores'].items():
        print(f"  {k}: {v}")
    output = os.path.join(WORKSPACE, "supplier_score.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
