#!/usr/bin/env python3
"""
Elysia Import/Export - Task 1247
Data import/export in multiple formats: JSON, CSV, YAML, Markdown.
"""
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class ImportExport:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "exports")
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def export_json(self, data: Any, filename: str, pretty: bool = True) -> str:
        path = self.data_dir / filename
        indent = 2 if pretty else None
        path.write_text(json.dumps(data, indent=indent, default=str))
        return str(path)

    def import_json(self, filepath: str) -> Any:
        return json.loads(Path(filepath).read_text())

    def export_csv(self, records: List[Dict[str, Any]], filename: str) -> str:
        if not records:
            return ""
        path = self.data_dir / filename
        keys = list(records[0].keys())
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(records)
        return str(path)

    def import_csv(self, filepath: str) -> List[Dict[str, Any]]:
        records = []
        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                records.append(dict(row))
        return records

    def export_markdown(self, data: Dict[str, Any], filename: str) -> str:
        path = self.data_dir / filename
        lines = [f"# {data.get('title', 'Export')}\n"]
        lines.append(f"Generated: {datetime.now().isoformat()}\n")

        for section, content in data.get("sections", {}).items():
            lines.append(f"\n## {section}\n")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        lines.append(f"- **{item.get('name', '')}**: {item.get('value', '')}")
                    else:
                        lines.append(f"- {item}")
            elif isinstance(content, dict):
                for k, v in content.items():
                    lines.append(f"| {k} | {v} |")
            else:
                lines.append(str(content))

        path.write_text("\n".join(lines))
        return str(path)

    def export_tasks_csv(self, tasks: List[Dict[str, Any]], filename: str = "tasks_export.csv") -> str:
        return self.export_csv(tasks, filename)

    def import_tasks_csv(self, filepath: str) -> List[Dict[str, Any]]:
        records = self.import_csv(filepath)
        for r in records:
            if "priority" in r:
                try:
                    r["priority"] = int(r["priority"])
                except ValueError:
                    r["priority"] = 3
            if "id" in r:
                try:
                    r["id"] = int(r["id"])
                except ValueError:
                    pass
        return records

    def backup_data(self, source_dir: str, backup_name: str = None) -> str:
        source = Path(source_dir)
        backup_name = backup_name or f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        files_data = {}
        for path in source.rglob("*"):
            if path.is_file() and ".data" not in str(path):
                rel = str(path.relative_to(source))
                try:
                    files_data[rel] = {
                        "content": path.read_text(errors="ignore"),
                        "size": path.stat().st_size,
                        "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat()
                    }
                except Exception:
                    pass
        return self.export_json({"files": files_data, "source": str(source)}, backup_name)

    def restore_data(self, backup_path: str, target_dir: str) -> int:
        data = self.import_json(backup_path)
        target = Path(target_dir)
        restored = 0
        for rel, info in data.get("files", {}).items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(info.get("content", ""))
            restored += 1
        return restored

    def convert(self, input_path: str, output_format: str) -> str:
        ext = Path(input_path).suffix.lower()
        if ext == ".json":
            data = self.import_json(input_path)
        elif ext == ".csv":
            data = self.import_csv(input_path)
        else:
            return ""

        out_name = Path(input_path).stem + f".{output_format}"
        if output_format == "json":
            return self.export_json(data, out_name)
        elif output_format == "csv":
            if isinstance(data, list) and data:
                return self.export_csv(data, out_name)
        elif output_format == "md":
            return self.export_markdown({"title": "Converted", "sections": {"data": data}}, out_name)
        return ""


def main():
    ie = ImportExport()

    if len(sys.argv) < 2:
        print("Elysia Import/Export")
        print("Commands: export-json, export-csv, import-json, import-csv, backup, restore, convert")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "export-json" and len(sys.argv) >= 4:
        data = json.loads(sys.argv[2])
        path = ie.export_json(data, sys.argv[3])
        print(f"[+] Exported to {path}")
    elif cmd == "import-json" and len(sys.argv) >= 3:
        data = ie.import_json(sys.argv[2])
        print(json.dumps(data, indent=2)[:500])
    elif cmd == "backup" and len(sys.argv) >= 3:
        path = ie.backup_data(sys.argv[2])
        print(f"[+] Backup: {path}")
    elif cmd == "restore" and len(sys.argv) >= 4:
        count = ie.restore_data(sys.argv[2], sys.argv[3])
        print(f"[+] Restored {count} files")
    elif cmd == "convert" and len(sys.argv) >= 4:
        path = ie.convert(sys.argv[2], sys.argv[3])
        print(f"[+] Converted to {path}")


if __name__ == "__main__":
    main()
