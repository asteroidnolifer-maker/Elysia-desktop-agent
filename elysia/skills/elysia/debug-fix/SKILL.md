---
name: debug-fix
description: Reproduce, root-cause, apply minimal fix, verify.
version: 1.0.0
author: Elysia
license: MIT
invocable: true
---

# Debug-fix skill

## Procedure

1. Reproduce the bug; capture the exact failing input and output.
2. Form 2-3 hypotheses for the root cause; rank by likelihood.
3. Find the minimal evidence that confirms the top hypothesis.
4. Apply the minimal fix.
5. Re-run the failing case; then run the full suite.
6. Write a regression test if one does not exist.

## Safety

- Only modify files owned by the task.
- If the fix would conflict with unrelated user changes, stop and report.
