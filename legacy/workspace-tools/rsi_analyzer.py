#!/usr/bin/env python3
"""Task #3: RSI analyzer tool."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def calculate_rsi(prices, period=14):
    """Calculate Relative Strength Index."""
    if len(prices) < period + 1:
        return {"error": "Not enough data"}
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    rsi_values = []
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        rsi_values.append(round(rsi, 2))
    return rsi_values

def analyze_rsi(prices, period=14):
    """Full RSI analysis with signals."""
    rsi = calculate_rsi(prices, period)
    if isinstance(rsi, dict):
        return rsi
    latest = rsi[-1]
    signals = []
    # Overbought/Oversold
    if latest > 70:
        signals.append({"type": "overbought", "value": latest, "action": "consider selling"})
    elif latest < 30:
        signals.append({"type": "oversold", "value": latest, "action": "consider buying"})
    # Divergence detection
    if len(rsi) > 20:
        recent_rsi = rsi[-20:]
        recent_prices = prices[-20:]
        if max(recent_prices[-10:]) > max(recent_prices[:10]) and max(recent_rsi[-10:]) < max(recent_rsi[:10]):
            signals.append({"type": "bearish_divergence", "action": "price up but RSI down"})
        if min(recent_prices[-10:]) < min(recent_prices[:10]) and min(recent_rsi[-10:]) > min(recent_rsi[:10]):
            signals.append({"type": "bullish_divergence", "action": "price down but RSI up"})
    # Centerline crossover
    if len(rsi) > 1 and rsi[-2] < 50 and rsi[-1] >= 50:
        signals.append({"type": "centerline_cross_up", "action": "bullish momentum"})
    elif len(rsi) > 1 and rsi[-2] > 50 and rsi[-1] <= 50:
        signals.append({"type": "centerline_cross_down", "action": "bearish momentum"})
    return {
        "rsi_values": rsi[-20:],
        "latest_rsi": latest,
        "period": period,
        "signals": signals,
        "interpretation": "overbought" if latest > 70 else "oversold" if latest < 30 else "neutral"
    }

if __name__ == "__main__":
    import random
    prices = [100]
    for _ in range(99):
        prices.append(prices[-1] + random.uniform(-2, 2))
    result = analyze_rsi(prices)
    print(f"Latest RSI: {result['latest_rsi']}")
    print(f"Interpretation: {result['interpretation']}")
    for s in result.get('signals', []):
        print(f"  Signal: {s['type']} - {s.get('action', '')}")
    output = os.path.join(WORKSPACE, "rsi_result.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
