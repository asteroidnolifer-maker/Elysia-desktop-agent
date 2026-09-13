#!/usr/bin/env python3
"""
Elysia Analytics Dashboard - Task 1601
Real-time analytics dashboard with charts, metrics, and KPIs.
"""
import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


class MetricStore:
    def __init__(self, store_path: str = None):
        self.store_path = Path(store_path or Path(__file__).parent / ".data" / "metrics.json")
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.metrics: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def _load(self):
        if self.store_path.exists():
            self.metrics = json.loads(self.store_path.read_text())

    def _save(self):
        self.store_path.write_text(json.dumps(self.metrics, indent=2))

    def record(self, name: str, value: float, tags: Dict[str, str] = None):
        if name not in self.metrics:
            self.metrics[name] = []
        self.metrics[name].append({
            "value": value,
            "timestamp": datetime.now().isoformat(),
            "tags": tags or {}
        })
        self._save()

    def query(self, name: str, since_minutes: int = 60) -> List[Dict[str, Any]]:
        entries = self.metrics.get(name, [])
        cutoff = datetime.now() - timedelta(minutes=since_minutes)
        return [e for e in entries if datetime.fromisoformat(e["timestamp"]) >= cutoff]

    def latest(self, name: str) -> Optional[Dict[str, Any]]:
        entries = self.metrics.get(name, [])
        return entries[-1] if entries else None

    def aggregate(self, name: str, since_minutes: int = 60) -> Dict[str, Any]:
        entries = self.query(name, since_minutes)
        if not entries:
            return {"count": 0, "min": 0, "max": 0, "avg": 0, "sum": 0}
        values = [e["value"] for e in entries]
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "sum": sum(values)
        }


class AnalyticsDashboard:
    def __init__(self, store_path: str = None):
        self.store = MetricStore(store_path)
        self.kpis: Dict[str, Dict[str, Any]] = {}

    def record_event(self, event: str, value: float = 1.0,
                     metadata: Dict[str, str] = None):
        self.store.record(event, value, metadata)

    def set_kpi(self, name: str, value: float, target: float = None,
                unit: str = ""):
        self.kpis[name] = {
            "value": value,
            "target": target,
            "unit": unit,
            "updated": datetime.now().isoformat()
        }

    def get_kpis(self) -> Dict[str, Any]:
        for name, kpi in self.kpis.items():
            if kpi.get("target"):
                kpi["progress_pct"] = (kpi["value"] / kpi["target"] * 100) if kpi["target"] else 0
        return self.kpis

    def get_overview(self, hours: int = 24) -> Dict[str, Any]:
        overview = {}
        for name in self.store.metrics:
            agg = self.store.aggregate(name, hours * 60)
            overview[name] = agg
        return {
            "period_hours": hours,
            "metrics": overview,
            "kpis": self.get_kpis(),
            "timestamp": datetime.now().isoformat()
        }

    def render_text_dashboard(self, hours: int = 24) -> str:
        overview = self.get_overview(hours)
        lines = [
            "=" * 60,
            f"  ELYSIA ANALYTICS DASHBOARD",
            f"  Period: last {hours}h | {overview['timestamp']}",
            "=" * 60,
            ""
        ]
        lines.append("KPIs:")
        for name, kpi in overview.get("kpis", {}).items():
            target_str = f"/ {kpi['target']}{kpi['unit']}" if kpi.get("target") else ""
            lines.append(f"  {name}: {kpi['value']}{kpi.get('unit', '')} {target_str}")
        lines.append("")
        lines.append("METRICS:")
        for name, data in overview.get("metrics", {}).items():
            lines.append(f"  {name}: count={data['count']} avg={data['avg']:.2f} "
                         f"min={data['min']:.2f} max={data['max']:.2f}")
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def render_bar_chart(self, name: str, width: int = 40) -> str:
        agg = self.store.aggregate(name, 60)
        if agg["count"] == 0:
            return f"{name}: no data"
        bar_len = int(agg["avg"] / max(agg["max"], 1) * width)
        bar = "#" * bar_len + "-" * (width - bar_len)
        return f"{name}: [{bar}] avg={agg['avg']:.1f}"

    def get_trend(self, name: str, points: int = 10) -> Dict[str, Any]:
        entries = self.store.metrics.get(name, [])[-points:]
        if len(entries) < 2:
            return {"trend": "stable", "change": 0}
        values = [e["value"] for e in entries]
        first_half = sum(values[:len(values)//2]) / max(len(values)//2, 1)
        second_half = sum(values[len(values)//2:]) / max(len(values) - len(values)//2, 1)
        change = ((second_half - first_half) / max(first_half, 1)) * 100
        trend = "up" if change > 5 else "down" if change < -5 else "stable"
        return {"trend": trend, "change_pct": change, "latest": values[-1]}


def main():
    dashboard = AnalyticsDashboard()

    if len(sys.argv) < 2:
        print("Elysia Analytics Dashboard")
        print("Commands: record <event> [value], overview, kpi <name> <value>, chart <event>, trend <event>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "record" and len(sys.argv) >= 3:
        value = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
        dashboard.record_event(sys.argv[2], value)
        print(f"[+] Recorded {sys.argv[2]}={value}")
    elif cmd == "overview":
        print(dashboard.render_text_dashboard())
    elif cmd == "kpi" and len(sys.argv) >= 4:
        dashboard.set_kpi(sys.argv[2], float(sys.argv[3]))
        print(f"[+] KPI set: {sys.argv[2]}={sys.argv[3]}")
    elif cmd == "chart" and len(sys.argv) >= 3:
        print(dashboard.render_bar_chart(sys.argv[2]))
    elif cmd == "trend" and len(sys.argv) >= 3:
        trend = dashboard.get_trend(sys.argv[2])
        print(f"Trend: {trend['trend']} ({trend.get('change_pct', 0):+.1f}%)")


if __name__ == "__main__":
    main()
