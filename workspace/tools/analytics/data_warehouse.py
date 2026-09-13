#!/usr/bin/env python3
"""
Elysia Data Warehouse - Task 1634
Structured data storage with schema management, ETL, and querying.
"""
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class Schema:
    def __init__(self, name: str, fields: Dict[str, str]):
        self.name = name
        self.fields = fields

    def validate(self, record: Dict[str, Any]) -> List[str]:
        errors = []
        for field, ftype in self.fields.items():
            if field not in record:
                errors.append(f"Missing field: {field}")
            elif ftype == "int" and not isinstance(record[field], int):
                errors.append(f"Field {field} should be int")
            elif ftype == "float" and not isinstance(record[field], (int, float)):
                errors.append(f"Field {field} should be float")
            elif ftype == "str" and not isinstance(record[field], str):
                errors.append(f"Field {field} should be str")
        return errors


class Table:
    def __init__(self, name: str, schema: Schema):
        self.name = name
        self.schema = schema
        self.records: List[Dict[str, Any]] = []

    def insert(self, record: Dict[str, Any]) -> bool:
        errors = self.schema.validate(record)
        if errors:
            return False
        record["_inserted_at"] = datetime.now().isoformat()
        self.records.append(record)
        return True

    def query(self, where: Dict[str, Any] = None, limit: int = 100) -> List[Dict[str, Any]]:
        results = self.records
        if where:
            for key, val in where.items():
                results = [r for r in results if r.get(key) == val]
        return results[:limit]

    def count(self) -> int:
        return len(self.records)


class DataWarehouse:
    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir or Path(__file__).parent / ".data" / "warehouse")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.tables: Dict[str, Table] = {}
        self.schemas: Dict[str, Schema] = {}

    def define_schema(self, name: str, fields: Dict[str, str]) -> Schema:
        schema = Schema(name, fields)
        self.schemas[name] = schema
        return schema

    def create_table(self, name: str, schema_name: str) -> Table:
        schema = self.schemas.get(schema_name)
        if not schema:
            schema = Schema(schema_name, {"id": "int"})
        table = Table(name, schema)
        self.tables[name] = table
        return table

    def insert(self, table_name: str, record: Dict[str, Any]) -> bool:
        table = self.tables.get(table_name)
        if not table:
            return False
        return table.insert(record)

    def query(self, table_name: str, where: Dict[str, Any] = None,
              limit: int = 100) -> List[Dict[str, Any]]:
        table = self.tables.get(table_name)
        if not table:
            return []
        return table.query(where, limit)

    def table_stats(self) -> Dict[str, Any]:
        return {name: {"records": t.count(), "fields": list(t.schema.fields.keys())}
                for name, t in self.tables.items()}

    def save(self):
        for name, table in self.tables.items():
            path = self.data_dir / f"{name}.json"
            path.write_text(json.dumps(table.records, indent=2))

    def load(self):
        for name, table in self.tables.items():
            path = self.data_dir / f"{name}.json"
            if path.exists():
                table.records = json.loads(path.read_text())


def main():
    warehouse = DataWarehouse()

    if len(sys.argv) < 2:
        print("Elysia Data Warehouse")
        print("Commands: create-table <name> <schema>, insert <table> <json>, query <table>, stats")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "create-table" and len(sys.argv) >= 4:
        fields = dict(f.split(":") for f in sys.argv[3].split(","))
        warehouse.define_schema(sys.argv[2], fields)
        warehouse.create_table(sys.argv[2], sys.argv[2])
        print(f"[+] Table '{sys.argv[2]}' created")
    elif cmd == "insert" and len(sys.argv) >= 4:
        record = json.loads(sys.argv[3])
        ok = warehouse.insert(sys.argv[2], record)
        print(f"[+] Inserted: {ok}")
    elif cmd == "query" and len(sys.argv) >= 3:
        results = warehouse.query(sys.argv[2])
        print(json.dumps(results, indent=2))
    elif cmd == "stats":
        print(json.dumps(warehouse.table_stats(), indent=2))


if __name__ == "__main__":
    main()
