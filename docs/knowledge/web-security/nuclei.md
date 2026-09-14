---
name: nuclei
category: web-security
purpose: Template-based vulnerability scanning of web applications you own, with a huge community CVE/exposure library.
package: nuclei
risk: medium
aliases: vuln scanner, template scanner, cve scan
---

Nuclei runs community/maintained templates against web targets to detect known
vulnerabilities and misconfigurations. Elysia's stance: **continuous self-
scanning** — schedule it against your own staging and production to catch
regressions before they are exploited.

Authorized use:
- your own apps: `nuclei -l internal_hosts.txt -t cves/ -severity medium,high`
- CI integration: fail builds that reintroduce a known exposure class.
- scope documents everything: targets must be yours or in a written contract.

Destructive/exploit templates exist; run those only in isolated staging, never
against production data you cannot restore. Install:
`go install -v github.com/projectdiscovery/nuclei/v2/cmd/nuclei@latest`
