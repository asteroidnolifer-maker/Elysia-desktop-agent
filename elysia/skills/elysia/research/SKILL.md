---
name: research
description: Plan queries, gather sources, synthesize a cited report.
version: 1.0.0
author: Elysia
license: MIT
invocable: true
---

# Research skill

Use when the user asks an open-ended question that benefits from sources.

## Procedure

1. Break the question into 2-4 concrete search queries.
2. Gather up to the configured source limit (dedupe by URL).
3. Read each source's snippet; note the claim + citation.
4. Synthesize a report with: Executive Summary, Findings (each citing [n]),
   Next Steps. Never invent citations.

## Output format

The report is written to `workspace/reports/<topic>.md`; a copy is returned.

## Safety

- Prefer official/public sources; distrust unverifiable claims.
- Do not claim facts not supported by gathered sources.
