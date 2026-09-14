#!/usr/bin/env python3
"""Task #12: Stock momentum scoring system."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def calculate_momentum_score(prices, volumes=None):
    """Calculate composite momentum score (0-100)."""
    if len(prices) < 60:
        return {"error": "Need at least 60 data points"}
    # Rate of Change (ROC) - 1 month
    roc_1m = (prices[-1] - prices[-21]) / prices[-21] * 100 if len(prices) > 21 else 0
    # ROC - 3 months
    roc_3m = (prices[-1] - prices[-63]) / prices[-63] * 100 if len(prices) > 63 else 0
    # ROC - 6 months
    roc_6m = (prices[-1] - prices[-126]) / prices[-126] * 100 if len(prices) > 126 else roc_3m
    # ROC - 12 months
    roc_12m = (prices[-1] - prices[-252]) / prices[-252] * 100 if len(prices) > 252 else roc_6m
    # Moving average position
    sma20 = sum(prices[-20:]) / 20
    sma50 = sum(prices[-50:]) / 50
    ma_score = 0
    if prices[-1] > sma20:
        ma_score += 25
    if prices[-1] > sma50:
        ma_score += 25
    if sma20 > sma50:
        ma_score += 25
    # New highs/lows
    high_52w = max(prices[-252:]) if len(prices) > 252 else max(prices)
    low_52w = min(prices[-252:]) if len(prices) > 252 else min(prices)
    range_pos = (prices[-1] - low_52w) / (high_52w - low_52w) * 100 if (high_52w - low_52w) > 0 else 50
    # Composite score
    score = (roc_1m * 0.3 + roc_3m * 0.25 + roc_6m * 0.2 + roc_12m * 0.15 + range_pos * 0.1)
    score = max(0, min(100, score + 50))  # Normalize to 0-100
    strength = "very_strong" if score > 80 else "strong" if score > 60 else "neutral" if score > 40 else "weak" if score > 20 else "very_weak"
    return {
        "score": round(score, 1),
        "strength": strength,
        "roc_1m": round(roc_1m, 2),
        "roc_3m": round(roc_3m, 2),
        "roc_6m": round(roc_6m, 2),
        "roc_12m": round(roc_12m, 2),
        "ma_score": ma_score,
        "range_position": round(range_pos, 1),
        "above_sma20": prices[-1] > sma20,
        "above_sma50": prices[-1] > sma50,
        "sma20_above_sma50": sma20 > sma50,
        "near_52w_high": range_pos > 90,
        "near_52w_low": range_pos < 10,
    }

if __name__ == "__main__":
    import random
    prices = [100]
    for _ in range(251):
        prices.append(prices[-1] * (1 + random.uniform(-0.03, 0.03)))
    result = calculate_momentum_score(prices)
    print("Momentum Score Analysis:")
    print(f"  Score: {result['score']}/100 ({result['strength']})")
    print(f"  ROC 1M: {result['roc_1m']}%")
    print(f"  ROC 3M: {result['roc_3m']}%")
    print(f"  ROC 6M: {result['roc_6m']}%")
    print(f"  ROC 12M: {result['roc_12m']}%")
    print(f"  Above SMA20: {result['above_sma20']}")
    print(f"  Above SMA50: {result['above_sma50']}")
    print(f"  Near 52W High: {result['near_52w_high']}")
    output = os.path.join(WORKSPACE, "momentum_score.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
