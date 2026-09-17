# Elysia deep audit — checks

Verification envelope for the deep-audit + hardening + feature-expansion phases.
Run these in order; the whole envelope must stay green.

## 1. Unit / integration suite

```bash
python3 -m unittest discover -s tests -v
```

Expected: **all tests pass** (currently 210), including the
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
catalog/recommend/inference provider — plus `tests/test_master_control.py`:
the master control plane (`elysia.core.master.MasterController`) end to end —
planner -> durable task graph -> scheduler -> executor -> multiple logical
agents -> real file writes -> QA -> tester -> git-diff reviewer -> completion,
with provider failover, parallel independent work, dependency sequencing,
restart recovery, cancellation, QA rejection rollback, and the agent/provider
trace the master reports — and `tests/test_boot_scripts.py`: the universal
install/launch contract (every subcommand's `--help`, dry runs that change
nothing, `start --dry-run` never claiming a service is up, shim `sh -n`/`bash
-n` syntax, shims forwarding to `elysia_boot.py`, and the real spawn →
liveness → stop → pid-cleanup lifecycle).

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

## 6. Master control plane

The master owns the whole graph: goal -> planner -> durable task graph ->
scheduler -> executor -> logical agents -> workspace -> QA -> review ->
completion, and reports what actually ran.

```bash
./bin/elysia master agents            # role -> required capabilities -> provider
./bin/elysia master status            # board counts, inflight, stages, providers
./bin/elysia master run "add a subtract() helper to calc.py"
./bin/elysia master run "<goal>" --no-wait --json     # fire-and-forget
python3 -m unittest tests.test_master_control -v
```

Expected: `master agents` serves planner/implementer/tester/code_reviewer on
the configured provider (a strict capability match wins; a local
`chat,coding` model is used as a documented fallback for `chat,reasoning`
roles), `master status` probes providers so "healthy" is never assumed, and a
completed `master run` prints the per-task status, the logical-agent order
(`planner -> implementer -> tester -> code_reviewer`), the files changed, and
provider request/failure counts. Offline (no reachable provider) it exits
non-zero with a clear provider error instead of pretending to work.

## 7. Universal install + launch scripts

`scripts/elysia_boot.py` is the single installer/launcher for Linux, macOS and
Windows (stdlib only); `install.sh`/`start.sh`, `install.ps1`/`start.ps1` and
the `.cmd` wrappers are thin Python-locator shims.

```bash
sh -n install.sh && bash -n start.sh            # POSIX + bash syntax
python3 -m py_compile scripts/elysia_boot.py
./install.sh --dry-run                          # every action, no writes
./install.sh --dry-run --deps                   # exact package-manager command
./start.sh --dry-run                            # exact service commands
./start.sh status                               # ports/pids/binaries (--json too)
./start.sh stop                                 # no-op when nothing runs
```

Expected: dry runs end with `dry run: nothing was changed` / `nothing was
started` and touch nothing; `status` reports `down` for every port when
nothing is listening (never an assumed UP); `stop` verifies the process is
gone before reporting `stopped` (a surviving pid is reported FAIL); missing
Go, model or `llama-server` produce SKIP plus the exact command to run, never
a fake success. Covered in `howtotest.md` §7b, including a lifecycle check
that spawns a sleeper and asserts `stop` really terminates it.

## 8. Server endpoints against the new core

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