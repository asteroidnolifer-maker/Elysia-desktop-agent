---
name: planner
description: Turn a goal into an ordered, dependency-aware task graph for the Elysia pipeline.
version: 1.0.0
author: Elysia
license: MIT
invocable: true
---

# Planner skill

Use when a new user goal arrives or a large task needs decomposition.

## Procedure

1. Restate the goal as one or two concrete deliverables.
2. List the minimal ordered work items (`- <title> | <detail>`).
3. Mark explicit dependencies (`Dependencies: <id> -> <id>`).
4. Assign an agent role to each item (implementer, tester, code_reviewer,
   security_reviewer, documentation_agent, research_agent).
5. If a step has no implementation surface, drop it; no busywork.

## Safety

- Planning is read-only.
- Never propose destructive actions the user did not ask for.
- Declare owned files per task so writes stay within the workspace boundary.
