#!/usr/bin/env python3
"""
Elysia Predictive Analytics - Task 1614
Time-series forecasting, trend analysis, and anomaly detection.
"""
import json
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


class TimeSeriesAnalyzer:
    def __init__(self):
        pass

    def moving_average(self, data: List[float], window: int = 7) -> List[float]:
        if len(data) < window:
            return data
        result = []
        for i in range(len(data)):
            start = max(0, i - window + 1)
            result.append(sum(data[start:i+1]) / (i - start + 1))
        return result

    def exponential_smoothing(self, data: List[float], alpha: float = 0.3) -> List[float]:
        if not data:
            return []
        result = [data[0]]
        for i in range(1, len(data)):
            result.append(alpha * data[i] + (1 - alpha) * result[-1])
        return result

    def linear_regression(self, x: List[float], y: List[float]) -> Dict[str, float]:
        n = len(x)
        if n < 2:
            return {"slope": 0, "intercept": 0, "r_squared": 0}
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi * xi for xi in x)

        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0:
            return {"slope": 0, "intercept": sum_y / n, "r_squared": 0}

        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n

        y_mean = sum_y / n
        ss_res = sum((yi - (slope * xi + intercept))**2 for xi, yi in zip(x, y))
        ss_tot = sum((yi - y_mean)**2 for yi in y)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0

        return {"slope": slope, "intercept": intercept, "r_squared": r_squared}

    def forecast(self, data: List[float], periods: int = 7) -> Dict[str, Any]:
        x = list(range(len(data)))
        lr = self.linear_regression(x, data)
        forecast_values = []
        for i in range(periods):
            val = lr["slope"] * (len(data) + i) + lr["intercept"]
            forecast_values.append(max(0, val))

        smoothed = self.exponential_smoothing(data)
        trend = "up" if lr["slope"] > 0 else "down" if lr["slope"] < 0 else "flat"

        return {
            "forecast": forecast_values,
            "trend": trend,
            "slope": lr["slope"],
            "r_squared": lr["r_squared"],
            "confidence": "high" if lr["r_squared"] > 0.7 else "medium" if lr["r_squared"] > 0.4 else "low"
        }

    def detect_anomalies(self, data: List[float],
                         threshold: float = 2.0) -> List[Dict[str, Any]]:
        if len(data) < 3:
            return []
        mean = sum(data) / len(data)
        variance = sum((x - mean)**2 for x in data) / len(data)
        std = math.sqrt(variance)

        anomalies = []
        for i, val in enumerate(data):
            z_score = (val - mean) / std if std > 0 else 0
            if abs(z_score) > threshold:
                anomalies.append({
                    "index": i,
                    "value": val,
                    "z_score": round(z_score, 2),
                    "type": "high" if z_score > 0 else "low"
                })
        return anomalies

    def seasonal_decompose(self, data: List[float],
                           period: int = 7) -> Dict[str, Any]:
        n = len(data)
        if n < period * 2:
            return {"trend": data, "seasonal": [0] * n, "residual": [0] * n}

        trend = self.moving_average(data, period)
        seasonal = [0] * n
        for i in range(n):
            seasonal[i] = data[i] - trend[i]

        residual = [data[i] - trend[i] - seasonal[i] for i in range(n)]
        return {"trend": trend, "seasonal": seasonal, "residual": residual}


class PredictiveAnalytics:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "predictions")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.analyzer = TimeSeriesAnalyzer()

    def predict_metric(self, name: str, historical_values: List[float],
                       periods: int = 7) -> Dict[str, Any]:
        forecast = self.analyzer.forecast(historical_values, periods)
        anomalies = self.analyzer.detect_anomalies(historical_values)
        return {
            "metric": name,
            "historical_count": len(historical_values),
            "forecast": forecast,
            "anomalies": anomalies,
            "generated_at": datetime.now().isoformat()
        }

    def generate_report(self, metrics: Dict[str, List[float]]) -> str:
        lines = ["=" * 50, "PREDICTIVE ANALYTICS REPORT", "=" * 50, ""]
        for name, values in metrics.items():
            result = self.predict_metric(name, values)
            f = result["forecast"]
            lines.append(f"Metric: {name}")
            lines.append(f"  Trend: {f['trend']} (R²={f['r_squared']:.3f})")
            lines.append(f"  Next {len(f['forecast'])} periods: "
                        f"{[round(v, 1) for v in f['forecast']]}")
            if result["anomalies"]:
                lines.append(f"  Anomalies: {len(result['anomalies'])} detected")
            lines.append("")
        return "\n".join(lines)


def main():
    pa = PredictiveAnalytics()

    if len(sys.argv) < 2:
        print("Elysia Predictive Analytics")
        print("Commands: predict <values>, forecast <values> [periods], anomalies <values>, report")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd in ("predict", "forecast") and len(sys.argv) >= 3:
        values = [float(v) for v in sys.argv[2].split(",")]
        periods = int(sys.argv[3]) if len(sys.argv) > 3 else 7
        result = pa.predict_metric("custom", values, periods)
        print(json.dumps(result, indent=2))
    elif cmd == "anomalies" and len(sys.argv) >= 3:
        values = [float(v) for v in sys.argv[2].split(",")]
        anomalies = pa.analyzer.detect_anomalies(values)
        print(f"Found {len(anomalies)} anomalies:")
        for a in anomalies:
            print(f"  Index {a['index']}: {a['value']} ({a['type']}, z={a['z_score']})")
    elif cmd == "report":
        import random
        metrics = {
            "tasks_completed": [random.randint(5, 20) for _ in range(30)],
            "error_rate": [random.uniform(0, 5) for _ in range(30)]
        }
        print(pa.generate_report(metrics))


if __name__ == "__main__":
    main()
