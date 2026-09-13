#!/usr/bin/env python3
"""Task #6: Moving average crossover signal generator."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def calculate_sma(prices, period):
    """Simple Moving Average."""
    return [sum(prices[i-period+1:i+1])/period for i in range(period-1, len(prices))]

def calculate_ema(prices, period):
    """Exponential Moving Average."""
    k = 2/(period+1)
    ema = [sum(prices[:period])/period]
    for p in prices[period:]:
        ema.append(p*k + ema[-1]*(1-k))
    return ema

def detect_crossovers(fast, slow, labels=("fast", "slow")):
    """Detect golden cross and death cross."""
    signals = []
    # Align from the end - fast and slow may have different lengths
    n = min(len(fast), len(slow))
    for i in range(1, n):
        f_curr = fast[len(fast)-n+i]
        f_prev = fast[len(fast)-n+i-1]
        s_curr = slow[len(slow)-n+i]
        s_prev = slow[len(slow)-n+i-1]
        prev_diff = f_prev - s_prev
        curr_diff = f_curr - s_curr
        if prev_diff <= 0 and curr_diff > 0:
            signals.append({"type": "golden_cross", "fast": labels[0], "slow": labels[1], "strength": abs(curr_diff)})
        elif prev_diff >= 0 and curr_diff < 0:
            signals.append({"type": "death_cross", "fast": labels[0], "slow": labels[1], "strength": abs(curr_diff)})
    return signals

def full_ma_analysis(prices):
    """Complete MA crossover analysis with multiple timeframes."""
    results = {}
    pairs = [(5, 20), (10, 30), (20, 50), (50, 200)]
    all_signals = []
    for fast_p, slow_p in pairs:
        fast = calculate_sma(prices, fast_p)
        slow = calculate_sma(prices, slow_p)
        if not fast or not slow:
            continue
        signals = detect_crossovers(fast, slow, (f"SMA{fast_p}", f"SMA{slow_p}"))
        results[f"{fast_p}/{slow_p}"] = {
            "fast_ma": round(fast[-1], 2),
            "slow_ma": round(slow[-1], 2),
            "trend": "bullish" if fast[-1] > slow[-1] else "bearish",
            "spread": round(abs(fast[-1] - slow[-1]), 2),
            "signals": len(signals)
        }
        all_signals.extend(signals)
    # EMA crossover
    ema12 = calculate_ema(prices, 12)
    ema26 = calculate_ema(prices, 26)
    ema_signals = detect_crossovers(ema12, ema26, ("EMA12", "EMA26"))
    all_signals.extend(ema_signals)
    return {"moving_averages": results, "total_signals": len(all_signals), "recent_signals": all_signals[-5:]}

if __name__ == "__main__":
    import random
    prices = [100]
    for _ in range(249):
        prices.append(prices[-1] + random.uniform(-2, 2))
    result = full_ma_analysis(prices)
    print("Moving Average Analysis:")
    for pair, info in result["moving_averages"].items():
        print(f"  {pair}: Fast={info['fast_ma']}, Slow={info['slow_ma']}, Trend={info['trend']}")
    print(f"Total crossover signals: {result['total_signals']}")
    output = os.path.join(WORKSPACE, "ma_crossover_result.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
