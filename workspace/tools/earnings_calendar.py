#!/usr/bin/env python3
"""Task #9: Earnings calendar scraper."""
import json, os
from datetime import datetime, timedelta

WORKSPACE = "/data/elysia/workspace/tools"

def get_earnings_calendar():
    """Get upcoming earnings dates (simulated, replace with real API)."""
    import random
    companies = [
        {"symbol": "AAPL", "name": "Apple Inc.", "sector": "Technology"},
        {"symbol": "MSFT", "name": "Microsoft Corp", "sector": "Technology"},
        {"symbol": "GOOGL", "name": "Alphabet Inc.", "sector": "Technology"},
        {"symbol": "AMZN", "name": "Amazon.com Inc.", "sector": "Consumer Cyclical"},
        {"symbol": "TSLA", "name": "Tesla Inc.", "sector": "Consumer Cyclical"},
        {"symbol": "NVDA", "name": "NVIDIA Corp", "sector": "Technology"},
        {"symbol": "META", "name": "Meta Platforms", "sector": "Technology"},
        {"symbol": "JPM", "name": "JPMorgan Chase", "sector": "Financial"},
        {"symbol": "V", "name": "Visa Inc.", "sector": "Financial"},
        {"symbol": "JNJ", "name": "Johnson & Johnson", "sector": "Healthcare"},
    ]
    calendar = []
    now = datetime.now()
    for c in companies:
        days_ahead = random.randint(1, 60)
        date = now + timedelta(days=days_ahead)
        eps_estimate = round(random.uniform(0.5, 5.0), 2)
        revenue_estimate = round(random.uniform(10, 100), 2)
        calendar.append({
            **c,
            "date": date.strftime("%Y-%m-%d"),
            "time": random.choice(["before_open", "after_close"]),
            "eps_estimate": eps_estimate,
            "revenue_estimate_b": revenue_estimate,
            "days_until": days_ahead,
            "importance": "high" if c["symbol"] in ["AAPL", "MSFT", "GOOGL", "AMZN"] else "medium"
        })
    calendar.sort(key=lambda x: x["date"])
    return calendar

def analyze_earnings_surprise(actual, estimate):
    """Calculate earnings surprise and market impact prediction."""
    surprise_pct = ((actual - estimate) / abs(estimate)) * 100 if estimate != 0 else 0
    return {
        "actual": actual,
        "estimate": estimate,
        "surprise_pct": round(surprise_pct, 2),
        "beat": actual > estimate,
        "magnitude": "large" if abs(surprise_pct) > 10 else "moderate" if abs(surprise_pct) > 5 else "small"
    }

if __name__ == "__main__":
    calendar = get_earnings_calendar()
    print("Upcoming Earnings:")
    for c in calendar:
        print(f"  {c['date']} {c['time']:>12} {c['symbol']:>6} - EPS Est: ${c['eps_estimate']}, Rev Est: ${c['revenue_estimate_b']}B")
    surprise = analyze_earnings_surprise(2.18, 1.95)
    print(f"\nEarnings Surprise Example:")
    print(f"  Actual: ${surprise['actual']}, Estimate: ${surprise['estimate']}")
    print(f"  Surprise: {surprise['surprise_pct']}% ({'Beat' if surprise['beat'] else 'Miss'})")
    output = os.path.join(WORKSPACE, "earnings_calendar.json")
    with open(output, 'w') as f:
        json.dump({"calendar": calendar, "surprise_example": surprise}, f, indent=2)
    print(f"[+] Saved to {output}")
