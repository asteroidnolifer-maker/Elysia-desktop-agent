#!/usr/bin/env python3
"""
Network Port Scanner for Elysia Pentesting Tools
TCP/UDP port scanning with service detection and banner grabbing.
"""
import socket
import threading
import sys
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed


class PortScanner:
    """Multi-threaded port scanner with service detection."""

    COMMON_PORTS = {
        21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS",
        80: "HTTP", 110: "POP3", 111: "RPCBind", 135: "MSRPC",
        139: "NetBIOS", 143: "IMAP", 443: "HTTPS", 445: "SMB",
        993: "IMAPS", 995: "POP3S", 1723: "PPTP", 3306: "MySQL",
        3389: "RDP", 5432: "PostgreSQL", 5900: "VNC", 8080: "HTTP-Proxy",
        8443: "HTTPS-Alt", 8888: "HTTP-Alt", 27017: "MongoDB"
    }

    def __init__(self, max_threads: int = 100, timeout: float = 1.0):
        self.max_threads = max_threads
        self.timeout = timeout
        self.results = []

    def scan_tcp(self, host: str, port: int) -> Dict[str, Any]:
        """Scan a single TCP port."""
        result = {
            "host": host,
            "port": port,
            "protocol": "tcp",
            "state": "closed",
            "service": self.COMMON_PORTS.get(port, "unknown"),
            "banner": None
        }

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((host, port))
            result["state"] = "open"

            # Banner grabbing
            try:
                sock.settimeout(2)
                banner = sock.recv(1024).decode("utf-8", errors="ignore").strip()
                if banner:
                    result["banner"] = banner[:200]
            except socket.timeout:
                pass

            sock.close()
        except (socket.timeout, ConnectionRefusedError, OSError):
            pass

        return result

    def scan_udp(self, host: str, port: int) -> Dict[str, Any]:
        """Scan a single UDP port."""
        result = {
            "host": host,
            "port": port,
            "protocol": "udp",
            "state": "closed",
            "service": self.COMMON_PORTS.get(port, "unknown"),
            "banner": None
        }

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            sock.sendto(b"\x00", (host, port))

            try:
                data, _ = sock.recvfrom(1024)
                result["state"] = "open"
                result["banner"] = data.decode("utf-8", errors="ignore")[:200]
            except socket.timeout:
                # UDP is tricky - timeout doesn't always mean closed
                result["state"] = "open|filtered"

            sock.close()
        except OSError:
            pass

        return result

    def scan_host(self, host: str, ports: List[int],
                  protocol: str = "tcp") -> List[Dict[str, Any]]:
        """Scan multiple ports on a host."""
        self.results = []
        scan_fn = self.scan_tcp if protocol == "tcp" else self.scan_udp

        with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
            futures = {
                executor.submit(scan_fn, host, port): port
                for port in ports
            }

            for future in as_completed(futures):
                result = future.result()
                if result["state"] == "open":
                    self.results.append(result)
                    print(f"  [OPEN] {result['port']}/{protocol} - {result['service']}")
                    if result["banner"]:
                        print(f"         Banner: {result['banner'][:50]}")

        return self.results

    def scan_range(self, host: str, start_port: int = 1,
                   end_port: int = 1024, protocol: str = "tcp") -> List[Dict[str, Any]]:
        """Scan a range of ports."""
        ports = list(range(start_port, end_port + 1))
        print(f"[*] Scanning {host} ports {start_port}-{end_port} ({protocol})...")
        start_time = datetime.now()

        results = self.scan_host(host, ports, protocol)

        duration = (datetime.now() - start_time).total_seconds()
        print(f"\n[+] Scan complete: {len(results)} open ports in {duration:.2f}s")

        return results

    def quick_scan(self, host: str) -> List[Dict[str, Any]]:
        """Quick scan of common ports."""
        common_ports = list(self.COMMON_PORTS.keys())
        print(f"[*] Quick scan of {host} (top {len(common_ports)} ports)...")
        return self.scan_host(host, common_ports)

    def detect_os(self, host: str) -> Dict[str, Any]:
        """Basic OS detection based on port patterns."""
        results = self.quick_scan(host)
        open_ports = {r["port"] for r in results}

        os_guess = {
            "os": "unknown",
            "confidence": 0,
            "evidence": []
        }

        # Windows patterns
        if 445 in open_ports and 3389 in open_ports:
            os_guess["os"] = "Windows"
            os_guess["confidence"] = 80
            os_guess["evidence"].append("SMB + RDP open")

        # Linux patterns
        elif 22 in open_ports and 80 in open_ports:
            os_guess["os"] = "Linux"
            os_guess["confidence"] = 70
            os_guess["evidence"].append("SSH + HTTP open")

        # macOS patterns
        elif 548 in open_ports or 631 in open_ports:
            os_guess["os"] = "macOS"
            os_guess["confidence"] = 60
            os_guess["evidence"].append("AFP/IPP services")

        return os_guess

    def generate_report(self, results: List[Dict[str, Any]],
                        host: str) -> str:
        """Generate a scan report."""
        report = []
        report.append(f"Port Scan Report for {host}")
        report.append(f"Generated: {datetime.now().isoformat()}")
        report.append("=" * 50)
        report.append(f"\nOpen ports found: {len(results)}\n")

        for r in sorted(results, key=lambda x: x["port"]):
            report.append(f"Port {r['port']}/{r['protocol']}: {r['service']}")
            if r["banner"]:
                report.append(f"  Banner: {r['banner'][:100]}")

        return "\n".join(report)


