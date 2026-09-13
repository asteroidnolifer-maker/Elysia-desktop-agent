#!/usr/bin/env python3
"""Task #11: Put-Call ratio analyzer."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def calculate_put_call_ratio(call_volume, put_volume):
    """Calculate put-call ratio from volume data."""
    if call_volume == 0:
        return {"ratio": float('inf'), "signal": "extreme_bearish"}
    ratio = put_volume / call_volume
    if ratio > 1.5:
        signal = "extreme_bearish"  # Contrarian bullish
    elif ratio > 0.9:
        signal = "bearish"
    elif ratio < 0.5:
        signal = "extreme_bullish"  # Contrarian bearish
    elif ratio < 0.7:
        signal = "bullish"
    else:
        signal = "neutral"
    return {"ratio": round(ratio, 4), "signal": signal, "calls": call_volume, "puts": put_volume}

def analyze_historical_pcr(ratios):
    """Analyze PCR trends over time."""
    avg = sum(ratios) / len(ratios)
    recent = ratios[-5:]
    recent_avg = sum(recent) / len(recent)
    trend = "increasing" if recent_avg > avg else "decreasing"
    z_score = (ratios[-1] - avg) / (sum((r-avg)**2 for r in ratios)/len(ratios))**0.5 if len(ratios) > 1 else 0
    return {
        "current": ratios[-1],
        "average": round(avg, 4),
        "recent_average": round(recent_avg, 4),
        "z_score": round(z_score, 2),
        "trend": trend,
        "extreme": abs(z_score) > 2,
        "interpretation": "overbought" if z_score < -2 else "oversold" if z_score > 2 else "normal"
    }

if __name__ == "__main__":
    import random
    # Current market PCR
    result = calculate_put_call_ratio(2500000, 1800000)
    print(f"Put-Call Ratio: {result['ratio']}")
    print(f"Signal: {result['signal']}")
    # Historical analysis
    historical = [random.uniform(0.5, 1.3) for _ in range(30)]
    hist_analysis = analyze_historical_pcr(historical)
    print(f"\nHistorical PCR Analysis:")
    print(f"  Current: {hist_analysis['current']}")
    print(f"  Average: {hist_analysis['average']}")
    print(f"  Z-Score: {hist_analysis['z_score']}")
    print(f"  Trend: {hist_analysis['trend']}")
    print(f"  Extreme: {hist_analysis['extreme']}")
    output = os.path.join(WORKSPACE, "put_call_ratio.json")
    with open(output, 'w') as f:
        json.dump({"current": result, "historical": hist_analysis}, f, indent=2)
    print(f"[+] Saved to {output}")
