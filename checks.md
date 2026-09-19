# Elysia deep audit — checks

Verification envelope for the deep-audit + hardening + feature-expansion phases.
Run these in order; the whole envelope must stay green.

## 1. Unit / integration suite

```bash
python3 -m unittest discover -s tests -v
```

Expected: **all tests pass** (currently 402), including the
`tests/test_resource_execution.py` bundle (see `RESOURCE_ARCHITECTURE.md`):
resource-aware execution — 20 logical agents through ONE local model slot
(peak concurrency = 1), priority/aging fairness, the CPU/RAM admission ladder,
heavy-slot exclusivity, warm-model hysteresis, `local_only` privacy routing,
provider-slot reservations, deterministic-first checks and the model-server
lifecycle — plus the
`tests/test_front_door.py` bundle: the Jarvis front door routes repo/machine
questions to the real environment (git remotes, `gh`, workspace) and goal
follow-ups ("is it done") to durable board state, goal milestones carry a real
result, and the HUD's legacy counters map canonical `ready`/`completed`
statuses — plus the
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
liveness → stop → pid-cleanup lifecycle) — `tests/test_tool_layer.py`
(see §6b): the runtime tool registry, the per-role permission model, workspace
security through the tool layer, dry-run previews, desktop two-key gating, the
SSRF guard, planning simulation, routing explanation, the health dimensions,
and the proof that the live pipeline writes files through the tool layer — and
`tests/test_db_budget_workflow.py` (see §9): DB health/backup/restore/vacuum,
budget enforcement over paid vs local providers, and the workflow engine's
gates (approval/join/fallback/timeout/rollback) evaluated on the real board.

## 2. Compile check

```bash
python3 -m py_compile orchestrator/server.py elysia/cli.py elysia/core/*.py \
    tests/test_features.py tests/test_resource_execution.py tests/test_front_door.py
```

## 3. Health + portability + resource views

```bash
./bin/elysia doctor     # workspace, providers, api_port, python_deps, git
./bin/elysia audit      # no hardcoded legacy absolute paths in source
./bin/elysia providers --catalog   # provider catalog: what is active/missing
./bin/elysia knowledge list        # vendored security docs indexed
./bin/elysia prompt                # prompt styles listed
./bin/elysia resources             # live CPU/RAM/swap/temp + slots + waiting reasons
./bin/elysia queue                 # same verdicts, task-centric
./bin/elysia models                # local slot + warm state + provider profiles
./bin/elysia master efficiency     # AI calls vs deterministic checks
```

Expected: `Result: all checks passed`, `audit passed`, and clean output from
the read-only commands (no tracebacks with zero credentials). Unknown metrics
(temperature, per-process CPU on first snapshot) print as unknown — never as
invented values.

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

## 6b. Runtime tool layer, simulation, routing, health

The canonical tool layer (`elysia.core.toolkit`) is what agents actually write
files through; `elysia.core.health` reports independent health dimensions.

```bash
./bin/elysia tools --registry            # runtime registry: risk + permissions
./bin/elysia tools --registry --role code_reviewer   # who may do what, and why not
./bin/elysia master route --caps chat,coding         # why this provider/model
./bin/elysia master simulate "add a subtract() helper to calc.py"
./bin/elysia health [--json]
python3 -m unittest tests.test_tool_layer -v
```

Expected:
- `tools --registry` lists every tool with its risk and required permission
  tokens; `--role` shows `deny` with the precise reason (`is high-risk and not
  enabled by policy`, `needs ['workspace:write'] (role code_reviewer has none)`).
- Reviewers (`code_reviewer`, `security_reviewer`, `planner`, ...) are read-only
  **even if config tries to grant them write**: `role_permissions()` strips write
  tokens from read-only roles.
- Desktop/clipboard tools need BOTH `tools.allow_high_risk: true` AND the
  `desktop:control` permission; on a headless host the call reports the backend
  unavailable instead of pretending.
- `master route` prints the decision trace: requirement passes (strict, then the
  documented soft-capability fallback), each candidate's rejection reason,
  priority order and free slots. It never acquires a slot.