class VulnerabilityScanner:
    """Basic vulnerability scanner for common misconfigs."""

    VULN_CHECKS = [
        {
            "name": "Anonymous FTP",
            "port": 21,
            "check": lambda banner: "anonymous" in banner.lower() if banner else False,
            "severity": "HIGH",
            "description": "FTP allows anonymous access"
        },
        {
            "name": "Default SSH Banner",
            "port": 22,
            "check": lambda banner: banner and "OpenSSH" in banner and any(v in banner for v in ["6.", "7.0", "7.1"]),
            "severity": "MEDIUM",
            "description": "Outdated SSH version detected"
        },
        {
            "name": "HTTP Server Header Leak",
            "port": 80,
            "check": lambda banner: banner and ("Apache/2.2" in banner or "nginx/1.0" in banner),
            "severity": "LOW",
            "description": "Server version disclosed in banner"
        },
        {
            "name": "MySQL No Auth",
            "port": 3306,
            "check": lambda banner: banner and "mysql" in banner.lower(),
            "severity": "CRITICAL",
            "description": "MySQL accessible without authentication"
        },
        {
            "name": "Redis No Auth",
            "port": 6379,
            "check": lambda banner: banner and "redis" in banner.lower(),
            "severity": "CRITICAL",
            "description": "Redis accessible without authentication"
        }
    ]

    def __init__(self):
        self.scanner = PortScanner(timeout=2.0)

    def scan_and_check(self, host: str) -> List[Dict[str, Any]]:
        """Scan host and check for vulnerabilities."""
        print(f"[*] Vulnerability scan on {host}...")
        results = self.scanner.quick_scan(host)
        vulnerabilities = []

        for r in results:
            for vuln in self.VULN_CHECKS:
                if r["port"] == vuln["port"]:
                    if vuln["check"](r.get("banner")):
                        vulnerabilities.append({
                            "host": host,
                            "port": r["port"],
                            "vulnerability": vuln["name"],
                            "severity": vuln["severity"],
                            "description": vuln["description"],
                            "banner": r.get("banner")
                        })
                        print(f"  [!] {vuln['severity']}: {vuln['name']}")

        return vulnerabilities


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python port_scanner.py <host> [start_port] [end_port]")
        print("Example: python port_scanner.py 192.168.1.1 1 1000")
        sys.exit(1)

    host = sys.argv[1]
    start_port = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    end_port = int(sys.argv[3]) if len(sys.argv) > 3 else 1024

    scanner = PortScanner()
    results = scanner.scan_range(host, start_port, end_port)

    # Generate report
    report = scanner.generate_report(results, host)
    print("\n" + report)

    # Save report
    report_path = Path(__file__).parent / f"scan_report_{host.replace('.', '_')}.txt"
    report_path.write_text(report)
    print(f"\n[+] Report saved to {report_path}")


if __name__ == "__main__":
    main()
