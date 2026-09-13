#!/usr/bin/env python3
"""Task #18: Portfolio beta calculator."""
import json, os, math

WORKSPACE = "/data/elysia/workspace/tools"

def calculate_beta(portfolio_returns, benchmark_returns):
    """Calculate portfolio beta against benchmark."""
    n = min(len(portfolio_returns), len(benchmark_returns))
    p = portfolio_returns[-n:]
    b = benchmark_returns[-n:]
    mean_p = sum(p)/n
    mean_b = sum(b)/n
    cov = sum((p[i]-mean_p)*(b[i]-mean_b) for i in range(n)) / n
    var_b = sum((b[i]-mean_b)**2 for i in range(n)) / n
    beta = cov / var_b if var_b > 0 else 1
    alpha = mean_p - beta * mean_b
    correlation = cov / (math.sqrt(sum((pi-mean_p)**2 for pi in p)/n) * math.sqrt(var_b))
    return {
        "beta": round(beta, 4),
        "alpha": round(alpha * 252, 4),  # Annualized
        "correlation": round(correlation, 4),
        "r_squared": round(correlation**2, 4),
        "volatility": round(math.sqrt(sum((pi-mean_p)**2 for pi in p)/n) * math.sqrt(252), 4),
        "interpretation": "aggressive" if beta > 1.2 else "defensive" if beta < 0.8 else "market_neutral"
    }

if __name__ == "__main__":
    import random
    port = [random.uniform(-0.02, 0.03) for _ in range(252)]
    bench = [random.uniform(-0.015, 0.02) for _ in range(252)]
    result = calculate_beta(port, bench)
    print("Portfolio Beta Analysis:")
    print(f"  Beta: {result['beta']}")
    print(f"  Alpha (annualized): {result['alpha']}")
    print(f"  Correlation: {result['correlation']}")
    print(f"  R-Squared: {result['r_squared']}")
    print(f"  Volatility: {result['volatility']}")
    print(f"  Interpretation: {result['interpretation']}")
    output = os.path.join(WORKSPACE, "portfolio_beta.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
