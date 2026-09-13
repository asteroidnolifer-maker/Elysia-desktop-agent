#!/usr/bin/env python3
"""
Vulnerability Scanner for Elysia Pentesting Tools
Checks common CVEs, misconfigs, and security weaknesses.
"""
import socket
import ssl
import subprocess
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path


class VulnerabilityScanner:
    """Scan for common vulnerabilities and misconfigurations."""

    def __init__(self):
        self.findings = []

    def scan_banner_grab(self, host: str, port: int) -> Dict[str, Any]:
        """Grab service banner for version detection."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((host, port))

            # Send probe
            sock.send(b"HEAD / HTTP/1.0\r\n\r\n")
            banner = sock.recv(1024).decode("utf-8", errors="ignore")
            sock.close()

            return {"port": port, "banner": banner.strip(), "vulnerable": self._check_banner_vulns(banner)}
        except Exception as e:
            return {"port": port, "error": str(e)}

    def _check_banner_vulns(self, banner: str) -> List[Dict[str, Any]]:
        """Check banner for known vulnerabilities."""
        vulns = []
        banner_lower = banner.lower()

        # Apache vulnerabilities
        if "apache/2.2" in banner_lower:
            vulns.append({
                "cve": "CVE-2021-41773",
                "severity": "CRITICAL",
                "description": "Apache 2.2 - Path traversal vulnerability",
                "affected": "Apache 2.2.x < 2.2.34"
            })

        # nginx vulnerabilities
        if "nginx/1.0" in banner_lower or "nginx/1.1" in banner_lower:
            vulns.append({
                "cve": "CVE-2013-2028",
                "severity": "HIGH",
                "description": "nginx - Stack buffer overflow",
                "affected": "nginx < 1.5.9"
            })

        # OpenSSH vulnerabilities
        if "openssh" in banner_lower:
            if "7.0" in banner_lower or "6." in banner_lower:
                vulns.append({
                    "cve": "CVE-2016-10009",
                    "severity": "HIGH",
                    "description": "OpenSSH - Agent forwarding vulnerability",
                    "affected": "OpenSSH < 7.1"
                })

        return vulns

    def scan_ssl_tls(self, host: str, port: int = 443) -> Dict[str, Any]:
        """Scan SSL/TLS configuration."""
        try:
            context = ssl.create_default_context()
            sock = socket.create_connection((host, port), timeout=5)
            ssl_sock = context.wrap_socket(sock, server_hostname=host)

            cert = ssl_sock.getpeercert()
            cipher = ssl_sock.cipher()
            version = ssl_sock.version()

            ssl_sock.close()

            issues = []

            # Check for weak protocols
            if version in ("TLSv1", "TLSv1.1"):
                issues.append({
                    "issue": "Weak TLS Version",
                    "severity": "HIGH",
                    "description": f"Server supports {version} (should be TLSv1.2+)"
                })

            # Check for weak ciphers
            if cipher and "RC4" in cipher[0]:
                issues.append({
                    "issue": "Weak Cipher",
                    "severity": "MEDIUM",
                    "description": f"Server uses RC4 cipher: {cipher[0]}"
                })

            # Check cert expiry
            not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
            days_until_expiry = (not_after - datetime.now()).days
            if days_until_expiry < 30:
                issues.append({
                    "issue": "Certificate Expiring Soon",
                    "severity": "MEDIUM",
                    "description": f"Certificate expires in {days_until_expiry} days"
                })

            return {
                "host": host,
                "port": port,
                "tls_version": version,
                "cipher": cipher[0] if cipher else "unknown",
                "cert_subject": dict(x[0] for x in cert.get("subject", [])),
                "cert_issuer": dict(x[0] for x in cert.get("issuer", [])),
                "cert_expiry": not_after.isoformat(),
                "issues": issues
            }

        except Exception as e:
            return {"host": host, "port": port, "error": str(e)}

    def scan_web_misconfigs(self, host: str, port: int = 80) -> List[Dict[str, Any]]:
        """Check for common web misconfigurations."""
        issues = []

        # Check for common sensitive paths
        sensitive_paths = [
            "/.env", "/.git/config", "/wp-config.php.bak",
            "/server-status", "/phpinfo.php", "/.htaccess",
            "/backup.sql", "/config.php", "/admin/"
        ]

        for path in sensitive_paths:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect((host, port))

                request = f"GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n"
                sock.send(request.encode())
                response = sock.recv(4096).decode("utf-8", errors="ignore")
                sock.close()

                if "200 OK" in response:
                    issues.append({
                        "path": path,
                        "severity": "HIGH",
                        "description": f"Sensitive file accessible: {path}",
                        "response_snippet": response[:200]
                    })
            except Exception:
                pass

        return issues

    def scan_directory_listing(self, host: str, port: int = 80) -> List[Dict[str, Any]]:
        """Check for directory listing enabled."""
        directories = ["/", "/admin/", "/backup/", "/uploads/", "/files/"]
        issues = []

        for directory in directories:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                sock.connect((host, port))

                request = f"GET {directory} HTTP/1.0\r\nHost: {host}\r\n\r\n"
                sock.send(request.encode())
                response = sock.recv(4096).decode("utf-8", errors="ignore")
                sock.close()

                if "Index of" in response or "Directory listing" in response:
                    issues.append({
                        "directory": directory,
                        "severity": "MEDIUM",
                        "description": f"Directory listing enabled at {directory}"
                    })
            except Exception:
                pass

        return issues

    def generate_report(self, host: str) -> str:
        """Generate vulnerability scan report."""
        report = []
        report.append("=" * 60)
        report.append("  VULNERABILITY SCAN REPORT")
        report.append(f"  Target: {host}")
        report.append(f"  Date: {datetime.now().isoformat()}")
        report.append("=" * 60)

        # SSL/TLS scan
        print(f"[*] Scanning SSL/TLS on {host}...")
        ssl_results = self.scan_ssl_tls(host)
        if "error" not in ssl_results:
            report.append(f"\n  SSL/TLS Configuration:")
            report.append(f"    Version: {ssl_results['tls_version']}")
            report.append(f"    Cipher: {ssl_results['cipher']}")
            if ssl_results.get("issues"):
                for issue in ssl_results["issues"]:
                    report.append(f"    [{issue['severity']}] {issue['issue']}: {issue['description']}")

        # Web misconfigs
        print(f"[*] Checking web misconfigs on {host}...")
        web_issues = self.scan_web_misconfigs(host)
        if web_issues:
            report.append(f"\n  Web Misconfigurations ({len(web_issues)} found):")
            for issue in web_issues[:10]:
                report.append(f"    [{issue['severity']}] {issue['description']}")

        # Directory listing
        print(f"[*] Checking directory listing on {host}...")
        dir_issues = self.scan_directory_listing(host)
        if dir_issues:
            report.append(f"\n  Directory Listing ({len(dir_issues)} found):")
            for issue in dir_issues:
                report.append(f"    [{issue['severity']}] {issue['description']}")

        return "\n".join(report)


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Vulnerability Scanner")
        print("=" * 40)
        print("\nUsage: python vuln_scanner.py <host>")
        print("\nScans:")
        print("  - SSL/TLS configuration")
        print("  - Web misconfigurations")
        print("  - Directory listing")
        print("  - Banner vulnerabilities")
        sys.exit(1)

    host = sys.argv[1]
    scanner = VulnerabilityScanner()

    print(f"[*] Starting vulnerability scan on {host}...")
    report = scanner.generate_report(host)
    print("\n" + report)

    # Save report
    report_path = Path(__file__).parent / f"vuln_report_{host.replace('.', '_')}.txt"
    report_path.write_text(report)
    print(f"\n[+] Report saved to {report_path}")


if __name__ == "__main__":
    main()
