#!/usr/bin/env python3
"""Task #22: Pattern recognition (head & shoulders)."""
import json, os

WORKSPACE = "/data/elysia/workspace/tools"

def detect_head_shoulders(prices, tolerance=0.02):
    """Detect head and shoulders pattern."""
    if len(prices) < 20:
        return {"detected": False}
    # Find local maxima
    peaks = []
    for i in range(2, len(prices)-2):
        if prices[i] > prices[i-1] and prices[i] > prices[i+1] and prices[i] > prices[i-2] and prices[i] > prices[i+2]:
            peaks.append({"index": i, "price": prices[i]})
    if len(peaks) < 3:
        return {"detected": False, "peaks_found": len(peaks)}
    # Check for H&S: left shoulder < head > right shoulder, shoulders roughly equal
    for i in range(len(peaks)-2):
        left = peaks[i]["price"]
        head = peaks[i+1]["price"]
        right = peaks[i+2]["price"]
        if head > left and head > right:
            shoulder_diff = abs(left - right) / left
            if shoulder_diff < tolerance:
                neckline = min(prices[peaks[i]["index"]:peaks[i+2]["index"]+1])
                return {
                    "detected": True,
                    "pattern": "head_and_shoulders",
                    "left_shoulder": left,
                    "head": head,
                    "right_shoulder": right,
                    "neckline": neckline,
                    "target": round(neckline - (head - neckline), 2),
                    "confidence": round((1 - shoulder_diff) * 100, 1),
                    "bearish": True
                }
    return {"detected": False, "peaks_found": len(peaks)}

def detect_inverse_head_shoulders(prices, tolerance=0.02):
    """Detect inverse head and shoulders."""
    inverted = [-p for p in prices]
    result = detect_head_shoulders(inverted, tolerance)
    if result.get("detected"):
        result["pattern"] = "inverse_head_and_shoulders"
        result["bearish"] = False
        result["left_shoulder"] = -result["left_shoulder"]
        result["head"] = -result["head"]
        result["right_shoulder"] = -result["right_shoulder"]
    return result

if __name__ == "__main__":
    # Create a sample H&S pattern
    prices = [100, 102, 105, 103, 100, 98, 101, 104, 108, 106, 103, 100, 97,
              100, 103, 105, 103, 101, 99, 97, 95, 93, 91]
    result = detect_head_shoulders(prices)
    inv_result = detect_inverse_head_shoulders(prices)
    print("Pattern Recognition:")
    print(f"  Head & Shoulders: {'DETECTED' if result['detected'] else 'Not found'}")
    if result.get("detected"):
        print(f"    Head: ${result['head']}, Target: ${result['target']}")
    print(f"  Inverse H&S: {'DETECTED' if inv_result.get('detected') else 'Not found'}")
    output = os.path.join(WORKSPACE, "pattern_recognition.json")
    with open(output, 'w') as f:
        json.dump({"head_shoulders": result, "inverse_head_shoulders": inv_result}, f, indent=2)
    print(f"[+] Saved to {output}")
