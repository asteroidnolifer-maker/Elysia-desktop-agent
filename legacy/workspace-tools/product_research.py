#!/usr/bin/env python3
"""Task #1451: Product research tool with profit calculator (Dropshipping)."""
import json, os, random

WORKSPACE = "/data/elysia/workspace/tools"

def research_product(niche=None):
    """Research product opportunity with profit analysis."""
    products = [
        {"name": "Wireless Earbuds Pro", "category": "Electronics", "supplier_price": 8.50, "shipping": 2.00, "competitor_price": 29.99, "demand_score": 85, "competition": "high"},
        {"name": "Posture Corrector Belt", "category": "Health", "supplier_price": 4.20, "shipping": 1.50, "competitor_price": 24.99, "demand_score": 78, "competition": "medium"},
        {"name": "LED Strip Lights 10m", "category": "Home", "supplier_price": 6.80, "shipping": 3.00, "competitor_price": 19.99, "demand_score": 92, "competition": "high"},
        {"name": "Magnetic Phone Mount", "category": "Auto", "supplier_price": 3.50, "shipping": 1.80, "competitor_price": 15.99, "demand_score": 71, "competition": "medium"},
        {"name": "Resistance Bands Set", "category": "Fitness", "supplier_price": 5.20, "shipping": 2.20, "competitor_price": 22.99, "demand_score": 88, "competition": "medium"},
        {"name": "Bamboo Cutting Board", "category": "Kitchen", "supplier_price": 7.80, "shipping": 4.00, "competitor_price": 28.99, "demand_score": 65, "competition": "low"},
        {"name": "Yoga Mat Premium", "category": "Fitness", "supplier_price": 9.50, "shipping": 5.00, "competitor_price": 34.99, "demand_score": 82, "competition": "high"},
        {"name": "Smart Water Bottle", "category": "Health", "supplier_price": 12.00, "shipping": 3.50, "competitor_price": 39.99, "demand_score": 74, "competition": "low"},
    ]
    if niche:
        products = [p for p in products if niche.lower() in p["category"].lower()] or products
    results = []
    for p in products:
        total_cost = p["supplier_price"] + p["shipping"]
        profit = p["competitor_price"] - total_cost
        margin = (profit / p["competitor_price"]) * 100
        ad_cost = p["competitor_price"] * 0.3  # 30% ad spend estimate
        net_profit = profit - ad_cost
        roi = (net_profit / total_cost) * 100
        results.append({
            **p,
            "total_cost": round(total_cost, 2),
            "gross_profit": round(profit, 2),
            "gross_margin": round(margin, 1),
            "ad_cost_estimate": round(ad_cost, 2),
            "net_profit_after_ads": round(net_profit, 2),
            "roi": round(roi, 1),
            "score": round(p["demand_score"] * 0.4 + margin * 0.3 + (100 if p["competition"] == "low" else 60 if p["competition"] == "medium" else 30) * 0.3, 1),
            "verdict": "WINNING" if margin > 60 and p["demand_score"] > 75 else "GOOD" if margin > 40 else "AVOID"
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"products": results, "best_opportunity": results[0] if results else None}

if __name__ == "__main__":
    result = research_product()
    print("Product Research Results:")
    for p in result["products"]:
        print(f"\n  {p['name']} ({p['category']})")
        print(f"    Cost: ${p['total_cost']} | Price: ${p['competitor_price']} | Profit: ${p['gross_profit']} ({p['gross_margin']}%)")
        print(f"    After Ads: ${p['net_profit_after_ads']} | ROI: {p['roi']}% | Score: {p['score']}")
        print(f"    Verdict: {p['verdict']}")
    output = os.path.join(WORKSPACE, "product_research.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"\n[+] Saved to {output}")
