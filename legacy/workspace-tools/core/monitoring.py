#!/usr/bin/env python3
"""
Elysia Monitoring Dashboard - Task 1259
System health, service status, and alerting.
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class HealthCheck:
    def __init__(self, name: str, check_func, interval: int = 60):
        self.name = name
        self.check_func = check_func
        self.interval = interval
        self.last_check = 0
        self.status = "unknown"
        self.last_result = {}

    def check(self) -> Dict[str, Any]:
        now = time.time()
        if now - self.last_check < self.interval:
            return self.last_result
        try:
            result = self.check_func()
            self.status = "healthy"
            self.last_result = {"status": "healthy", "result": result,
                               "timestamp": datetime.now().isoformat()}
        except Exception as e:
            self.status = "unhealthy"
            self.last_result = {"status": "unhealthy", "error": str(e),
                               "timestamp": datetime.now().isoformat()}
        self.last_check = now
        return self.last_result


class MonitoringDashboard:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "monitoring")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.checks: Dict[str, HealthCheck] = {}
        self.alerts: List[Dict[str, Any]] = []
        self.metrics: Dict[str, List[float]] = {}

    def add_check(self, name: str, check_func, interval: int = 60):
        self.checks[name] = HealthCheck(name, check_func, interval)

    def record_metric(self, name: str, value: float):
        if name not in self.metrics:
            self.metrics[name] = []
        self.metrics[name].append(value)
        if len(self.metrics[name]) > 1000:
            self.metrics[name] = self.metrics[name][-1000:]

    def alert(self, severity: str, message: str, source: str = "system"):
        alert = {
            "severity": severity,
            "message": message,
            "source": source,
            "timestamp": datetime.now().isoformat(),
            "acknowledged": False
        }
        self.alerts.append(alert)
        return alert

    def get_health(self) -> Dict[str, Any]:
        results = {}
        all_healthy = True
        for name, check in self.checks.items():
            result = check.check()
            results[name] = result
            if result.get("status") != "healthy":
                all_healthy = False
        return {
            "overall": "healthy" if all_healthy else "degraded",
            "checks": results,
            "timestamp": datetime.now().isoformat()
        }

    def get_metrics_summary(self) -> Dict[str, Any]:
        summary = {}
        for name, values in self.metrics.items():
            if values:
                summary[name] = {
                    "latest": values[-1],
                    "min": min(values),
                    "max": max(values),
                    "avg": sum(values) / len(values),
                    "count": len(values)
                }
        return summary

    def get_unacknowledged_alerts(self) -> List[Dict[str, Any]]:
        return [a for a in self.alerts if not a["acknowledged"]]

    def acknowledge_alert(self, index: int) -> bool:
        if 0 <= index < len(self.alerts):
            self.alerts[index]["acknowledged"] = True
            return True
        return False

    def render_dashboard(self) -> str:
        health = self.get_health()
        lines = [
            "=" * 50,
            "  ELYSIA MONITORING DASHBOARD",
            f"  Status: {health['overall'].upper()}",
            f"  Time: {health['timestamp'][:19]}",
            "=" * 50, ""
        ]
        for name, result in health["checks"].items():
            status_icon = "✓" if result["status"] == "healthy" else "✗"
            lines.append(f"  {status_icon} {name}: {result['status']}")
        lines.append("")
        metrics = self.get_metrics_summary()
        if metrics:
            lines.append("METRICS:")
            for name, data in metrics.items():
                lines.append(f"  {name}: latest={data['latest']:.2f} "
                            f"avg={data['avg']:.2f} min={data['min']:.2f} max={data['max']:.2f}")
        unacked = self.get_unacknowledged_alerts()
        if unacked:
            lines.append(f"\nALERTS: {len(unacked)} unacknowledged")
            for a in unacked[-5:]:
                lines.append(f"  [{a['severity']}] {a['message']}")
        lines.append("=" * 50)
        return "\n".join(lines)


def main():
    dashboard = MonitoringDashboard()
    if len(sys.argv) < 2:
        print("Elysia Monitoring Dashboard")
        print("Commands: health, metrics, alert <severity> <msg>, dashboard")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "health":
        print(json.dumps(dashboard.get_health(), indent=2))
    elif cmd == "metrics":
        print(json.dumps(dashboard.get_metrics_summary(), indent=2))
    elif cmd == "alert" and len(sys.argv) >= 4:
        dashboard.alert(sys.argv[2], " ".join(sys.argv[3:]))
        print("[+] Alert recorded")
    elif cmd == "dashboard":
        print(dashboard.render_dashboard())


if __name__ == "__main__":
    main()
