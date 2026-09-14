#!/usr/bin/env python3
"""Task #5: Stock screener with PE/market cap filters."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

SAMPLE_STOCKS = [
    {"symbol": "AAPL", "name": "Apple Inc.", "pe": 29.5, "market_cap": 2.78e12, "dividend_yield": 0.52, "sector": "Technology", "price": 178.50, "revenue_growth": 8.2, "profit_margin": 25.3},
    {"symbol": "MSFT", "name": "Microsoft Corp", "pe": 35.2, "market_cap": 2.81e12, "dividend_yield": 0.73, "sector": "Technology", "price": 378.90, "revenue_growth": 13.1, "profit_margin": 34.1},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "pe": 25.8, "market_cap": 1.78e12, "dividend_yield": 0, "sector": "Technology", "price": 141.20, "revenue_growth": 11.0, "profit_margin": 22.5},
    {"symbol": "AMZN", "name": "Amazon.com Inc.", "pe": 61.3, "market_cap": 1.85e12, "dividend_yield": 0, "sector": "Consumer Cyclical", "price": 178.30, "revenue_growth": 11.8, "profit_margin": 5.2},
    {"symbol": "NVDA", "name": "NVIDIA Corp", "pe": 65.4, "market_cap": 1.22e12, "dividend_yield": 0.03, "sector": "Technology", "price": 495.20, "revenue_growth": 122.0, "profit_margin": 55.3},
    {"symbol": "TSLA", "name": "Tesla Inc.", "pe": 72.1, "market_cap": 789e9, "dividend_yield": 0, "sector": "Consumer Cyclical", "price": 248.40, "revenue_growth": 18.7, "profit_margin": 15.4},
    {"symbol": "JPM", "name": "JPMorgan Chase", "pe": 11.2, "market_cap": 432e9, "dividend_yield": 2.45, "sector": "Financial", "price": 158.70, "revenue_growth": 21.3, "profit_margin": 32.8},
    {"symbol": "V", "name": "Visa Inc.", "pe": 30.5, "market_cap": 521e9, "dividend_yield": 0.75, "sector": "Financial", "price": 268.90, "revenue_growth": 9.4, "profit_margin": 50.2},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "pe": 15.8, "market_cap": 389e9, "dividend_yield": 2.95, "sector": "Healthcare", "price": 162.30, "revenue_growth": 3.8, "profit_margin": 18.7},
    {"symbol": "WMT", "name": "Walmart Inc.", "pe": 28.3, "market_cap": 421e9, "dividend_yield": 1.42, "sector": "Consumer Defensive", "price": 158.40, "revenue_growth": 5.7, "profit_margin": 2.8},
    {"symbol": "PG", "name": "Procter & Gamble", "pe": 25.6, "market_cap": 356e9, "dividend_yield": 2.42, "sector": "Consumer Defensive", "price": 150.80, "revenue_growth": 4.1, "profit_margin": 17.9},
    {"symbol": "MA", "name": "Mastercard Inc.", "pe": 33.8, "market_cap": 398e9, "dividend_yield": 0.52, "sector": "Financial", "price": 428.60, "revenue_growth": 12.8, "profit_margin": 46.3},
]

def screen_stocks(min_pe=None, max_pe=None, min_market_cap=None, max_market_cap=None,
                  min_dividend=None, min_growth=None, min_margin=None, sectors=None):
    """Filter stocks based on criteria."""
    results = SAMPLE_STOCKS
    if min_pe is not None:
        results = [s for s in results if s["pe"] >= min_pe]
    if max_pe is not None:
        results = [s for s in results if s["pe"] <= max_pe]
    if min_market_cap is not None:
        results = [s for s in results if s["market_cap"] >= min_market_cap]
    if max_market_cap is not None:
        results = [s for s in results if s["market_cap"] <= max_market_cap]
    if min_dividend is not None:
        results = [s for s in results if s["dividend_yield"] >= min_dividend]
    if min_growth is not None:
        results = [s for s in results if s["revenue_growth"] >= min_growth]
    if min_margin is not None:
        results = [s for s in results if s["profit_margin"] >= min_margin]
    if sectors:
        results = [s for s in results if s["sector"] in sectors]
    # Score and rank
    for s in results:
        s["score"] = (s["revenue_growth"] * 0.3 + s["profit_margin"] * 0.3 +
                     (1/s["pe"] * 100) * 0.2 + s["dividend_yield"] * 10 * 0.2)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

if __name__ == "__main__":
    # Screen for value stocks (low PE, high dividend)
    value = screen_stocks(max_pe=20, min_dividend=2.0)
    print("=== VALUE STOCKS ===")
    for s in value:
        print(f"  {s['symbol']}: PE={s['pe']}, Div={s['dividend_yield']}%, Cap=${s['market_cap']/1e9:.0f}B")
    # Screen for growth stocks (high revenue growth)
    growth = screen_stocks(min_growth=10, min_margin=15)
    print("\n=== GROWTH STOCKS ===")
    for s in growth:
        print(f"  {s['symbol']}: Growth={s['revenue_growth']}%, Margin={s['profit_margin']}%")
    output = os.path.join(WORKSPACE, "stock_screener_result.json")
    with open(output, 'w') as f:
        json.dump({"value_stocks": value, "growth_stocks": growth}, f, indent=2, default=str)
    print(f"\n[+] Saved to {output}")