- `master simulate` writes NOTHING (no files, no board rows, no scheduler): it
  reports the files that would change, conflicting file ownership, circular
  dependencies, missing write permission per role and unservable roles. Offline
  it fails loudly on the planner provider rather than inventing a plan.
- `elysia health` prints ten independent dimensions (providers, scheduler,
  task_store, workspace, resources, security, tests, git, memory, installation)
  with `ok`/`warn`/`fail`/`unknown` and an explicit "no aggregate score" note;
  `unknown` means the evidence does not exist yet (e.g. no test run recorded).

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

## 9. DB hardening, budget enforcement, workflow engine

```bash
./bin/elysia db health                     # integrity, schema version, WAL
./bin/elysia db backup state/backups       # consistent online backup
./bin/elysia db vacuum
./bin/elysia workflow start --file nodes.json --name demo
./bin/elysia workflow tick                 # advance gates
./bin/elysia workflow state demo           # node table, awaiting approval
./bin/elysia workflow approve --node ID    # human decision (deny cascades)
python3 -m unittest tests.test_db_budget_workflow -v
```

Expected:
- `db health` reports `integrity: ok`, `schema ver: 1`, `journal: wal` and the
  board counts; backup writes a consistent snapshot that restores into a fresh
  store round-trip; restore refuses missing files AND non-SQLite content
  ("backup unreadable"), never clobbering the live board.
- Over budget (`providers.set_budget`): paid providers are dropped everywhere —
  `reserve()` returns None for an all-paid fleet (the task queues instead of
  silently spending) while local/zero-cost providers keep serving. The drop is
  visible in `master route`'s trace ("over budget: paid provider dropped").
  Budget accounting is estimated (chars/4) and labelled as estimates.
- Workflow gates are REAL board rows (`kind='gate:*'`) that `TaskStore.claim`
  refuses — a worker can never execute a gate. Approvals block downstream work
  until `workflow approve|deny`; denial cancels the branch (never proceeds).
  Joins stay queued until every sibling is terminal, then complete on all-success
  and fail on any failure. Fallback executes only when its primary failed and is
  recorded as skipped when it succeeded. Timeout fails a stuck child via the
  store's own `timeout_task`. Rollback verifies the checkpoint exists (refusing
  to guess) and never runs a destructive reset on its own.
- Static validation rejects empty graphs, duplicate ids, unknown node types,
  unknown `after` refs, forward references (cycles impossible by construction),
  joins that wait on nothing, and fallbacks with no `fallback_of`.

## 12. Resource-aware execution (Phase 19)

`RESOURCE_ARCHITECTURE.md` is the design reference;
`tests/test_resource_execution.py` is the proof (44 tests). All numbers come
from real subsystems — real ledger, real policy ladder, real pool threads,
real scheduler + SQLite board; only the model transport is faked.

```bash
python3 -m unittest tests.test_resource_execution -v
./bin/elysia resources          # live system + held slots + waiting reasons
./bin/elysia queue              # waiting view, task-centric
./bin/elysia models             # local slots, warm state, batching policy
./bin/elysia master queue       # running + waiting from the live controller
```

Expected:
- 20 logical agents complete through ONE local model slot — peak concurrent
  local inferences = 1, slot released after every request.
- The slot survives provider exceptions, cancellation and timeouts (a release
  that raises is recorded, never propagated).
- Fairness: interactive outranks background; aging lifts a waiting task; an
  interactive waiter defers background admission with the exact verdict.
- CPU ladder: 60% → build deferred; 80% → heavy/background deferred; 95% →
  local blocked but remote allowed. RAM ladder: 1.5 GB free → no new model;
  0.8 GB → inference blocked; remote still serves.
- Heavy exclusivity: model running → build refused ("one heavy job at a time").
- Warm models: no pressure → no unload; fresh model → keep (hysteresis); no
  unload command → honest `unsupported`.
- Privacy: `local_only` stays local while the slot is busy; global
  `privacy.local_only` locks ALL routing; saturated local overflows to remote
  only for non-private tasks.
- Reservations: model task claims its provider slot before starting; a build
  task takes the build slot, NOT the model slot; finish/cancel releases
  exactly once.
