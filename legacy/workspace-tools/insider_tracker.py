#!/usr/bin/env python3
"""Task #15: Insider trading activity tracker."""
import json, os
from datetime import datetime, timedelta

WORKSPACE = "/data/elysia/workspace/tools"

def generate_insider_data():
    """Generate sample insider trading data."""
    import random
    insiders = ["Tim Cook", "Satya Nadella", "Sundar Pichai", "Andy Jassy", "Elon Musk"]
    transactions = []
    for _ in range(20):
        insider = random.choice(insiders)
        tx_type = random.choice(["Buy", "Sell"])
        shares = random.randint(1000, 100000)
        price = random.uniform(100, 400)
        transactions.append({
            "insider": insider,
            "type": tx_type,
            "shares": shares,
            "price": round(price, 2),
            "value": round(shares * price, 2),
            "date": (datetime.now() - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d"),
            "shares_owned": random.randint(50000, 5000000)
        })
    return transactions

def analyze_insider_activity(transactions):
    """Analyze insider trading patterns."""
    buys = [t for t in transactions if t["type"] == "Buy"]
    sells = [t for t in transactions if t["type"] == "Sell"]
    buy_value = sum(t["value"] for t in buys)
    sell_value = sum(t["value"] for t in sells)
    signal = "bullish" if buy_value > sell_value * 1.5 else "bearish" if sell_value > buy_value * 1.5 else "neutral"
    return {
        "total_transactions": len(transactions),
        "buys": len(buys),
        "sells": len(sells),
        "total_buy_value": round(buy_value, 2),
        "total_sell_value": round(sell_value, 2),
        "buy_sell_ratio": round(buy_value / sell_value, 2) if sell_value > 0 else float('inf'),
        "signal": signal,
        "cluster_buying": len(buys) > len(sells) * 2,
        "cluster_selling": len(sells) > len(buys) * 2,
        "recent_transactions": sorted(transactions, key=lambda x: x["date"], reverse=True)[:5]
    }

if __name__ == "__main__":
    transactions = generate_insider_data()
    result = analyze_insider_activity(transactions)
    print("Insider Trading Activity:")
    print(f"  Transactions: {result['total_transactions']}")
    print(f"  Buys: {result['buys']} (${result['total_buy_value']:,.0f})")
    print(f"  Sells: {result['sells']} (${result['total_sell_value']:,.0f})")
    print(f"  Signal: {result['signal']}")
    print(f"  Cluster Buying: {result['cluster_buying']}")
    output = os.path.join(WORKSPACE, "insider_trading.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
