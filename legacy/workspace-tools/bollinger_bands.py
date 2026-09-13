#!/usr/bin/env python3
"""Task #4: Bollinger Bands signal detector."""
import json, os, math

WORKSPACE = "/data/elysia/workspace/tools"

def calculate_bollinger_bands(prices, period=20, std_dev=2):
    """Calculate Bollinger Bands."""
    if len(prices) < period:
        return {"error": "Not enough data"}
    sma = sum(prices[-period:]) / period
    variance = sum((p - sma) ** 2 for p in prices[-period:]) / period
    std = math.sqrt(variance)
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    bandwidth = ((upper - lower) / sma) * 100
    pct_b = (prices[-1] - lower) / (upper - lower) if (upper - lower) != 0 else 0.5
    return {
        "upper_band": round(upper, 2),
        "middle_band": round(sma, 2),
        "lower_band": round(lower, 2),
        "bandwidth": round(bandwidth, 2),
        "percent_b": round(pct_b, 4),
        "current_price": prices[-1],
        "squeeze": bandwidth < 5,
        "signal": "buy" if prices[-1] < lower else "sell" if prices[-1] > upper else "hold"
    }

def detect_squeeze(prices, period=20, lookback=10):
    """Detect Bollinger Band squeeze (low volatility)."""
    results = []
    for i in range(lookback, len(prices)):
        window = prices[i-lookback:i+1]
        sma = sum(window[-period:]) / period if len(window) >= period else sum(window) / len(window)
        variance = sum((p - sma) ** 2 for p in window[-period:]) / period if len(window) >= period else 0
        std = math.sqrt(variance)
        upper = sma + 2 * std
        lower = sma - 2 * std
        bw = ((upper - lower) / sma) * 100 if sma else 0
        results.append({"index": i, "bandwidth": round(bw, 2), "price": prices[i]})
    # Find squeeze periods (bandwidth below 5%)
    squeezes = [r for r in results if r["bandwidth"] < 5]
    return {"squeeze_periods": len(squeezes), "total_periods": len(results), "squeeze_ratio": len(squeezes)/len(results) if results else 0}

if __name__ == "__main__":
    import random
    prices = [100]
    for _ in range(99):
        prices.append(prices[-1] + random.uniform(-1.5, 1.5))
    result = calculate_bollinger_bands(prices)
    squeeze = detect_squeeze(prices)
    print(f"Upper: ${result['upper_band']}")
    print(f"Middle: ${result['middle_band']}")
    print(f"Lower: ${result['lower_band']}")
    print(f"Bandwidth: {result['bandwidth']}%")
    print(f"%B: {result['percent_b']}")
    print(f"Signal: {result['signal']}")
    print(f"Squeeze detected: {result['squeeze']}")
    output = os.path.join(WORKSPACE, "bollinger_result.json")
    with open(output, 'w') as f:
        json.dump({"bollinger": result, "squeeze_analysis": squeeze}, f, indent=2)
    print(f"[+] Saved to {output}")
