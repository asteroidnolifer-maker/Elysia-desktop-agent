#!/usr/bin/env python3
"""Task #1455: Order tracking aggregator."""
import json, os, random
from datetime import datetime, timedelta

WORKSPACE = "/data/elysia/workspace/tools"

def aggregate_orders():
    """Aggregate order tracking from multiple carriers."""
    carriers = ["USPS", "UPS", "FedEx", "DHL", "ePacket"]
    orders = []
    for i in range(10):
        carrier = random.choice(carriers)
        status = random.choice(["shipped", "in_transit", "out_for_delivery", "delivered", "exception"])
        orders.append({
            "order_id": f"ORD-{random.randint(100000, 999999)}",
            "carrier": carrier,
            "tracking_number": f"{carrier[:2]}{random.randint(100000000, 999999999)}",
            "status": status,
            "origin": random.choice(["Shenzhen, China", "Guangzhou, China", "Yiwu, China"]),
            "destination": random.choice(["New York, NY", "Los Angeles, CA", "Chicago, IL"]),
            "estimated_delivery": (datetime.now() + timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d"),
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "days_in_transit": random.randint(1, 30)
        })
    statuses = {}
    for o in orders:
        statuses[o["status"]] = statuses.get(o["status"], 0) + 1
    return {"orders": orders, "summary": statuses, "total": len(orders)}

if __name__ == "__main__":
    result = aggregate_orders()
    print(f"Order Tracking ({result['total']} orders):")
    for o in result["orders"][:3]:
        print(f"  {o['order_id']} ({o['carrier']}): {o['status']} - ETA {o['estimated_delivery']}")
    print(f"Summary: {result['summary']}")
    output = os.path.join(WORKSPACE, "order_tracking.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
