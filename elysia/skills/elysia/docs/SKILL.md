---
name: docs
description: Write accurate, concise documentation for a change.
version: 1.0.0
author: Elysia
license: MIT
invocable: true
---

# Docs skill

## Procedure

1. Understand the change from the task + diff.
2. Update the top-level README/docs index if a page is added.
3. Document: purpose, usage example, failure behavior, config options.
4. Keep examples runnable and stdlib-compatible.

## Safety

- Do not document secrets or internal paths with absolute host references.
- Language: active voice, sentence case, minimal emphasis.
