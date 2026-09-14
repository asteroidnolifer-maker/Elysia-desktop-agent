#!/usr/bin/env python3
"""Task #1454: Competitor price monitor."""
import json, os, random

WORKSPACE = "/data/elysia/workspace/tools"

def monitor_prices(products):
    """Monitor competitor prices and alert on changes."""
    alerts = []
    for p in products:
        current = p["current_price"]
        previous = p["previous_price"]
        change = ((current - previous) / previous) * 100
        if abs(change) > 5:
            alerts.append({
                "product": p["name"],
                "previous": previous,
                "current": current,
                "change_pct": round(change, 1),
                "alert_type": "price_drop" if change < 0 else "price_increase",
                "action": "match_price" if change < 0 else "review_pricing"
            })
    return {"products_monitored": len(products), "alerts": alerts, "alert_count": len(alerts)}

if __name__ == "__main__":
    products = [{"name": f"Product {i}", "current_price": round(random.uniform(10, 50), 2), "previous_price": round(random.uniform(10, 50), 2)} for i in range(10)]
    result = monitor_prices(products)
    print(f"Monitoring {result['products_monitored']} products, {result['alert_count']} alerts")
    for a in result["alerts"]:
        print(f"  {a['alert_type']}: {a['product']} ${a['previous']} -> ${a['current']} ({a['change_pct']}%)")
    output = os.path.join(WORKSPACE, "price_monitor.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
