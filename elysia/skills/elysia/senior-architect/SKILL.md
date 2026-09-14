---
name: senior-architect
description: Hard review of an architecture with simplification and portability focus.
version: 1.0.0
author: Elysia
license: MIT
invocable: true
---

# Senior architect skill

Second-opinion review of an architecture before implementation.

## Procedure

1. Collapse 3+ layers of indirection.
2. Check for vendor lock-in; prefer provider-agnostic interfaces.
3. Verify the plan handles partial failure (timeouts, lease expiry).
4. Confirm every data path is bounded (char limits, file sizes, queue depth).
5. Approve, or return a short concrete change list — never a rewrite.

## Output format

Return `## Verdict` (`APPROVE`/`AMEND`) then `## Required changes`.

## Safety

- Read-only; no code changes.
- Flag any capability request that exceeds the resource budget.
