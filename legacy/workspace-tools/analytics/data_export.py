#!/usr/bin/env python3
"""
Elysia Analytics Data Export - Task 1622
Export analytics data to CSV, JSON, and text formats.
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class AnalyticsExporter:
    def __init__(self, export_dir: str = None):
        self.export_dir = Path(export_dir or Path(__file__).parent / ".data" / "analytics_exports")
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def export_csv(self, records: List[Dict[str, Any]], filename: str) -> str:
        if not records:
            return ""
        path = self.export_dir / filename
        keys = list(records[0].keys())
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(records)
        return str(path)

    def export_json(self, data: Any, filename: str, pretty: bool = True) -> str:
        path = self.export_dir / filename
        path.write_text(json.dumps(data, indent=2 if pretty else None, default=str))
        return str(path)

    def export_metrics_csv(self, metrics: Dict[str, List[Dict]], filename: str = "metrics.csv") -> str:
        rows = []
        for metric_name, entries in metrics.items():
            for entry in entries:
                rows.append({
                    "metric": metric_name,
                    "value": entry.get("value", 0),
                    "timestamp": entry.get("timestamp", ""),
                    "tags": json.dumps(entry.get("tags", {}))
                })
        return self.export_csv(rows, filename)

    def export_summary(self, data: Dict[str, Any], filename: str = "summary.json") -> str:
        summary = {
            "generated_at": datetime.now().isoformat(),
            "data": data
        }
        return self.export_json(summary, filename)

    def export_text_report(self, sections: Dict[str, str],
                           filename: str = "report.txt") -> str:
        path = self.export_dir / filename
        lines = ["=" * 60, "ANALYTICS REPORT", f"Generated: {datetime.now().isoformat()}", "=" * 60, ""]
        for title, content in sections.items():
            lines.append(f"## {title}")
            lines.append(content)
            lines.append("")
        path.write_text("\n".join(lines))
        return str(path)


def main():
    exporter = AnalyticsExporter()

    if len(sys.argv) < 2:
        print("Elysia Analytics Export")
        print("Commands: export-csv, export-json, export-report")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "export-csv" and len(sys.argv) >= 3:
        data = json.loads(sys.argv[2])
        path = exporter.export_csv(data, sys.argv[3] if len(sys.argv) > 3 else "export.csv")
        print(f"[+] Exported to {path}")
    elif cmd == "export-json" and len(sys.argv) >= 3:
        data = json.loads(sys.argv[2])
        path = exporter.export_json(data, sys.argv[3] if len(sys.argv) > 3 else "export.json")
        print(f"[+] Exported to {path}")
    elif cmd == "export-report":
        sections = {"Overview": "Analytics summary", "Metrics": "No data yet"}
        path = exporter.export_text_report(sections)
        print(f"[+] Report: {path}")


if __name__ == "__main__":
    main()
