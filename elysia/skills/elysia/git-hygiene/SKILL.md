---
name: git-hygiene
description: Clean commits, secrets-free staging, safe checkpoints and rollbacks.
version: 1.0.0
author: Elysia
license: MIT
invocable: true
---

# Git-hygiene skill

## Procedure

1. Check status/conflicts before any commit.
2. Stage explicit paths, never `git add .`.
3. Run the secret-redaction check on staged diff.
4. Commit with a short imperative message (`scope: change`).
5. On rollback requests, use `--soft` first (keeps working files).

## Safety

- Never commit credentials, runtime state, or build artifacts.
- Never auto-push unless the user explicitly asks.
