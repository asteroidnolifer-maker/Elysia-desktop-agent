#!/usr/bin/env python3
"""Task #1458: Shipping cost calculator."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

RATES = {
    "ePacket": {"base": 0, "per_kg": 0.5, "days": "12-20"},
    "AliExpress Standard": {"base": 1, "per_kg": 1.5, "days": "15-25"},
    "DHL Express": {"base": 15, "per_kg": 5, "days": "5-10"},
    "FedEx International": {"base": 12, "per_kg": 4, "days": "5-12"},
    "UPS Worldwide": {"base": 10, "per_kg": 3.5, "days": "7-14"},
    "China Post": {"base": 0, "per_kg": 0.3, "days": "20-40"},
}

def calculate_shipping(weight_kg, destination="US"):
    """Calculate shipping costs for all methods."""
    results = []
    for method, rate in RATES.items():
        cost = rate["base"] + (rate["per_kg"] * weight_kg)
        results.append({"method": method, "cost": round(cost, 2), "delivery": rate["days"], "cost_per_kg": round(cost / weight_kg, 2) if weight_kg > 0 else 0})
    results.sort(key=lambda x: x["cost"])
    return {"weight_kg": weight_kg, "destination": destination, "options": results, "cheapest": results[0], "fastest": min(results, key=lambda x: int(x["delivery"].split("-")[0]))}

if __name__ == "__main__":
    result = calculate_shipping(0.5)
    print(f"Shipping Options ({result['weight_kg']}kg to {result['destination']}):")
    for o in result["options"]:
        print(f"  {o['method']}: ${o['cost']} ({o['delivery']} days)")
    output = os.path.join(WORKSPACE, "shipping_costs.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
