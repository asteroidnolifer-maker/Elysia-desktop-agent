---
name: security-review
description: Review code for security flaws, with severity labels.
version: 1.0.0
author: Elysia
license: MIT
invocable: true
---

# Security review skill

Run before merge or after a risky diff.

## Procedure

1. Trace data flow from untrusted input to sinks (subprocess, file, network).
2. Check for: path traversal, command injection, secrets in logs, unsafe
   deserialization, missing authz, unbounded work.
3. Confirm Elysia tool permissions gate every external effect.
4. Report findings as `SEVERITY: path:line: note`.

Severity scale: BLOCKER / MAJOR / MINOR / NIT.

## Safety

- This skill surfaces issues; it never exploits them.
- Do not exfiltrate anything; redact secrets in any report.
