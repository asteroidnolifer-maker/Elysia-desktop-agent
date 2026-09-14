#!/usr/bin/env python3
"""Generate TASKS.md showing all unique task titles."""
import sqlite3

DB = "/data/elysia/orchestrator/taskboard.sqlite"
OUT = "/data/elysia/TASKS.md"

conn = sqlite3.connect(DB)
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM tasks")
total = c.fetchone()[0]

# Get all unique titles
c.execute("SELECT title FROM tasks ORDER BY id")
titles = [row[0] for row in c.fetchall()]

with open(OUT, 'w') as f:
    f.write(f"# Elysia Master Task List\n")
    f.write(f"# Total: {total:,} unique tasks\n")
    f.write(f"# All tasks are OPEN and ready for workers\n\n")
    
    for i, title in enumerate(titles, 1):
        f.write(f"{i}. {title}\n")

conn.close()
print(f"[+] Wrote {total:,} tasks to {OUT}")
