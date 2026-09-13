#!/usr/bin/env python3
"""Task #19: Arbitrage scanner."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def scan_arbitrage(exchanges_data):
    """Scan for price arbitrage opportunities across exchanges."""
    opportunities = []
    symbols = set()
    for ex in exchanges_data:
        symbols.update(ex["prices"].keys())
    for symbol in symbols:
        prices = {}
        for ex in exchanges_data:
            if symbol in ex["prices"]:
                prices[ex["name"]] = ex["prices"][symbol]
        if len(prices) < 2:
            continue
        min_ex = min(prices, key=prices.get)
        max_ex = max(prices, key=prices.get)
        spread = prices[max_ex] - prices[min_ex]
        spread_pct = (spread / prices[min_ex]) * 100
        if spread_pct > 0.5:
            opportunities.append({
                "symbol": symbol,
                "buy_exchange": min_ex,
                "buy_price": prices[min_ex],
                "sell_exchange": max_ex,
                "sell_price": prices[max_ex],
                "spread": round(spread, 4),
                "spread_pct": round(spread_pct, 2),
                "estimated_profit_per_1000": round(1000 * spread_pct / 100, 2)
            })
    opportunities.sort(key=lambda x: x["spread_pct"], reverse=True)
    return opportunities

if __name__ == "__main__":
    exchanges = [
        {"name": "Binance", "prices": {"BTC": 43250.50, "ETH": 2280.30, "SOL": 98.75}},
        {"name": "Coinbase", "prices": {"BTC": 43380.20, "ETH": 2295.10, "SOL": 99.20}},
        {"name": "Kraken", "prices": {"BTC": 43180.90, "ETH": 2270.40, "SOL": 98.10}},
    ]
    result = scan_arbitrage(exchanges)
    print("Arbitrage Opportunities:")
    for opp in result:
        print(f"  {opp['symbol']}: Buy@{opp['buy_exchange']} ${opp['buy_price']} -> Sell@{opp['sell_exchange']} ${opp['sell_price']} ({opp['spread_pct']}%)")
    output = os.path.join(WORKSPACE, "arbitrage_scanner.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
