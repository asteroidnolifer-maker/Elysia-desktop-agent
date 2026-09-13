#!/usr/bin/env python3
"""Real-time crypto tracker using CoinGecko API."""
import requests
import json

def get_crypto_prices(coins=None):
    """Get real crypto prices from CoinGecko."""
    if coins is None:
        coins = ["bitcoin", "ethereum", "solana", "dogecoin", "cardano"]
    ids = ",".join(coins)
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true"
    try:
        r = requests.get(url, timeout=15)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def get_trending_coins():
    """Get trending coins from CoinGecko."""
    url = "https://api.coingecko.com/api/v3/search/trending"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        return [{"name": c["item"]["name"], "symbol": c["item"]["symbol"], "rank": c["item"]["market_cap_rank"]} for c in data.get("coins", [])]
    except Exception as e:
        return [{"error": str(e)}]

if __name__ == "__main__":
    print("=== Crypto Prices ===")
    prices = get_crypto_prices()
    for coin, data in prices.items():
        if isinstance(data, dict) and "usd" in data:
            change = data.get("usd_24h_change", 0)
            print(f"  {coin}: ${data['usd']:,.2f} ({change:+.1f}%)")
    print("\n=== Trending ===")
    for coin in get_trending_coins()[:5]:
        print(f"  {coin.get('symbol', '?')} - {coin.get('name', '?')} (rank #{coin.get('rank', '?')})")
