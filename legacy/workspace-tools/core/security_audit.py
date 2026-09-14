#!/usr/bin/env python3
"""
Elysia Security Auditor - Task 1211
Security scanning, vulnerability detection, and hardening recommendations.
"""
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


class SecurityAuditor:
    def __init__(self):
        self.findings: List[Dict[str, Any]] = []

    def scan_file(self, filepath: str) -> List[Dict[str, Any]]:
        path = Path(filepath)
        try:
            content = path.read_text(errors="ignore")
        except Exception:
            return []

        findings = []
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            # Hardcoded secrets
            if re.search(r'(password|secret|api_key|token)\s*=\s*["\'][^"\']{8,}', line, re.I):
                findings.append({"file": str(path), "line": i, "severity": "critical",
                                "issue": "Hardcoded secret detected"})
            # SQL injection
            if re.search(r'execute\(.*%s|execute\(.*\.format|f".*SELECT.*{', line):
                findings.append({"file": str(path), "line": i, "severity": "high",
                                "issue": "Potential SQL injection"})
            # Eval/exec
            if re.search(r'\beval\s*\(|\bexec\s*\(', line):
                findings.append({"file": str(path), "line": i, "severity": "high",
                                "issue": "eval/exec usage (code injection risk)"})
            # Insecure HTTP
            if re.search(r'http://(?!localhost|127\.0\.0\.1)', line):
                findings.append({"file": str(path), "line": i, "severity": "medium",
                                "issue": "Insecure HTTP usage"})
            # Debug mode
            if re.search(r'DEBUG\s*=\s*True', line):
                findings.append({"file": str(path), "line": i, "severity": "medium",
                                "issue": "Debug mode enabled"})
            # Weak crypto
            if re.search(r'md5\(|sha1\(', line):
                findings.append({"file": str(path), "line": i, "severity": "medium",
                                "issue": "Weak hash algorithm"})

        self.findings.extend(findings)
        return findings

    def scan_directory(self, directory: str) -> Dict[str, Any]:
        self.findings = []
        for py_file in Path(directory).rglob("*.py"):
            if ".data" in str(py_file) or "__pycache__" in str(py_file):
                continue
            self.scan_file(str(py_file))

        by_severity = {}
        for f in self.findings:
            sev = f["severity"]
            by_severity[sev] = by_severity.get(sev, 0) + 1

        return {
            "total_findings": len(self.findings),
            "by_severity": by_severity,
            "findings": self.findings
        }

    def generate_report(self, results: Dict[str, Any]) -> str:
        lines = ["=" * 50, "SECURITY AUDIT REPORT", "=" * 50, ""]
        lines.append(f"Total findings: {results['total_findings']}")
        for sev, count in results.get("by_severity", {}).items():
            lines.append(f"  {sev}: {count}")
        lines.append("")
        for f in results.get("findings", []):
            lines.append(f"[{f['severity'].upper()}] {f['file']}:{f['line']} - {f['issue']}")
        if not results.get("findings"):
            lines.append("No security issues found.")
        return "\n".join(lines)

    def get_hardening_checklist(self) -> List[str]:
        return [
            "Enable HTTPS for all external connections",
            "Implement rate limiting on API endpoints",
            "Add input validation on all user inputs",
            "Use parameterized queries for database access",
            "Enable CSRF protection on forms",
            "Implement Content Security Policy headers",
            "Rotate secrets and API keys regularly",
            "Enable audit logging for sensitive operations",
            "Set secure cookie flags (HttpOnly, Secure, SameSite)",
            "Implement proper authentication and authorization"
        ]


def main():
    auditor = SecurityAuditor()
    if len(sys.argv) < 2:
        print("Elysia Security Auditor")
        print("Commands: scan <dir>, checklist")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "scan" and len(sys.argv) >= 3:
        results = auditor.scan_directory(sys.argv[2])
        print(auditor.generate_report(results))
    elif cmd == "checklist":
        for item in auditor.get_hardening_checklist():
            print(f"  [ ] {item}")


if __name__ == "__main__":
    main()
