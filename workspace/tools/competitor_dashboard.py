#!/usr/bin/env python3
"""Task #1464: Competitor tracking dashboard."""
import json, os, random
from datetime import datetime

WORKSPACE = "/data/elysia/workspace/tools"

def generate_dashboard_data():
    """Generate competitor tracking data."""
    competitors = [
        {"name": "CompetitorA", "traffic_rank": 1523, "social_followers": 45000, "price_index": 92, "ad_spend_est": 12000, "growth": 8.5},
        {"name": "CompetitorB", "traffic_rank": 3200, "social_followers": 28000, "price_index": 88, "ad_spend_est": 8500, "growth": 3.2},
        {"name": "CompetitorC", "traffic_rank": 890, "social_followers": 92000, "price_index": 95, "ad_spend_est": 22000, "growth": 15.1},
        {"name": "CompetitorD", "traffic_rank": 5100, "social_followers": 12000, "price_index": 78, "ad_spend_est": 4200, "growth": -2.1},
        {"name": "CompetitorE", "traffic_rank": 2100, "social_followers": 67000, "price_index": 91, "ad_spend_est": 15800, "growth": 6.8},
    ]
    alerts = []
    for c in competitors:
        if c["growth"] > 10:
            alerts.append({"competitor": c["name"], "type": "high_growth", "message": f"{c['name']} growing at {c['growth']}% - monitor pricing"})
        if c["ad_spend_est"] > 20000:
            alerts.append({"competitor": c["name"], "type": "high_ad_spend", "message": f"{c['name']} increasing ad spend to ${c['ad_spend_est']:,}"})
    return {"competitors": sorted(competitors, key=lambda x: x["traffic_rank"]), "alerts": alerts, "last_updated": datetime.now().isoformat()}

if __name__ == "__main__":
    result = generate_dashboard_data()
    print("Competitor Dashboard:")
    for c in result["competitors"]:
        print(f"  #{c['traffic_rank']} {c['name']}: {c['growth']}% growth, ${c['ad_spend_est']:,} ad spend")
    if result["alerts"]:
        print("\nAlerts:")
        for a in result["alerts"]:
            print(f"  {a['type']}: {a['message']}")
    output = os.path.join(WORKSPACE, "competitor_dashboard.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
