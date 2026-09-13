#!/usr/bin/env python3
"""Task #7: Fibonacci retracement calculator."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]

def calculate_fibonacci(high, low):
    """Calculate Fibonacci retracement levels."""
    diff = high - low
    levels = {}
    for level in FIB_LEVELS:
        price = high - (diff * level)
        levels[f"{level:.1%}"] = round(price, 2)
    return {"high": high, "low": low, "range": round(diff, 2), "levels": levels}

def find_fib_targets(entry, high, low):
    """Find profit targets and stop losses using Fibonacci extensions."""
    diff = high - low
    return {
        "entry": entry,
        "stop_loss": round(low - diff * 0.1, 2),
        "target_1": round(high + diff * 0.382, 2),
        "target_2": round(high + diff * 0.618, 2),
        "target_3": round(high + diff * 1.0, 2),
        "risk_reward_1": round((high + diff * 0.382 - entry) / (entry - (low - diff * 0.1)), 2),
        "risk_reward_2": round((high + diff * 0.618 - entry) / (entry - (low - diff * 0.1)), 2),
    }

if __name__ == "__main__":
    result = calculate_fibonacci(150.0, 100.0)
    targets = find_fib_targets(120.0, 150.0, 100.0)
    print("Fibonacci Retracement Levels:")
    for level, price in result["levels"].items():
        print(f"  {level}: ${price}")
    print(f"\nTrade Setup:")
    print(f"  Entry: ${targets['entry']}")
    print(f"  Stop Loss: ${targets['stop_loss']}")
    print(f"  Target 1: ${targets['target_1']} (R:R={targets['risk_reward_1']})")
    print(f"  Target 2: ${targets['target_2']} (R:R={targets['risk_reward_2']})")
    output = os.path.join(WORKSPACE, "fibonacci_result.json")
    with open(output, 'w') as f:
        json.dump({"retracement": result, "trade_setup": targets}, f, indent=2)
    print(f"[+] Saved to {output}")
