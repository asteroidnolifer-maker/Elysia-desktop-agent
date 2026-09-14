---
name: test-driven
description: Write a failing test first, then the minimal implementation, then verify green.
version: 1.0.0
author: Elysia
license: MIT
invocable: true
---

# Test-driven skill

## Procedure

1. Understand the acceptance criteria.
2. Write the smallest failing test.
3. Run it (via project test command) and confirm RED.
4. Implement the minimal change to make it GREEN.
5. Run the full test suite to confirm no regressions.
6. Refactor while keeping GREEN.

## Safety

- Never skip the suite.
- If tests cannot run in this environment, say so instead of faking results.
