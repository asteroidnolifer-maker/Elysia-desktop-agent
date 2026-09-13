#!/usr/bin/env python3
"""Task #10: Options pricing model (Black-Scholes calculator)."""
import json, os, math

WORKSPACE = "/data/elysia/workspace/tools"

def normal_cdf(x):
    """Standard normal cumulative distribution function."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def normal_pdf(x):
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)

def black_scholes(S, K, T, r, sigma, option_type="call"):
    """Black-Scholes option pricing model.
    S: current stock price
    K: strike price
    T: time to expiration (years)
    r: risk-free interest rate
    sigma: volatility
    """
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    if option_type == "call":
        price = S*normal_cdf(d1) - K*math.exp(-r*T)*normal_cdf(d2)
    else:
        price = K*math.exp(-r*T)*normal_cdf(-d2) - S*normal_cdf(-d1)
    # Greeks
    delta = normal_cdf(d1) if option_type == "call" else normal_cdf(d1) - 1
    gamma = normal_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * normal_pdf(d1) * math.sqrt(T) / 100
    theta = (-(S * normal_pdf(d1) * sigma) / (2 * math.sqrt(T)) -
             r * K * math.exp(-r*T) * normal_cdf(d2 if option_type == "call" else -d2)) / 365
    rho = K * T * math.exp(-r*T) * normal_cdf(d2 if option_type == "call" else -d2) / 100
    return {
        "price": round(price, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 4),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
        "d1": round(d1, 4),
        "d2": round(d2, 4),
        "in_the_money": S > K if option_type == "call" else S < K,
        "intrinsic_value": max(S - K, 0) if option_type == "call" else max(K - S, 0),
        "time_value": round(price - max(S - K, 0) if option_type == "call" else price - max(K - S, 0), 4)
    }

def generate_option_chain(S, r=0.05, sigma=0.3):
    """Generate a sample option chain."""
    chain = []
    for offset in range(-5, 6):
        K = S + offset * 5
        call = black_scholes(S, K, 30/365, r, sigma, "call")
        put = black_scholes(S, K, 30/365, r, sigma, "put")
        chain.append({"strike": K, "call": call, "put": put})
    return chain

if __name__ == "__main__":
    # Example: AAPL call option
    result = black_scholes(S=178.50, K=180.0, T=30/365, r=0.05, sigma=0.25, option_type="call")
    print("Black-Scholes Option Pricing:")
    print(f"  Price: ${result['price']}")
    print(f"  Delta: {result['delta']}")
    print(f"  Gamma: {result['gamma']}")
    print(f"  Theta: ${result['theta']}/day")
    print(f"  Vega: ${result['vega']}")
    print(f"  Intrinsic: ${result['intrinsic_value']}")
    print(f"  Time Value: ${result['time_value']}")
    chain = generate_option_chain(178.50)
    print(f"\nOption Chain (ATM ±$25):")
    for opt in chain[:5]:
        print(f"  Strike ${opt['strike']}: Call ${opt['call']['price']:.2f}, Put ${opt['put']['price']:.2f}")
    output = os.path.join(WORKSPACE, "options_pricing.json")
    with open(output, 'w') as f:
        json.dump({"black_scholes": result, "option_chain": chain}, f, indent=2)
    print(f"[+] Saved to {output}")
