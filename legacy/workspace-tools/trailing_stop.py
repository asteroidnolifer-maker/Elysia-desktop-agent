#!/usr/bin/env python3
"""Task #28: Trailing stop-loss calculator."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def calculate_trailing_stop(entry_price, highest_price, trail_pct=5):
    """Calculate trailing stop-loss level."""
    stop_price = highest_price * (1 - trail_pct / 100)
    risk = entry_price - stop_price
    risk_pct = risk / entry_price * 100
    return {
        "entry_price": entry_price,
        "highest_price": highest_price,
        "trail_pct": trail_pct,
        "stop_price": round(stop_price, 2),
        "risk_per_share": round(risk, 2),
        "risk_pct": round(risk_pct, 2),
        "protected_gain": round(highest_price - entry_price, 2),
        "protected_gain_pct": round((highest_price - entry_price) / entry_price * 100, 2),
        "status": "profit_protected" if stop_price > entry_price else "loss_limited"
    }

def optimize_trail_pct(prices, test_range=range(2, 15)):
    """Find optimal trailing stop percentage."""
    results = []
    for pct in test_range:
        capital = 10000
        shares = 0
        entry = 0
        peak = 0
        for p in prices:
            if shares == 0:
                shares = int(capital / p)
                entry = p
                peak = p
                capital -= shares * p
            else:
                peak = max(peak, p)
                stop = peak * (1 - pct / 100)
                if p <= stop:
                    capital += shares * p
                    shares = 0
        if shares > 0:
            capital += shares * prices[-1]
        ret = (capital - 10000) / 10000 * 100
        results.append({"trail_pct": pct, "return_pct": round(ret, 2)})
    best = max(results, key=lambda x: x["return_pct"])
    return {"results": results, "optimal": best}

if __name__ == "__main__":
    result = calculate_trailing_stop(100, 120, 5)
    print("Trailing Stop-Loss:")
    print(f"  Entry: ${result['entry_price']}")
    print(f"  Highest: ${result['highest_price']}")
    print(f"  Stop: ${result['stop_price']} ({result['trail_pct']}% trail)")
    print(f"  Protected Gain: ${result['protected_gain']} ({result['protected_gain_pct']}%)")
    import random
    prices = [100 + random.uniform(-10, 25) for _ in range(60)]
    opt = optimize_trail_pct(prices)
    print(f"\nOptimal Trail: {opt['optimal']['trail_pct']}% ({opt['optimal']['return_pct']}% return)")
    output = os.path.join(WORKSPACE, "trailing_stop.json")
    with open(output, 'w') as f:
        json.dump({"stop": result, "optimization": opt}, f, indent=2)
    print(f"[+] Saved to {output}")
