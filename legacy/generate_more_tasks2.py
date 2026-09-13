#!/usr/bin/env python3
"""Add more bulk tasks to reach ~1M total."""
import sqlite3

DB = "/data/elysia/orchestrator/taskboard.sqlite"

# More real task categories
BULK2 = {
    "code_quality": ["Refactor function for readability", "Extract duplicated code", "Add type hints to module", "Fix code smell", "Simplify conditional logic", "Remove dead code", "Add error handling", "Optimize hot path", "Add unit tests", "Update documentation"],
    "feature_impl": ["Add search functionality", "Implement pagination", "Create filter system", "Build sort mechanism", "Add export to CSV", "Implement import from JSON", "Create batch operation", "Build undo/redo system", "Add keyboard shortcuts", "Implement drag and drop"],
    "ui_polish": ["Fix alignment issue", "Improve spacing", "Update color scheme", "Add hover effects", "Fix responsive breakpoint", "Improve accessibility", "Add loading states", "Fix z-index issues", "Improve animations", "Update typography"],
    "integration": ["Add webhook support", "Implement OAuth flow", "Create API client", "Build data sync", "Add payment processing", "Implement email service", "Create analytics hook", "Build notification system", "Add SSO integration", "Implement 2FA"],
    "performance_opt": ["Cache database queries", "Implement lazy loading", "Add pagination", "Optimize image loading", "Minify assets", "Enable gzip compression", "Implement CDN", "Optimize SQL queries", "Add connection pooling", "Implement virtual scrolling"],
    "bug_hunting": ["Fix memory leak", "Resolve race condition", "Fix null pointer", "Handle edge case", "Fix broken redirect", "Resolve timeout issue", "Fix data corruption", "Handle network error", "Fix UI glitch", "Resolve state issue"],
    "architecture": ["Decouple module dependency", "Implement plugin system", "Create adapter pattern", "Build facade layer", "Implement strategy pattern", "Create observer pattern", "Build command pattern", "Implement decorator pattern", "Create factory pattern", "Build proxy pattern"],
    "data_management": ["Implement data validation", "Create backup system", "Build data migration", "Implement versioning", "Create audit trail", "Build data export", "Implement data import", "Create data cleanup", "Build data enrichment", "Implement data deduplication"],
    "user_experience": ["Simplify onboarding flow", "Add progress indicators", "Improve error messages", "Create empty states", "Add confirmation dialogs", "Implement smart defaults", "Build contextual help", "Create tutorial system", "Add breadcrumbs", "Implement search UX"],
    "infrastructure": ["Set up monitoring", "Create alerting rules", "Build deployment pipeline", "Implement blue-green deploy", "Create rollback mechanism", "Build health checks", "Implement circuit breaker", "Create rate limiting", "Build load balancing", "Implement auto-scaling"],
    "documentation": ["Write API reference", "Create user guide", "Build developer docs", "Write deployment guide", "Create troubleshooting guide", "Write changelog", "Build architecture docs", "Create README", "Write inline comments", "Build example repository"],
    "testing_expansion": ["Add integration tests", "Create end-to-end tests", "Build performance tests", "Implement security tests", "Create accessibility tests", "Build mobile tests", "Implement API tests", "Create database tests", "Build UI tests", "Implement load tests"],
    "mobile_opt": ["Optimize touch gestures", "Implement swipe actions", "Build pull-to-refresh", "Create bottom navigation", "Implement floating action", "Build snack bar notifications", "Create bottom sheets", "Implement modal dialogs", "Build tab navigation", "Create carousel component"],
    "realtime": ["Implement WebSocket server", "Build real-time notifications", "Create live collaboration", "Implement presence system", "Build live chat", "Create real-time dashboard", "Implement event streaming", "Build live feed", "Create real-time search", "Implement live updates"],
    "accessibility": ["Add ARIA labels", "Implement keyboard navigation", "Build screen reader support", "Create high contrast mode", "Implement focus management", "Build text resizing support", "Create reduced motion mode", "Implement color blind support", "Build voice navigation", "Implement switch access"],
    "internationalization": ["Add multi-language support", "Implement RTL layout", "Build date formatting", "Create currency converter", "Implement timezone handling", "Build number formatting", "Create address format handler", "Implement phone validation", "Build character encoding support", "Create translation management"],
    "devtools": ["Build Chrome extension", "Create VS Code extension", "Implement CLI tool", "Build debugging tool", "Create profiler tool", "Implement log viewer", "Build config editor", "Create schema validator", "Implement code generator", "Build scaffolding tool"],
    "content_features": ["Build WYSIWYG editor", "Create image gallery", "Implement video player", "Build audio player", "Create document viewer", "Implement map integration", "Build calendar component", "Create timeline view", "Implement kanban board", "Build spreadsheet view"],
    "collaboration": ["Implement real-time editing", "Build comment system", "Create approval workflow", "Implement task assignment", "Build activity tracking", "Create notification preferences", "Implement mention system", "Build file sharing", "Create version history", "Implement conflict resolution"],
    "compliance": ["Implement GDPR consent", "Build data export tool", "Create right to erasure", "Implement cookie consent", "Build privacy dashboard", "Create audit logging", "Implement access controls", "Build data retention policy", "Create breach notification", "Implement data processing agreement"],
}

def main():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT MAX(id) FROM tasks")
    task_id = c.fetchone()[0] + 1

    total = 0
    for cat, templates in BULK2.items():
        for i in range(4000):
            base = templates[i % len(templates)]
            suffix = f" #{i // len(templates) + 1}" if i >= len(templates) else ""
            title = base + suffix
            files = f'["{cat}_{i+1}"]'
            c.execute(
                "INSERT INTO tasks (id, title, description, files, status, priority, created_at) VALUES (?, ?, ?, ?, 'open', 5, datetime('now'))",
                (task_id, title, title, files)
            )
            task_id += 1
            total += 1

    conn.commit()
    c.execute("SELECT COUNT(*) FROM tasks")
    final = c.fetchone()[0]
    conn.close()
    print(f"[+] Added {total} tasks, {final} total in database")

if __name__ == "__main__":
    main()
