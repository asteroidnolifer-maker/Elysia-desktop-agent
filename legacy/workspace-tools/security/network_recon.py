#!/usr/bin/env python3
"""
Network Reconnaissance Tools for Elysia Pentesting
DNS enumeration, WHOIS, subdomain scanning, OS detection.
"""
import socket
import struct
import json
import sys
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime


class DNSRecon:
    """DNS enumeration and reconnaissance."""

    COMMON_RECORDS = ["A", "AAAA", "MX", "NS", "TXT", "CNAME", "SOA"]

    def __init__(self):
        self.results = {}

    def dns_lookup(self, domain: str, record_type: str = "A") -> Dict[str, Any]:
        import subprocess
        try:
            result = subprocess.run(["nslookup", "-type=" + record_type, domain],
                                   capture_output=True, text=True, timeout=10)
            return {"domain": domain, "type": record_type, "result": result.stdout, "success": True}
        except Exception as e:
            return {"domain": domain, "type": record_type, "error": str(e), "success": False}

    def enumerate_records(self, domain: str) -> Dict[str, Any]:
        records = {}
        for rtype in self.COMMON_RECORDS:
            records[rtype] = self.dns_lookup(domain, rtype)
        return {"domain": domain, "records": records, "timestamp": datetime.now().isoformat()}

    def find_mail_servers(self, domain: str) -> List[Dict[str, Any]]:
        result = self.dns_lookup(domain, "MX")
        servers = []
        for line in result.get("result", "").split("\n"):
            if "mail exchanger" in line.lower() or "mx" in line.lower():
                parts = line.split("=") if "=" in line else line.split()
                if len(parts) > 1:
                    servers.append({"priority": 10, "server": parts[-1].strip()})
        return servers

    def find_subdomains(self, domain: str, wordlist: List[str] = None) -> List[Dict[str, Any]]:
        common = wordlist or [
            "www", "mail", "ftp", "admin", "dev", "staging", "test",
            "api", "docs", "blog", "shop", "app", "portal", "vpn",
            "cdn", "media", "static", "images", "assets", "files"
        ]
        found = []
        for sub in common:
            subdomain = f"{sub}.{domain}"
            try:
                ip = socket.gethostbyname(subdomain)
                found.append({"subdomain": subdomain, "ip": ip, "found": True})
            except socket.gaierror:
                pass
        return found


class WhoisLookup:
    """WHOIS domain information lookup."""

    def lookup(self, domain: str) -> Dict[str, Any]:
        import subprocess
        try:
            result = subprocess.run(["whois", domain], capture_output=True, text=True, timeout=15)
            info = {"domain": domain, "raw": result.stdout, "parsed": self._parse_whois(result.stdout)}
            return info
        except FileNotFoundError:
            return {"domain": domain, "error": "whois command not installed"}
        except Exception as e:
            return {"domain": domain, "error": str(e)}

    def _parse_whois(self, raw: str) -> Dict[str, str]:
        parsed = {}
        for line in raw.split("\n"):
            if ":" in line:
                parts = line.split(":", 1)
                key = parts[0].strip().lower()
                value = parts[1].strip()
                if key in ["registrar", "creation date", "registry expiry date",
                           "name server", "updated date", "status", "registrant organization"]:
                    parsed[key] = value
        return parsed


