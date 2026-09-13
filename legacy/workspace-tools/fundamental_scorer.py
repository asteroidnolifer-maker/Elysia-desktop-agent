#!/usr/bin/env python3
"""Task #29: Fundamental analysis scorer."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def score_fundamentals(data):
    """Score a stock based on fundamental metrics."""
    score = 0
    breakdown = {}
    # Valuation (30 points)
    pe_score = max(0, min(30, 30 - (data.get("pe", 25) - 15) * 2))
    breakdown["valuation"] = round(pe_score, 1)
    score += pe_score
    # Profitability (25 points)
    margin_score = min(25, data.get("profit_margin", 10) / 2)
    breakdown["profitability"] = round(margin_score, 1)
    score += margin_score
    # Growth (25 points)
    growth_score = min(25, data.get("revenue_growth", 5) / 2)
    breakdown["growth"] = round(growth_score, 1)
    score += growth_score
    # Dividend (10 points)
    div_score = min(10, data.get("dividend_yield", 0) * 3)
    breakdown["dividend"] = round(div_score, 1)
    score += div_score
    # Financial health (10 points)
    health_score = min(10, 10 - data.get("debt_to_equity", 0.5) * 5)
    breakdown["financial_health"] = max(0, round(health_score, 1))
    score += max(0, health_score)
    grade = "A+" if score > 85 else "A" if score > 75 else "B+" if score > 65 else "B" if score > 55 else "C+" if score > 45 else "C" if score > 35 else "D" if score > 25 else "F"
    return {"score": round(score, 1), "grade": grade, "breakdown": breakdown}

if __name__ == "__main__":
    result = score_fundamentals({"pe": 22, "profit_margin": 28, "revenue_growth": 15, "dividend_yield": 1.2, "debt_to_equity": 0.3})
    print(f"Fundamental Score: {result['score']}/100 (Grade: {result['grade']})")
    for k, v in result['breakdown'].items():
        print(f"  {k}: {v}")
    output = os.path.join(WORKSPACE, "fundamental_score.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
