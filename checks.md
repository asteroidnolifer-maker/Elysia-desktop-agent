# Elysia deep audit — checks

Verification envelope for the deep-audit + hardening + feature-expansion phases.
Run these in order; the whole envelope must stay green.

## 1. Unit / integration suite

```bash
python3 -m unittest discover -s tests -v
```

Expected: **all tests pass** (currently 181), including the
`tests/test_features.py` bundle covering context budgeting, telemetry/cost,
tool risk gating, computer permissions + shell gating, skills risk assessment
(intent-based, false-positive free), templates expansion, research engine
offline + deep, openreacher module, project intel, plugins allow-listing,
doctor, git checkpoint/rollback, the rewired server `/api/agent`,
`tests/test_integration.py` — the full runtime call graph (goal ->
persistent board tasks -> scheduler atomic reservation -> AgentPipeline
`solve_task` -> real Workspace write -> completion), concurrency caps,
reservation-slot release on cancel, provider failover within one task,
process-restart durability, and provider-failure handling — plus the new
`tests/test_providers_plus.py` bundle: provider preset catalog (cloud APIs +
CLI agents, credential-gated activation), config preset integration
(`ELYSIA_DISABLE_PRESETS`), prompt styles (worker contract preserved),
browser-login credential store (0600, env-wins, no secrets in output),
knowledge base (search, defensive context digest), and the HuggingFace
catalog/recommend/inference provider.

## 2. Compile check

```bash
python3 -m py_compile orchestrator/server.py elysia/cli.py elysia/core/*.py \
    tests/test_features.py
```

## 3. Health + portability

```bash
./bin/elysia doctor     # workspace, providers, api_port, python_deps, git
./bin/elysia audit      # no hardcoded legacy absolute paths in source
./bin/elysia providers --catalog   # provider catalog: what is active/missing
./bin/elysia knowledge list        # vendored security docs indexed
./bin/elysia prompt                # prompt styles listed
```

Expected: `Result: all checks passed`, `audit passed`, and clean output from
the three new read-only commands (no tracebacks with zero credentials).

## 4. Skills (vendor + Elysia-native)

```bash
./bin/elysia skills list
```

Expected: 16 curated vendor skills (code-review, autofix, git-commit,
github-pr-creation/merge/review, systematic-debugging, senior-architect,
documentation, python, existing-repo, commit-hygiene, …) plus the 9
Elysia-native skills (planner, architect, senior-architect, research,
security-review, test-driven, debug-fix, docs, git-hygiene).
Risk gating blocks destructive skills at import; `scripts/import_skills.py`
re-imports the PICK list from `agent-skills-collection`.

## 5. Deep research / openreacher

```bash
./bin/elysia research "Some question"                    # single-pass
./bin/elysia research "Some question" --deep --breadth 2 --depth 1
./bin/elysia orx "Some question"                         # alias for --deep
```

Expected: report to `workspace/reports/<topic>.md` (+ `.deep.md` in deep mode),
structured `[sources] N` printed. Offline (no provider) degrades gracefully.

## 6. Server endpoints against the new core

`orchestrator/server.py` `/api/agent`, `/api/chat` (research/elysia intents)
now call `elysia.core.server_api` (bounded threads, structured results,
graceful enqueue when providers are down). Legacy `elysia_agent` imports are
gone. Covered by `tests/test_server_api.py`.

## Security posture

- No hardcoded absolute host paths in source (audit enforces).
- Runtime state (`state/`, `workspace/reports/`, `*.sqlite`, logs, pids) is
  gitignored.
- Tools: risk levels + dry-run previews + permission gate (`tools.py`).
- Computer: path traversal blocked, shell gated (`computer.py`).
- Skills: intent-based risk assessment, destructive skills quarantined by
  default (`skills.py`).
- Config: central validated config with secret redaction (`config.py`).
- Provider presets: credential-gated activation, keys only from env or the
  0600 git-ignored `config/providers.env`; catalog output never prints keys.
- Security tooling: knowledge-first (`docs/knowledge/kali-tools/` +
  `knowledge.py`); policy + agent prohibitions in
  `docs/security/SECURITY_TOOLING.md`; no attack tooling vendored.

## Manual test guide

`howtotest.md` walks every new surface (catalog, login, hf, knowledge,
prompt styles) offline-first, with optional connected checks.

## Git hygiene

- `bin/elysia checkpoint <msg>` — safe checkpoint
- `bin/elysia rollback <sha> [--hard]` — rollback
- No `git add .`; stage explicit paths only.