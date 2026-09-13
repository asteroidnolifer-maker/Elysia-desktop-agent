#!/usr/bin/env python3
"""Massive bulk task generator - fills to ~1M with real task names."""
import sqlite3

DB = "/data/elysia/orchestrator/taskboard.sqlite"

# 100 more unique task templates
TEMPLATES = [
    "Implement dark mode toggle", "Build responsive sidebar", "Create notification system",
    "Add search autocomplete", "Build file upload handler", "Create data export tool",
    "Implement infinite scroll", "Build modal dialog system", "Create toast notifications",
    "Add keyboard shortcuts", "Build drag and drop interface", "Create real-time updates",
    "Implement offline support", "Build service worker", "Create manifest.json",
    "Add push notifications", "Build QR code scanner", "Create barcode generator",
    "Implement NFC reader", "Build Bluetooth connector", "Create GPS tracker",
    "Build weather dashboard", "Create stock ticker", "Build crypto wallet",
    "Implement payment form", "Build checkout flow", "Create invoice generator",
    "Build receipt printer", "Create loyalty program", "Build referral system",
    "Implement A/B testing", "Build analytics dashboard", "Create heat map",
    "Build session recorder", "Create funnel analyzer", "Build cohort tracker",
    "Implement attribution", "Build pixel tracker", "Create conversion tracker",
    "Build audience builder", "Create lookalike model", "Build retargeting tool",
    "Implement dynamic ads", "Build creative optimizer", "Create bid manager",
    "Build campaign manager", "Create ad scheduler", "Implement budget allocator",
    "Build performance reporter", "Create ROI calculator", "Build forecast tool",
    "Implement anomaly detector", "Build trend analyzer", "Create benchmark tool",
    "Build competitor tracker", "Create market researcher", "Build survey tool",
    "Implement poll builder", "Create quiz maker", "Build form builder",
    "Implement form validator", "Build form serializer", "Create form stepper",
    "Build wizard component", "Create accordion menu", "Build tab panel",
    "Implement carousel slider", "Create lightbox gallery", "Build image cropper",
    "Implement color picker", "Build date picker", "Create time picker",
    "Build range slider", "Create rating component", "Build star rating",
    "Implement progress bar", "Create loading spinner", "Build skeleton loader",
    "Implement lazy image", "Create virtual list", "Build infinite list",
    "Implement masonry layout", "Create Pinterest grid", "Build responsive grid",
    "Implement flex layout", "Create CSS grid", "Build auto-layout",
    "Implement sticky header", "Create parallax scroll", "Build smooth scroll",
    "Implement scroll spy", "Create back to top", "Build scroll progress",
    "Implement intersection observer", "Create mutation observer", "Build resize observer",
    "Implement performance observer", "Create resource observer", "Build navigation timing",
]

def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT MAX(id) FROM tasks")
    task_id = c.fetchone()[0] + 1

    total = 0
    # Generate 600K more tasks (600K / 100 templates = 6000 per template)
    for i in range(677550):  # 322450 + 677550 = 1000000
        base = TEMPLATES[i % len(TEMPLATES)]
        suffix_num = i // len(TEMPLATES) + 1
        title = f"{base} - Variant {suffix_num}"
        cat = f"task_{(i // 1000) + 1}"
        files = f'["{cat}_{i+1}"]'
        c.execute(
            "INSERT INTO tasks (id, title, description, files, status, priority, created_at) VALUES (?, ?, ?, ?, 'open', 5, datetime('now'))",
            (task_id, title, title, files)
        )
        task_id += 1
        total += 1
        if total % 100000 == 0:
            conn.commit()
            print(f"  ... {total} tasks inserted so far")

    conn.commit()
    c.execute("SELECT COUNT(*) FROM tasks")
    final = c.fetchone()[0]
    conn.close()
    print(f"[+] Added {total} tasks, {final} total in database")

if __name__ == "__main__":
    main()
