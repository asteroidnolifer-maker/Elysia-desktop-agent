#!/usr/bin/env python3
"""
Elysia Real-time Metrics - Task 1602
Live metrics collection, aggregation, and streaming.
"""
import json
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from threading import Lock


class RealTimeMetrics:
    def __init__(self, window_seconds: int = 300, persist_path: str = None):
        self.window = window_seconds
        self.persist_path = Path(persist_path or Path(__file__).parent / ".data" / "rt_metrics.json")
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.counters: Dict[str, int] = defaultdict(int)
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.timestamps: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

    def increment(self, name: str, value: int = 1):
        with self.lock:
            self.counters[name] += value

    def decrement(self, name: str, value: int = 1):
        with self.lock:
            self.counters[name] -= value

    def set_gauge(self, name: str, value: float):
        with self.lock:
            self.gauges[name] = value

    def record_histogram(self, name: str, value: float):
        with self.lock:
            self.histograms[name].append(value)
            self.timestamps[name].append(time.time())

    def get_counter(self, name: str) -> int:
        return self.counters.get(name, 0)

    def get_gauge(self, name: str) -> Optional[float]:
        return self.gauges.get(name)

    def get_histogram(self, name: str, window_seconds: int = None) -> Dict[str, Any]:
        window = window_seconds or self.window
        cutoff = time.time() - window
        with self.lock:
            values = [v for v, t in zip(self.histograms[name], self.timestamps[name])
                      if t >= cutoff]
        if not values:
            return {"count": 0, "min": 0, "max": 0, "avg": 0, "p50": 0, "p95": 0, "p99": 0}
        values.sort()
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
            "p50": values[len(values) // 2],
            "p95": values[int(len(values) * 0.95)],
            "p99": values[int(len(values) * 0.99)]
        }

    def rate(self, name: str, window_seconds: int = 60) -> float:
        cutoff = time.time() - window_seconds
        with self.lock:
            recent = [t for t in self.timestamps[name] if t >= cutoff]
        if len(recent) < 2:
            return 0
        return (len(recent) - 1) / (recent[-1] - recent[0]) if recent[-1] > recent[0] else 0

    def snapshot(self) -> Dict[str, Any]:
        return {
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
            "histograms": {name: self.get_histogram(name)
                          for name in self.histograms},
            "timestamp": datetime.now().isoformat()
        }

    def persist(self):
        self.persist_path.write_text(json.dumps(self.snapshot(), indent=2))

    def load(self):
        if self.persist_path.exists():
            data = json.loads(self.persist_path.read_text())
            self.counters.update(data.get("counters", {}))
            self.gauges.update(data.get("gauges", {}))


class MetricTimer:
    def __init__(self, metrics: RealTimeMetrics, name: str):
        self.metrics = metrics
        self.name = name
        self.start = None

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        elapsed = time.time() - self.start
        self.metrics.record_histogram(self.name, elapsed)


def main():
    metrics = RealTimeMetrics()

    if len(sys.argv) < 2:
        print("Elysia Real-time Metrics")
        print("Commands: inc <name>, gauge <name> <value>, hist <name> <value>, snapshot, rate <name>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "inc" and len(sys.argv) >= 3:
        metrics.increment(sys.argv[2])
        print(f"[+] {sys.argv[2]}: {metrics.get_counter(sys.argv[2])}")
    elif cmd == "gauge" and len(sys.argv) >= 4:
        metrics.set_gauge(sys.argv[2], float(sys.argv[3]))
        print(f"[+] {sys.argv[2]} = {sys.argv[3]}")
    elif cmd == "hist" and len(sys.argv) >= 4:
        metrics.record_histogram(sys.argv[2], float(sys.argv[3]))
        h = metrics.get_histogram(sys.argv[2])
        print(f"[+] {sys.argv[2]}: p50={h['p50']:.2f} p95={h['p95']:.2f} avg={h['avg']:.2f}")
    elif cmd == "snapshot":
        print(json.dumps(metrics.snapshot(), indent=2))
    elif cmd == "rate" and len(sys.argv) >= 3:
        r = metrics.rate(sys.argv[2])
        print(f"Rate: {r:.2f}/s")


if __name__ == "__main__":
    main()
