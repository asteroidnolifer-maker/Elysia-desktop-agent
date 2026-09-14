---
name: sqlmap
category: web
purpose: Automates detection and verification of SQL-injection flaws in web endpoints you own, so the finding can be reproduced and fixed.
package: sqlmap
risk: high
aliases: sqli, injection testing
---

sqlmap is a *verification* tool for a bug you already suspect: given a request
against an endpoint you own, it confirms whether a parameter is injectable and
characterizes it so developers can reproduce and patch the flaw.

Authorized use (defensive-first):
- verify a suspected injection in your own app's search parameter, then fix
  the query (parameterized statements) and re-run to confirm the fix.
- Elysia's own repos: any place the agent composes SQL with string
  interpolation (e.g. task-store queries) is a candidate to audit first.

The repo's skill gate (`elysia/core/skills.py`) marks this class of tooling
high-risk: skills invoking it stay quarantined unless explicitly enabled.
Only run against systems you own or have written authorization to test.
Install: `sudo apt install sqlmap` (Kali) or `pip install sqlmap`.
