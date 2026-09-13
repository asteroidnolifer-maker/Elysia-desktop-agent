#!/usr/bin/env python3
"""Task #8: Stock correlation matrix builder."""
import json, os, math

WORKSPACE = "/data/elysia/workspace/tools"

def correlate(x, y):
    """Pearson correlation coefficient."""
    n = len(x)
    if n < 2:
        return 0
    mean_x = sum(x)/n
    mean_y = sum(y)/n
    cov = sum((x[i]-mean_x)*(y[i]-mean_y) for i in range(n)) / n
    std_x = math.sqrt(sum((xi-mean_x)**2 for xi in x)/n)
    std_y = math.sqrt(sum((yi-mean_y)**2 for yi in y)/n)
    if std_x == 0 or std_y == 0:
        return 0
    return cov / (std_x * std_y)

def build_correlation_matrix(returns_dict):
    """Build correlation matrix from price returns."""
    symbols = list(returns_dict.keys())
    matrix = {}
    for s1 in symbols:
        matrix[s1] = {}
        for s2 in symbols:
            corr = correlate(returns_dict[s1], returns_dict[s2])
            matrix[s1][s2] = round(corr, 4)
    return matrix

def find_uncorrelated_pairs(matrix, threshold=0.3):
    """Find pairs with low correlation for diversification."""
    pairs = []
    symbols = list(matrix.keys())
    for i in range(len(symbols)):
        for j in range(i+1, len(symbols)):
            corr = matrix[symbols[i]][symbols[j]]
            if abs(corr) < threshold:
                pairs.append({"pair": f"{symbols[i]}/{symbols[j]}", "correlation": corr})
    return sorted(pairs, key=lambda x: abs(x["correlation"]))

if __name__ == "__main__":
    import random
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
    returns = {}
    for sym in symbols:
        r = [random.uniform(-0.03, 0.03) for _ in range(252)]
        returns[sym] = r
    matrix = build_correlation_matrix(returns)
    pairs = find_uncorrelated_pairs(matrix)
    print("Correlation Matrix:")
    print("     ", "  ".join(f"{s[:4]:>6}" for s in symbols))
    for s1 in symbols:
        vals = "  ".join(f"{matrix[s1][s2]:6.3f}" for s2 in symbols)
        print(f"{s1[:4]:>5} {vals}")
    print(f"\nBest diversification pairs:")
    for p in pairs[:3]:
        print(f"  {p['pair']}: {p['correlation']:.4f}")
    output = os.path.join(WORKSPACE, "correlation_result.json")
    with open(output, 'w') as f:
        json.dump({"matrix": matrix, "diversification_pairs": pairs}, f, indent=2)
    print(f"[+] Saved to {output}")
