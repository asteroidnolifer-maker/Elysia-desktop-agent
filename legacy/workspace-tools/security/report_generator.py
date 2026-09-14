#!/usr/bin/env python3
"""
Report Generator for Elysia Pentesting
Generate vulnerability reports in various formats.
"""
import json
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime


class PentestReport:
    """Generate penetration testing reports."""

    def __init__(self, output_dir: str = None):
        self.output_dir = Path(output_dir or Path(__file__).parent / "reports")
        self.output_dir.mkdir(exist_ok=True)

    def generate_report(self, scan_results: Dict[str, Any], target: str) -> str:
        report = []
        report.append("=" * 70)
        report.append("  PENETRATION TEST REPORT")
        report.append(f"  Target: {target}")
        report.append(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 70)

        findings = scan_results.get("findings", [])
        report.append(f"\n  EXECUTIVE SUMMARY")
        report.append(f"  Total findings: {len(findings)}")

        severity_count = {}
        for f in findings:
            sev = f.get("severity", "UNKNOWN")
            severity_count[sev] = severity_count.get(sev, 0) + 1

        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            if sev in severity_count:
                report.append(f"    {sev}: {severity_count[sev]}")

        report.append(f"\n  DETAILED FINDINGS")
        report.append("-" * 70)

        for i, finding in enumerate(findings, 1):
            report.append(f"\n  Finding #{i}")
            report.append(f"    Type: {finding.get('type', 'Unknown')}")
            report.append(f"    Severity: {finding.get('severity', 'Unknown')}")
            report.append(f"    URL/Host: {finding.get('url', finding.get('host', 'N/A'))}")
            report.append(f"    Description: {finding.get('description', finding.get('evidence', 'N/A'))}")
            if finding.get("remediation"):
                report.append(f"    Remediation: {finding['remediation']}")

        report.append(f"\n  RECOMMENDATIONS")
        report.append("-" * 70)
        if severity_count.get("CRITICAL", 0) > 0:
            report.append("  [!] URGENT: Address CRITICAL findings immediately")
        report.append("  - Implement security headers on all web applications")
        report.append("  - Regularly update and patch all systems")
        report.append("  - Conduct regular security assessments")
        report.append("  - Implement network segmentation")

        report.append(f"\n  END OF REPORT")
        report.append("=" * 70)

        report_text = "\n".join(report)

        filename = f"pentest_report_{target.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        filepath = self.output_dir / filename
        filepath.write_text(report_text)
        print(f"[+] Report saved: {filepath}")
        return report_text

    def generate_html_report(self, scan_results: Dict[str, Any], target: str) -> str:
        findings = scan_results.get("findings", [])
        severity_colors = {"CRITICAL": "#dc3545", "HIGH": "#fd7e14", "MEDIUM": "#ffc107", "LOW": "#28a745", "INFO": "#17a2b8"}

        findings_html = ""
        for f in findings:
            color = severity_colors.get(f.get("severity", ""), "#666")
            findings_html += f"""
            <div class="finding" style="border-left: 4px solid {color}; padding: 10px; margin: 10px 0;">
                <h3>{f.get('type', 'Unknown')} <span style="color:{color}">[{f.get('severity', 'Unknown')}]</span></h3>
                <p><strong>Target:</strong> {f.get('url', f.get('host', 'N/A'))}</p>
                <p><strong>Description:</strong> {f.get('description', f.get('evidence', 'N/A'))}</p>
                {f'<p><strong>Remediation:</strong> {f["remediation"]}</p>' if f.get('remediation') else ''}
            </div>"""

        html = f"""<!DOCTYPE html>
<html><head><title>Pentest Report - {target}</title>
<style>
    body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
    .container {{ max-width: 900px; margin: 0 auto; background: white; padding: 30px; }}
    h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
    h2 {{ color: #555; margin-top: 30px; }}
    .summary {{ background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }}
    .finding {{ background: white; border-radius: 5px; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
</style></head>
<body><div class="container">
    <h1>Penetration Test Report</h1>
    <p><strong>Target:</strong> {target} | <strong>Date:</strong> {datetime.now().strftime('%Y-%m-%d')}</p>
    <div class="summary"><h2>Executive Summary</h2><p>Total findings: {len(findings)}</p></div>
    <h2>Detailed Findings</h2>{findings_html}
    <h2>Recommendations</h2>
    <ul><li>Address critical findings immediately</li><li>Implement security headers</li><li>Regular patching</li></ul>
</div></body></html>"""

        filename = f"pentest_report_{target.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        filepath = self.output_dir / filename
        filepath.write_text(html)
        print(f"[+] HTML report saved: {filepath}")
        return str(filepath)

    def export_json(self, scan_results: Dict[str, Any], target: str) -> str:
        filename = f"pentest_report_{target.replace('.', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self.output_dir / filename
        filepath.write_text(json.dumps(scan_results, indent=2))
        print(f"[+] JSON report saved: {filepath}")
        return str(filepath)


class ReportTemplates:
    """Pre-built report templates."""

    @staticmethod
    def web_application_template() -> Dict[str, Any]:
        return {
            "sections": ["Executive Summary", "Scope", "Methodology", "Findings", "Risk Assessment", "Recommendations", "Appendix"],
            "finding_fields": ["type", "severity", "url", "parameter", "payload", "evidence", "remediation"],
            "severity_definitions": {
                "CRITICAL": "Immediate risk, requires urgent remediation",
                "HIGH": "Significant risk, should be addressed quickly",
                "MEDIUM": "Moderate risk, should be planned for remediation",
                "LOW": "Minor risk, can be addressed in regular maintenance",
                "INFO": "Informational finding, no immediate risk"
            }
        }

    @staticmethod
    def network_scan_template() -> Dict[str, Any]:
        return {
            "sections": ["Executive Summary", "Target Information", "Scan Results", "Vulnerabilities", "Services", "Recommendations"],
            "finding_fields": ["host", "port", "service", "version", "vulnerability", "severity", "remediation"]
        }


def main():
    report_gen = PentestReport()

    if len(sys.argv) < 2:
        print("Report Generator")
        print("=" * 40)
        print("\nCommands:")
        print("  generate <json_file> <target>  - Generate text report")
        print("  html <json_file> <target>      - Generate HTML report")
        print("  json <json_file> <target>      - Export JSON report")
        print("  templates                      - Show templates")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "generate" and len(sys.argv) >= 4:
        with open(sys.argv[2]) as f:
            data = json.load(f)
        report_gen.generate_report(data, sys.argv[3])

    elif cmd == "html" and len(sys.argv) >= 4:
        with open(sys.argv[2]) as f:
            data = json.load(f)
        report_gen.generate_html_report(data, sys.argv[3])

    elif cmd == "json" and len(sys.argv) >= 4:
        with open(sys.argv[2]) as f:
            data = json.load(f)
        report_gen.export_json(data, sys.argv[3])

    elif cmd == "templates":
        web = ReportTemplates.web_application_template()
        print("\nWeb Application Template:")
        print(f"  Sections: {', '.join(web['sections'])}")
        net = ReportTemplates.network_scan_template()
        print("\nNetwork Scan Template:")
        print(f"  Sections: {', '.join(net['sections'])}")

    else:
        print("Unknown command")


if __name__ == "__main__":
    main()
