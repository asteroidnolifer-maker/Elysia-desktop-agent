#!/usr/bin/env python3
"""
Elysia Data Visualization - Task 1618
Text-based charts: bar, line, sparkline, histogram.
"""
import math
import sys
from typing import List, Optional


class TextCharts:
    def __init__(self, width: int = 60, height: int = 15):
        self.width = width
        self.height = height

    def bar_chart(self, data: dict, title: str = "") -> str:
        if not data:
            return ""
        labels = list(data.keys())
        values = list(data.values())
        max_val = max(values) if values else 1
        lines = []
        if title:
            lines.append(f"  {title}")
            lines.append("  " + "-" * (self.width - 2))
        max_label = max(len(l) for l in labels)
        for label, val in zip(labels, values):
            bar_len = int(val / max_val * (self.width - max_label - 4))
            bar = "#" * bar_len
            lines.append(f"  {label:>{max_label}} | {bar} {val}")
        return "\n".join(lines)

    def horizontal_bar(self, data: dict, title: str = "") -> str:
        return self.bar_chart(data, title)

    def sparkline(self, values: List[float], width: int = 40) -> str:
        if not values:
            return ""
        blocks = " ▁▂▃▄▅▆▇█"
        mn, mx = min(values), max(values)
        rng = mx - mn if mx != mn else 1
        sampled = values
        if len(values) > width:
            step = len(values) / width
            sampled = [values[int(i * step)] for i in range(width)]
        return "".join(blocks[min(int((v - mn) / rng * 8), 8)] for v in sampled)

    def line_chart(self, data: dict, title: str = "") -> str:
        if not data:
            return ""
        values = list(data.values())
        labels = list(data.keys())
        mn, mx = min(values), max(values)
        rng = mx - mn if mx != mn else 1
        lines = []
        if title:
            lines.append(f"  {title}")
        for row in range(self.height, -1, -1):
            threshold = mn + (rng * row / self.height)
            line = ""
            for v in values:
                if v >= threshold:
                    line += " * "
                else:
                    line += "   "
            lines.append(f"  {threshold:>7.1f} |{line}")
        lines.append("  " + " " * 8 + "+" + "---" * len(values))
        return "\n".join(lines)

    def histogram(self, values: List[float], bins: int = 10, title: str = "") -> str:
        if not values:
            return ""
        mn, mx = min(values), max(values)
        rng = mx - mn if mx != mn else 1
        bin_size = rng / bins
        counts = [0] * bins
        for v in values:
            idx = min(int((v - mn) / bin_size), bins - 1)
            counts[idx] += 1
        max_count = max(counts) if counts else 1
        lines = []
        if title:
            lines.append(f"  {title}")
        for i, count in enumerate(counts):
            lo = mn + i * bin_size
            hi = lo + bin_size
            bar_len = int(count / max_count * (self.width - 20))
            bar = "#" * bar_len
            lines.append(f"  {lo:7.1f}-{hi:7.1f} | {bar} ({count})")
        return "\n".join(lines)

    def pie_chart(self, data: dict, title: str = "") -> str:
        if not data:
            return ""
        total = sum(data.values())
        if total == 0:
            return ""
        chars = "█▓▒░"
        lines = []
        if title:
            lines.append(f"  {title}")
        max_label = max(len(k) for k in data.keys())
        for i, (label, val) in enumerate(data.items()):
            pct = val / total * 100
            bar_len = int(pct / 100 * 20)
            char = chars[min(i, len(chars) - 1)]
            bar = char * bar_len
            lines.append(f"  {label:>{max_label}} | {bar} {pct:.1f}%")
        return "\n".join(lines)


def main():
    charts = TextCharts()

    if len(sys.argv) < 2:
        print("Elysia Text Charts")
        print("Commands: bar <k:v>, line <k:v>, histogram <v,v>, pie <k:v>, sparkline <v,v>")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "bar" and len(sys.argv) >= 3:
        data = dict(item.split(":") for item in sys.argv[2].split(",") if ":" in item)
        data = {k: float(v) for k, v in data.items()}
        print(charts.bar_chart(data, "Bar Chart"))
    elif cmd == "line" and len(sys.argv) >= 3:
        data = dict(item.split(":") for item in sys.argv[2].split(",") if ":" in item)
        data = {k: float(v) for k, v in data.items()}
        print(charts.line_chart(data, "Line Chart"))
    elif cmd == "histogram" and len(sys.argv) >= 3:
        values = [float(v) for v in sys.argv[2].split(",")]
        print(charts.histogram(values, title="Histogram"))
    elif cmd == "pie" and len(sys.argv) >= 3:
        data = dict(item.split(":") for item in sys.argv[2].split(",") if ":" in item)
        data = {k: float(v) for k, v in data.items()}
        print(charts.pie_chart(data, "Pie Chart"))
    elif cmd == "sparkline" and len(sys.argv) >= 3:
        values = [float(v) for v in sys.argv[2].split(",")]
        print(charts.sparkline(values))


if __name__ == "__main__":
    main()
