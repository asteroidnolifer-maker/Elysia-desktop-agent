#!/usr/bin/env python3
"""Task #1459: Inventory sync tool."""
import json, os, random

WORKSPACE = "/data/elysia/workspace/tools"

def sync_inventory(stores, supplier_stock):
    """Sync inventory levels across multiple stores."""
    sync_log = []
    for store in stores:
        for sku, qty in supplier_stock.items():
            current = store["inventory"].get(sku, 0)
            if current != qty:
                sync_log.append({"store": store["name"], "sku": sku, "old": current, "new": qty, "action": "updated"})
                store["inventory"][sku] = qty
    return {"stores_synced": len(stores), "updates": len(sync_log), "log": sync_log[:10]}

if __name__ == "__main__":
    stores = [{"name": "Shopify", "inventory": {"SKU1": 10, "SKU2": 5}}, {"name": "Amazon", "inventory": {"SKU1": 8, "SKU2": 7}}]
    supplier = {"SKU1": 15, "SKU2": 12, "SKU3": 20}
    result = sync_inventory(stores, supplier)
    print(f"Synced {result['stores_synced']} stores, {result['updates']} updates")
    for log in result["log"]:
        print(f"  {log['store']}: {log['sku']} {log['old']} -> {log['new']}")
    output = os.path.join(WORKSPACE, "inventory_sync.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
