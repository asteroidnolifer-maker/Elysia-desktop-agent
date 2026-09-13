#!/usr/bin/env python3
"""Task #1462: Demand forecasting tool."""
import json, os, random, math

WORKSPACE = "/data/elysia/workspace/tools"

def forecast_demand(historical_sales, months_ahead=6):
    """Forecast future demand using trend analysis."""
    n = len(historical_sales)
    if n < 3:
        return {"error": "Need at least 3 data points"}
    # Simple linear regression
    x = list(range(n))
    mean_x = sum(x) / n
    mean_y = sum(historical_sales) / n
    cov = sum((x[i]-mean_x)*(historical_sales[i]-mean_y) for i in range(n))
    var = sum((xi-mean_x)**2 for xi in x)
    slope = cov / var if var > 0 else 0
    intercept = mean_y - slope * mean_x
    forecast = []
    for i in range(months_ahead):
        val = slope * (n + i) + intercept
        forecast.append({"month": n + i + 1, "predicted": round(max(0, val), 0), "lower": round(max(0, val * 0.8), 0), "upper": round(val * 1.2, 0)})
    growth_rate = (slope / mean_y * 100) if mean_y > 0 else 0
    return {"forecast": forecast, "trend": "increasing" if slope > 0 else "decreasing", "growth_rate": round(growth_rate, 1), "avg_monthly_sales": round(mean_y, 0)}

if __name__ == "__main__":
    sales = [100, 110, 125, 115, 130, 145, 140, 160]
    result = forecast_demand(sales)
    print(f"Demand Forecast (trend: {result['trend']}, growth: {result['growth_rate']}%/month)")
    for f in result["forecast"]:
        print(f"  Month {f['month']}: {f['predicted']} (range: {f['lower']}-{f['upper']})")
    output = os.path.join(WORKSPACE, "demand_forecast.json")
    with open(output, 'w') as f:
        json.dump(result, f, indent=2)
    print(f"[+] Saved to {output}")
