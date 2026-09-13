#!/usr/bin/env python3
"""Task #16: Short interest ratio analyzer."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def analyze_short_interest(short_shares, float_shares, avg_volume, days_to_cover=0):
    """Analyze short interest metrics."""
    short_ratio = short_shares / float_shares if float_shares > 0 else 0
    dtc = short_shares / avg_volume if avg_volume > 0 else days_to_cover
    if short_ratio > 0.20:
        signal = "extreme_squeeze_potential"
    elif short_ratio > 0.10:
        signal = "high_short_interest"
    elif short_ratio > 0.05:
        signal = "moderate"
    else:
        signal = "low"
    return {
        "short_shares": short_shares,
        "float_shares": float_shares,
        "short_ratio": round(short_ratio, 4),
        "short_percentage": round(short_ratio * 100, 2),
        "days_to_cover": round(dtc, 1),
        "signal": signal,
        "squeeze_potential": "high" if short_ratio > 0.15 and dtc > 5 else "moderate" if short_ratio > 0.10 else "low"
    }

if __name__ == "__main__":
    result = analyze_short_interest(50000000, 400000000, 8000000)
    print("Short Interest Analysis:")
    print(f"  Short Ratio: {result['short_ratio']} ({result['short_percentage']}%)")
    print(f"  Days to Cover: {result['days_to_cover']}")
    print(f"  Signal: {result['signal']}")
    print(f"  Squeeze Potential: {result['squeeze_potential']}")
    output = os.path.join(WORKSPACE, "short_interest.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
