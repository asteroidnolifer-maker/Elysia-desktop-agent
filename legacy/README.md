# Legacy workspace tools + mass-task generators

This subtree holds model-generated, one-off tool scripts from the original
Elysia codebase. They are **not** part of the active runtime:

- They contain hard-coded absolute paths like `/data/elysia/...` that do not
  exist on other machines.
- Several modules perform unsafe operations (port scanning, credential
  cracking, `shell=True` subprocess invocation, automatic git pushes) with no
  permissioning layer and must never be reachable through the Elysia agent
  pipeline.
- The mass-task generators were used once to seed a large SQLite board.

The canonical, supported runtime lives under `elysia/core`, `orchestrator/`,
`elysia/`, `tests/` and `docs/`.

## What moved here

| Original path                        | Why                                            |
|--------------------------------------|------------------------------------------------|
| `workspace/tools/*`                  | legacy domain scripts + unsafe helpers         |
| `scripts/generate_*tasks*.py`        | bulk task board seeding (machine-specific DB)  |
| `runtime/restore-model.sh`           | old download/restore flow with absolute paths  |

## Re-enabling

If you need one of these scripts for inspection, read it, fix the paths and
the unsafe patterns first, and wrap any execution behind the permissioned tool
layer (`elysia.core.tools`). Do not import them from the agent pipeline.