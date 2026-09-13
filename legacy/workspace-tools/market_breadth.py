#!/usr/bin/env python3
"""Task #13: Market breadth indicator."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def calculate_breadth(advancing, declining, unchanged):
    """Calculate market breadth indicators."""
    total = advancing + declining + unchanged
    ad_ratio = advancing / declining if declining > 0 else float('inf')
    ad_line = advancing - declining
    ad_percentage = (advancing / total * 100) if total > 0 else 50
    mcclellan = ad_percentage - 50  # Simplified McClellan
    return {
        "advancing": advancing,
        "declining": declining,
        "unchanged": unchanged,
        "total": total,
        "ad_ratio": round(ad_ratio, 2),
        "ad_line": ad_line,
        "ad_percentage": round(ad_percentage, 1),
        "breadth": "strong_bullish" if ad_percentage > 60 else "bullish" if ad_percentage > 55 else "neutral" if ad_percentage > 45 else "bearish" if ad_percentage > 40 else "strong_bearish",
        "new_highs_lows": "expansion" if advancing > declining * 1.5 else "contraction" if declining > advancing * 1.5 else "mixed"
    }

def calculate_arms_index(adv_issues, dec_issues, adv_volume, dec_volume):
    """Calculate TRIN/ARMS index."""
    if dec_issues == 0 or dec_volume == 0:
        return {"trin": 0, "signal": "insufficient_data"}
    trin = (adv_issues / dec_issues) / (adv_volume / dec_volume)
    signal = "oversold" if trin > 2 else "neutral" if trin > 0.5 else "overbought"
    return {"trin": round(trin, 4), "signal": signal}

if __name__ == "__main__":
    result = calculate_breadth(2800, 2100, 150)
    trin = calculate_arms_index(2800, 2100, 5e9, 4.5e9)
    print("Market Breadth:")
    print(f"  Advance/Decline: {result['advancing']}/{result['declining']}")
    print(f"  A/D Ratio: {result['ad_ratio']}")
    print(f"  A/D Line: {result['ad_line']}")
    print(f"  Breadth Signal: {result['breadth']}")
    print(f"  TRIN: {trin['trin']} ({trin['signal']})")
    output = os.path.join(WORKSPACE, "market_breadth.json")
    with open(output, 'w') as f:
        json.dump({"breadth": result, "trin": trin}, f, indent=2)
    print(f"[+] Saved to {output}")
