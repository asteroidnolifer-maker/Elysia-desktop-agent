#!/usr/bin/env python3
"""Task #25: Dollar-cost averaging simulator."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def simulate_dca(prices, monthly_investment=1000, months=None):
    """Simulate dollar-cost averaging."""
    if months is None:
        months = len(prices)
    total_invested = 0
    total_shares = 0
    history = []
    for i in range(min(months, len(prices))):
        price = prices[i]
        shares = monthly_investment / price
        total_invested += monthly_investment
        total_shares += shares
        avg_cost = total_invested / total_shares
        history.append({
            "month": i + 1,
            "price": round(price, 2),
            "shares_bought": round(shares, 4),
            "total_shares": round(total_shares, 4),
            "total_invested": total_invested,
            "portfolio_value": round(total_shares * price, 2),
            "avg_cost": round(avg_cost, 2),
            "gain_loss_pct": round((total_shares * price - total_invested) / total_invested * 100, 2)
        })
    final_value = total_shares * prices[min(months-1, len(prices)-1)]
    return {
        "total_invested": total_invested,
        "total_shares": round(total_shares, 4),
        "final_value": round(final_value, 2),
        "total_return": round(final_value - total_invested, 2),
        "return_pct": round((final_value - total_invested) / total_invested * 100, 2),
        "avg_cost_per_share": round(total_invested / total_shares, 2),
        "history": history
    }

if __name__ == "__main__":
    import random
    prices = [100 + random.uniform(-20, 30) for _ in range(24)]
    result = simulate_dca(prices, 500, 24)
    print("DCA Simulation (24 months, $500/month):")
    print(f"  Total Invested: ${result['total_invested']:,.0f}")
    print(f"  Total Shares: {result['total_shares']:.4f}")
    print(f"  Final Value: ${result['final_value']:,.2f}")
    print(f"  Return: {result['return_pct']}%")
    print(f"  Avg Cost: ${result['avg_cost_per_share']}")
    output = os.path.join(WORKSPACE, "dca_simulator.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