- Determinism: verification tasks complete with 0 model calls; the checks
  really ran.
- Bypass audits: `airllm.py` contains no `subprocess` (AST-checked);
  `start_pool` spawns nothing; `worker_local.py` reaches models only through
  the brain wrapper.

## 10. Memory, context planning, self-healing, task graphs

```bash
python3 -m unittest tests.test_memory_context_healing tests.test_task_graph -v
./bin/elysia memory stats
./bin/elysia memory timeline --ns solution
./bin/elysia memory recall "provider timeout"
./bin/elysia memory backup state/memory-backup.json
./bin/elysia memory compact
./bin/elysia healing policies
./bin/elysia healing classify "database is locked"
./bin/elysia healing classify "merge conflict in calc.py"
./bin/elysia master simulate "plan check" --file plan.json
```

Expected:
- **Memory.** Records carry `importance`, `confidence`, `provenance`, `tags`,
  `created`/`updated`, an optional TTL, a recall counter and a content hash.
  Identical content is merged (dedup), not duplicated. Retrieval returns a
  transparent score (`keyword × importance × recency + recall boost`) plus the
  `why` string. `memory timeline` shows provenance per record and marks
  invalidated ones. `memory compact` drops expired records and compresses the
  oldest beyond the per-namespace cap into a `project/memory_summary` record
  listing the keys it replaced. `backup`/`restore` round-trip; a corrupt or
  missing backup is refused with a reason instead of wiping memory.
- **Context.** A long layer is truncated to its recent tail and the response
  says how many chars were omitted; a layer that cannot fit is reported in
  `dropped` with `budget exhausted` / `no useful slice fits the budget`; the
  per-role priority tables differ (an implementer weighs `failures` above
  `provider`; a reviewer weighs `diff` above `memory`).
- **Healing.** `healing policies` prints all classes with retryability, action,
  base backoff and recovery routine. `classify` returns the kind, the action,
  the bounded attempt counter, the computed backoff and the EVIDENCE
  (`pattern:/…/` or `exception:…`) — nothing is guessed. A dangerous input
  (`merge conflict`, `permission denied`, `401 unauthorized`, a tool denial)
  classifies as non-retryable → `escalate`/`replan` with zero backoff.
  On the live path a failure is classified, recovery is attempted, the result
  is verified where it can be, the failure is stored in failure memory and a
  `task.healing` event is emitted; the retry prompt then carries the hint.
- **Graphs.** `master simulate --file plan.json` (offline, no model) prints every
  issue with severity, the conflicts in the RAW plan, the repairs the planner
  path would have applied automatically, the repairs available for the explicit
  plan, and heuristic estimates. Two tasks owning one file is a blocker in the
  raw plan; the repaired graph that would actually run has one owner. `replan()`
  never leaves an unknown/self edge or a cycle, and splitting a task points its
  dependents at every part.

## 11. Provider health (circuit breaker)

```bash
python3 -m unittest tests.test_providers_plus -v
./bin/elysia master status          # circuit/success columns per provider
./bin/elysia health                 # "N quarantined (circuit open)"
```

Expected:
- A provider that fails `FAILURE_THRESHOLD` (3) times in a row is quarantined:
  `circuit=open`, `trips=1`, a 30s cooldown that doubles per subsequent trip
  (capped at 900s), and it is no longer reserved at all.
- `master route` names the quarantine as the rejection reason ("circuit open
  after 1 trip(s)/3 failures, 30s cooldown left"), not just "degraded".
- After the cooldown ONE half-open probe is allowed; success closes the circuit
  (`provider.recovered`), failure re-quarantines for longer. An abandoned probe
  ticket expires after 120s so nothing is locked out forever.
- `provider.quarantined`, `provider.half_open` and `provider.recovered` each
  appear ONCE per transition on the event timeline (never once per call).
- `success_rate` is the last-20-outcomes window and is `None` before any call —
  no invented availability numbers.

## Security posture

- No hardcoded absolute host paths in source (audit enforces).
- Memory records are plain JSON under `state/memory/` (no secrets are written by
  the runtime; provider keys live in `config/providers.env`, git-ignored).
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