#!/usr/bin/env python3
"""
Elysia Backup System - Task 1248
Automated backup with rotation, compression, and restore.
"""
import gzip
import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


class BackupManager:
    def __init__(self, backup_dir: str = None, max_backups: int = 10):
        self.backup_dir = Path(backup_dir or Path(__file__).parent / ".data" / "backups")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.max_backups = max_backups
        self.manifest_path = self.backup_dir / "manifest.json"
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> Dict[str, Any]:
        if self.manifest_path.exists():
            return json.loads(self.manifest_path.read_text())
        return {"backups": [], "created": datetime.now().isoformat()}

    def _save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2))

    def create_backup(self, source_dir: str, name: str = None,
                      compress: bool = True) -> Dict[str, Any]:
        source = Path(source_dir)
        name = name or f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path = self.backup_dir / name

        if compress:
            backup_path = backup_path.with_suffix(".tar.gz")
            import tarfile
            with tarfile.open(backup_path, "w:gz") as tar:
                tar.add(source, arcname=name)
        else:
            shutil.copytree(source, backup_path, dirs_exist_ok=True)

        size = backup_path.stat().st_size if backup_path.exists() else 0
        entry = {
            "name": name,
            "path": str(backup_path),
            "source": str(source),
            "size_bytes": size,
            "compressed": compress,
            "created": datetime.now().isoformat()
        }
        self.manifest["backups"].append(entry)
        self._rotate()
        self._save_manifest()
        print(f"[+] Backup created: {backup_path} ({size:,} bytes)")
        return entry

    def _rotate(self):
        while len(self.manifest["backups"]) > self.max_backups:
            old = self.manifest["backups"].pop(0)
            old_path = Path(old["path"])
            if old_path.exists():
                if old_path.is_dir():
                    shutil.rmtree(old_path)
                else:
                    old_path.unlink()
                print(f"[-] Rotated old backup: {old['name']}")

    def restore_backup(self, name: str, target_dir: str) -> bool:
        entry = None
        for b in self.manifest["backups"]:
            if b["name"] == name:
                entry = b
                break
        if not entry:
            print(f"[-] Backup '{name}' not found")
            return False

        backup_path = Path(entry["path"])
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)

        if entry.get("compressed"):
            import tarfile
            with tarfile.open(backup_path, "r:gz") as tar:
                tar.extractall(target)
        else:
            shutil.copytree(backup_path, target, dirs_exist_ok=True)

        print(f"[+] Restored {name} to {target}")
        return True

    def list_backups(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": b["name"],
                "size": b["size_bytes"],
                "created": b["created"],
                "compressed": b["compressed"]
            }
            for b in self.manifest["backups"]
        ]

    def delete_backup(self, name: str) -> bool:
        for i, b in enumerate(self.manifest["backups"]):
            if b["name"] == name:
                path = Path(b["path"])
                if path.exists():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                self.manifest["backups"].pop(i)
                self._save_manifest()
                print(f"[+] Deleted backup: {name}")
                return True
        return False

    def get_total_size(self) -> int:
        return sum(b["size_bytes"] for b in self.manifest["backups"])

    def schedule_backup(self, source_dir: str, interval_hours: int = 24,
                        name_prefix: str = "scheduled") -> Dict[str, Any]:
        return {
            "source": source_dir,
            "interval_hours": interval_hours,
            "name_prefix": name_prefix,
            "next_run": (datetime.now() + timedelta(hours=interval_hours)).isoformat()
        }


def main():
    mgr = BackupManager()

    if len(sys.argv) < 2:
        print("Elysia Backup System")
        print("Commands: create <source> [name], list, restore <name> <target>, delete <name>, size")
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "create" and len(sys.argv) >= 3:
        name = sys.argv[3] if len(sys.argv) > 3 else None
        mgr.create_backup(sys.argv[2], name)
    elif cmd == "list":
        backups = mgr.list_backups()
        for b in backups:
            print(f"  {b['name']}: {b['size']:,} bytes ({b['created']})")
    elif cmd == "restore" and len(sys.argv) >= 4:
        mgr.restore_backup(sys.argv[2], sys.argv[3])
    elif cmd == "delete" and len(sys.argv) >= 3:
        mgr.delete_backup(sys.argv[2])
    elif cmd == "size":
        print(f"Total backup size: {mgr.get_total_size():,} bytes")


if __name__ == "__main__":
    main()
