#!/usr/bin/env python3
"""Task #2: MACD indicator calculator."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def ema(data, period):
    """Calculate Exponential Moving Average."""
    if len(data) < period:
        return []
    k = 2 / (period + 1)
    ema_values = [sum(data[:period]) / period]
    for price in data[period:]:
        ema_values.append(price * k + ema_values[-1] * (1 - k))
    return ema_values

def calculate_macd(prices, fast=12, slow=26, signal=9):
    """Calculate MACD line, signal line, and histogram."""
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    # Align lengths
    offset = slow - fast
    ema_fast_aligned = ema_fast[offset:]
    macd_line = [f - s for f, s in zip(ema_fast_aligned, ema_slow)]
    signal_line = ema(macd_line, signal)
    # Align MACD to signal
    macd_aligned = macd_line[signal-1:]
    histogram = [m - s for m, s in zip(macd_aligned, signal_line)]
    return {
        "macd_line": [round(x, 4) for x in macd_line],
        "signal_line": [round(x, 4) for x in signal_line],
        "histogram": [round(x, 4) for x in histogram],
        "latest": {
            "macd": round(macd_line[-1], 4),
            "signal": round(signal_line[-1], 4),
            "histogram": round(histogram[-1], 4),
            "bullish": histogram[-1] > 0
        }
    }

def detect_divergence(prices, macd_histogram):
    """Detect bullish and bearish divergences."""
    divergences = []
    if len(prices) < 20:
        return divergences
    for i in range(10, len(prices)):
        recent_prices = prices[i-10:i]
        recent_hist = macd_histogram[max(0,i-10):i]
        if not recent_hist:
            continue
        # Bullish divergence: price making lower low but MACD making higher low
        price_min_idx = recent_prices.index(min(recent_prices))
        hist_at_price_min = recent_hist[min(price_min_idx, len(recent_hist)-1)]
        hist_at_end = recent_hist[-1]
        if min(recent_prices) < prices[i-11] and hist_at_end > hist_at_price_min:
            divergences.append({"type": "bullish", "index": i, "strength": abs(hist_at_end - hist_at_price_min)})
        # Bearish divergence: price making higher high but MACD making lower high
        if max(recent_prices) > prices[i-11] and hist_at_end < hist_at_price_min:
            divergences.append({"type": "bearish", "index": i, "strength": abs(hist_at_end - hist_at_price_min)})
    return divergences

if __name__ == "__main__":
    import random
    # Generate sample price data
    prices = [100]
    for _ in range(99):
        prices.append(prices[-1] + random.uniform(-2, 2))
    result = calculate_macd(prices)
    divergences = detect_divergence(prices, result["histogram"])
    print(f"MACD: {result['latest']['macd']}")
    print(f"Signal: {result['latest']['signal']}")
    print(f"Histogram: {result['latest']['histogram']}")
    print(f"Bullish: {result['latest']['bullish']}")
    print(f"Divergences found: {len(divergences)}")
    # Save
    output = os.path.join(WORKSPACE, "macd_result.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
