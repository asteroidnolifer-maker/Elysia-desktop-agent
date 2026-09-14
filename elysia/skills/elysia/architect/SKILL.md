---
name: architect
description: Produce a concise architecture (modules, data flow, risks) for a planned feature.
version: 1.0.0
author: Elysia
license: MIT
invocable: true
---

# Architect skill

Turn a plan into an architecture implementers can follow.

## Procedure

1. Identify the modules and their public boundaries.
2. Describe data flow between modules (an ASCII diagram suffices).
3. State the failure/retry model and where state lives.
4. List risks and open questions; pick the simplest defensible option.

## Output format

Return markdown with only `## Modules`, `## Data flow`, `## Risks`.

## Safety

- Prefer stdlib-only solutions where the platform requires it.
- Keep each module small enough to implement in < 400 LOC.
