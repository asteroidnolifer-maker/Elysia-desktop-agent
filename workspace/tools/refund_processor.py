#!/usr/bin/env python3
"""Task #1461: Automated refund processor."""
import json, os, random
from datetime import datetime, timedelta

WORKSPACE = "/data/elysia/workspace/tools"

def process_refunds(orders):
    """Process refund requests automatically."""
    results = []
    for order in orders:
        eligible = order["days_since_delivery"] <= 30
        refund_amount = order["amount"] if eligible else 0
        results.append({
            "order_id": order["id"],
            "amount": order["amount"],
            "eligible": eligible,
            "refund_amount": refund_amount,
            "reason": order["reason"],
            "auto_approved": eligible and order["amount"] < 50,
            "status": "refunded" if eligible else "denied",
            "processing_time": "immediate" if eligible else "manual_review"
        })
    approved = sum(1 for r in results if r["auto_approved"])
    total_refunded = sum(r["refund_amount"] for r in results)
    return {"processed": len(results), "approved": approved, "total_refunded": round(total_refunded, 2), "results": results}

if __name__ == "__main__":
    orders = [{"id": f"ORD-{i}", "amount": round(random.uniform(5, 100), 2), "days_since_delivery": random.randint(1, 60), "reason": random.choice(["defective", "wrong_item", "not_as_described", "changed_mind"])} for i in range(10)]
    result = process_refunds(orders)
    print(f"Processed {result['processed']} refunds, {result['approved']} auto-approved, ${result['total_refunded']} refunded")
    output = os.path.join(WORKSPACE, "refund_processor.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
