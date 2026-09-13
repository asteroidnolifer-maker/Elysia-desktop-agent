#!/usr/bin/env python3
"""Real stock trading research - fetches actual market data."""
import requests
import json
import os
import re
from bs4 import BeautifulSoup

WORKSPACE = "/data/elysia/workspace/tools"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def get_stock_price(ticker):
    """Get real stock price from Google Finance."""
    url = f"https://www.google.com/finance/quote/{ticker}:NASDAQ"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "lxml")
        price_el = soup.select_one("divYMlKec")
        change_el = soup.select_one("divJbUci")
        name_el = soup.select_one("divZZZ7wf")
        price = price_el.text.strip() if price_el else "N/A"
        change = change_el.text.strip() if change_el else "N/A"
        name = name_el.text.strip() if name_el else ticker
        return {"ticker": ticker, "name": name, "price": price, "change": change, "source": "google_finance"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_stock_news(ticker):
    """Get real news about a stock."""
    from web_research import search_google
    result = search_google(f"{ticker} stock news today", 5)
    return {"ticker": ticker, "news": result.get("results", [])}


def analyze_stock(ticker):
    """Full stock analysis with real data."""
    price_data = get_stock_price(ticker)
    news_data = get_stock_news(ticker)
    return {"ticker": ticker, "price_data": price_data, "news": news_data["news"][:3], "analyzed_at": __import__("datetime").datetime.now().isoformat()}


if __name__ == "__main__":
    print("=== Real Stock Research ===")
    for ticker in ["AAPL", "GOOGL", "NVDA"]:
        result = analyze_stock(ticker)
        print(f"\n{result['ticker']}:")
        print(f"  Price: {result['price_data'].get('price', 'N/A')}")
        print(f"  Change: {result['price_data'].get('change', 'N/A')}")
        for n in result['news'][:2]:
            print(f"  News: {n['title'][:60]}")
    output = os.path.join(WORKSPACE, "stock_analysis.json")
    with open(output, "w") as f:
        json.dump({"stocks": [analyze_stock(t) for t in ["AAPL", "GOOGL", "NVDA"]]}, f, indent=2, default=str)
    print(f"\n[+] Saved to {output}")
