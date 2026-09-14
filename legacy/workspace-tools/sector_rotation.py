#!/usr/bin/env python3
"""Task #14: Sector rotation analysis tool."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

SECTORS = {
    "Technology": {"etf": "XLK", "weight": 29.5, "ytd": 18.2, "momentum": 85},
    "Healthcare": {"etf": "XLV", "weight": 12.8, "ytd": 5.1, "momentum": 45},
    "Financial": {"etf": "XLF", "weight": 13.2, "ytd": 12.4, "momentum": 70},
    "Consumer Cyclical": {"etf": "XLY", "weight": 10.5, "ytd": 8.7, "momentum": 55},
    "Energy": {"etf": "XLE", "weight": 4.2, "ytd": -5.3, "momentum": 25},
    "Industrials": {"etf": "XLI", "weight": 8.8, "ytd": 10.1, "momentum": 62},
    "Consumer Defensive": {"etf": "XLP", "weight": 6.5, "ytd": 2.3, "momentum": 35},
    "Utilities": {"etf": "XLU", "weight": 2.8, "ytd": 1.5, "momentum": 30},
    "Real Estate": {"etf": "XLRE", "weight": 2.4, "ytd": -2.1, "momentum": 20},
    "Materials": {"etf": "XLB", "weight": 2.5, "ytd": 6.8, "momentum": 48},
    "Communication Services": {"etf": "XLC", "weight": 8.8, "ytd": 15.3, "momentum": 78},
}

def analyze_rotation():
    """Analyze sector rotation based on momentum and relative strength."""
    ranked = sorted(SECTORS.items(), key=lambda x: x[1]["momentum"], reverse=True)
    leading = [s[0] for s in ranked[:3]]
    lagging = [s[0] for s in ranked[-3:]]
    rotation_signal = "risk_on" if ranked[0][1]["momentum"] > 70 else "risk_off" if ranked[-1][1]["momentum"] < 30 else "mixed"
    return {
        "sectors": {k: v for k, v in ranked},
        "leading_sectors": leading,
        "lagging_sectors": lagging,
        "rotation_signal": rotation_signal,
        "recommendation": f"Overweight {leading[0]} and {leading[1]}, Underweight {lagging[0]}"
    }

if __name__ == "__main__":
    result = analyze_rotation()
    print("Sector Rotation Analysis:")
    print(f"  Leading: {', '.join(result['leading_sectors'])}")
    print(f"  Lagging: {', '.join(result['lagging_sectors'])}")
    print(f"  Signal: {result['rotation_signal']}")
    print(f"  {result['recommendation']}")
    output = os.path.join(WORKSPACE, "sector_rotation.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