class OSDetector:
    """OS detection based on network fingerprints."""

    def detect_by_ttl(self, host: str) -> Dict[str, Any]:
        import subprocess
        try:
            result = subprocess.run(["ping", "-c", "1", "-W", "2", host],
                                   capture_output=True, text=True, timeout=5)
            for line in result.stdout.split("\n"):
                if "ttl=" in line:
                    ttl = int(line.split("ttl=")[1].split()[0])
                    os_guess = "Unknown"
                    if ttl <= 64:
                        os_guess = "Linux/macOS"
                    elif ttl <= 128:
                        os_guess = "Windows"
                    elif ttl <= 255:
                        os_guess = "Network Device/Solaris"
                    return {"host": host, "ttl": ttl, "os_guess": os_guess}
            return {"host": host, "error": "No TTL found"}
        except Exception as e:
            return {"host": host, "error": str(e)}

    def detect_by_ports(self, host: str) -> Dict[str, Any]:
        common_ports = {22: "SSH", 3389: "RDP", 445: "SMB", 135: "MSRPC", 548: "AFP"}
        open_services = []
        for port in common_ports:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                if sock.connect_ex((host, port)) == 0:
                    open_services.append({"port": port, "service": common_ports[port]})
                sock.close()
            except Exception:
                pass

        os_guess = "Unknown"
        open_ports = {s["port"] for s in open_services}
        if 3389 in open_ports and 445 in open_ports:
            os_guess = "Windows"
        elif 22 in open_ports:
            os_guess = "Linux/macOS"
        elif 548 in open_ports:
            os_guess = "macOS"

        return {"host": host, "open_services": open_services, "os_guess": os_guess}


class StealthScanner:
    """Stealth scanning techniques."""

    def __init__(self):
        self.scan_history = []

    def syn_scan(self, host: str, port: int) -> Dict[str, Any]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            state = "open" if result == 0 else "closed"
            self.scan_history.append({"host": host, "port": port, "state": state, "technique": "SYN"})
            return {"host": host, "port": port, "state": state}
        except Exception as e:
            return {"host": host, "port": port, "error": str(e)}

    def null_scan(self, host: str, port: int) -> Dict[str, Any]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((host, port))
            sock.send(b"\x00\x00\x00\x00")
            try:
                response = sock.recv(1024)
                state = "open" if len(response) > 0 else "closed"
            except socket.timeout:
                state = "open|filtered"
            sock.close()
            return {"host": host, "port": port, "state": state, "technique": "NULL"}
        except Exception as e:
            return {"host": host, "port": port, "error": str(e)}

    def fin_scan(self, host: str, port: int) -> Dict[str, Any]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((host, port))
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            import struct
            sock.sendto(struct.pack('!BBHHHBBHII', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), (host, port))
            try:
                response = sock.recv(1024)
                state = "closed" if len(response) > 0 else "open"
            except socket.timeout:
                state = "open|filtered"
            sock.close()
            return {"host": host, "port": port, "state": state, "technique": "FIN"}
        except Exception as e:
            return {"host": host, "port": port, "error": str(e)}


def main():
    if len(sys.argv) < 2:
        print("Network Recon Tools")
        print("=" * 40)
        print("\nCommands:")
        print("  dns <domain>          - DNS enumeration")
        print("  whois <domain>        - WHOIS lookup")
        print("  subdomains <domain>  - Subdomain scan")
        print("  os-ttl <host>         - OS detection via TTL")
        print("  os-ports <host>       - OS detection via ports")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "dns" and len(sys.argv) >= 3:
        recon = DNSRecon()
        result = recon.enumerate_records(sys.argv[2])
        for rtype, data in result["records"].items():
            if data.get("success"):
                print(f"  {rtype}: {data['result'][:100]}")

    elif cmd == "whois" and len(sys.argv) >= 3:
        lookup = WhoisLookup()
        result = lookup.lookup(sys.argv[2])
        for key, value in result.get("parsed", {}).items():
            print(f"  {key}: {value}")

    elif cmd == "subdomains" and len(sys.argv) >= 3:
        recon = DNSRecon()
        found = recon.find_subdomains(sys.argv[2])
        for f in found:
            print(f"  {f['subdomain']} -> {f['ip']}")

    elif cmd == "os-ttl" and len(sys.argv) >= 3:
        detector = OSDetector()
        result = detector.detect_by_ttl(sys.argv[2])
        print(f"  OS: {result.get('os_guess', 'Unknown')} (TTL: {result.get('ttl', '?')})")

    elif cmd == "os-ports" and len(sys.argv) >= 3:
        detector = OSDetector()
        result = detector.detect_by_ports(sys.argv[2])
        print(f"  OS: {result.get('os_guess', 'Unknown')}")
        for s in result.get("open_services", []):
            print(f"    Port {s['port']}: {s['service']}")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
