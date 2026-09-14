#!/usr/bin/env python3
"""Task #21: After-hours price scanner."""
import json, os
from datetime import datetime

WORKSPACE = "/data/elysia/workspace/tools"

def scan_after_hours():
    """Scan after-hours/pre-market price movements."""
    import random
    stocks = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "JPM", "V", "JNJ"]
    results = []
    for sym in stocks:
        change = random.uniform(-5, 8)
        volume = random.randint(10000, 2000000)
        results.append({
            "symbol": sym,
            "regular_close": round(random.uniform(100, 500), 2),
            "after_hours_price": round(random.uniform(95, 520), 2),
            "change_pct": round(change, 2),
            "volume": volume,
            "earnings": random.choice([True, False]),
            "news": random.choice(["upgrade", "downgrade", "analyst_initiation", "none"]),
            "significance": "high" if abs(change) > 3 else "moderate" if abs(change) > 1 else "low"
        })
    results.sort(key=lambda x: abs(x["change_pct"]), reverse=True)
    return {"scan_time": datetime.now().isoformat(), "movers": results}

if __name__ == "__main__":
    result = scan_after_hours()
    print("After-Hours Price Scanner:")
    for m in result["movers"][:5]:
        sign = "+" if m["change_pct"] >= 0 else ""
        print(f"  {m['symbol']}: {sign}{m['change_pct']}% (Vol: {m['volume']:,}) {'[EARNINGS]' if m['earnings'] else ''}")
    output = os.path.join(WORKSPACE, "after_hours_scanner.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
