#!/usr/bin/env python3
"""Task #20: Stock split/dividend tracker."""
import json, os
from datetime import datetime, timedelta

WORKSPACE = "/data/elysia/workspace/tools"

def generate_corporate_actions():
    """Generate sample corporate actions data."""
    import random
    actions = []
    for _ in range(15):
        action_type = random.choice(["split", "dividend", "special_dividend"])
        if action_type == "split":
            ratio = random.choice(["2:1", "3:1", "4:1", "10:1"])
            actions.append({
                "type": "stock_split",
                "ratio": ratio,
                "announcement_date": (datetime.now() - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d"),
                "effective_date": (datetime.now() + timedelta(days=random.randint(5, 60))).strftime("%Y-%m-%d"),
                "price_impact": f"~{1/int(ratio.split(':')[0])*100:.0f}% price decrease expected"
            })
        else:
            amount = round(random.uniform(0.5, 5.0), 2)
            actions.append({
                "type": action_type,
                "amount": amount,
                "ex_date": (datetime.now() + timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d"),
                "payment_date": (datetime.now() + timedelta(days=random.randint(30, 60))).strftime("%Y-%m-%d"),
                "yield": round(amount / random.uniform(50, 200) * 100, 2)
            })
    return actions

def analyze_dividend_sustainability(dividend_history, earnings_history):
    """Analyze if dividend is sustainable."""
    if not dividend_history or not earnings_history:
        return {"sustainable": "insufficient_data"}
    latest_div = dividend_history[-1]
    latest_eps = earnings_history[-1]
    payout_ratio = latest_div / latest_eps if latest_eps > 0 else float('inf')
    div_growth = [(dividend_history[i] - dividend_history[i-1]) / dividend_history[i-1] * 100
                  for i in range(1, len(dividend_history))]
    return {
        "current_yield": round(latest_div / (latest_eps / (payout_ratio if payout_ratio > 0 else 1)) * 100, 2),
        "payout_ratio": round(payout_ratio * 100, 1),
        "sustainable": payout_ratio < 0.75,
        "dividend_growth_rate": round(sum(div_growth) / len(div_growth), 2) if div_growth else 0,
        "years_of_growth": sum(1 for g in div_growth if g > 0),
        "risk_level": "low" if payout_ratio < 0.5 else "moderate" if payout_ratio < 0.75 else "high"
    }

if __name__ == "__main__":
    actions = generate_corporate_actions()
    import random
    div_hist = [1.50, 1.60, 1.70, 1.80, 1.90, 2.00]
    eps_hist = [5.00, 5.50, 6.00, 6.20, 6.50, 7.00]
    sustainability = analyze_dividend_sustainability(div_hist, eps_hist)
    print("Corporate Actions:")
    for a in actions[:5]:
        print(f"  {a['type']}: {a.get('ratio', '')} {a.get('amount', '')} - {a.get('announcement_date', a.get('ex_date', ''))}")
    print(f"\nDividend Sustainability:")
    print(f"  Payout Ratio: {sustainability['payout_ratio']}%")
    print(f"  Sustainable: {sustainability['sustainable']}")
    print(f"  Risk: {sustainability['risk_level']}")
    output = os.path.join(WORKSPACE, "corporate_actions.json")
    with open(output, 'w') as f:
        json.dump({"actions": actions, "dividend_analysis": sustainability}, f, indent=2)
    print(f"[+] Saved to {output}")
