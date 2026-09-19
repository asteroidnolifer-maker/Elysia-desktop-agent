# Elysia Target Architecture

**Status:** ACTIVE TARGET — this document describes the architecture we are
building toward. It is the single authoritative source for how Elysia should
behave. If code contradicts this document, the code is wrong.

---

## Principles

1. **Logical agents ≠ OS processes ≠ AI providers.** 100 logical tasks must not
   require 100 local LLM processes. Many logical agents share a small pool of
   provider sessions/processes (especially local models).
2. **Provider diversity.** The core must be provider-agnostic. Local
   llama.cpp/Ollama is ONE provider among many (OpenAI-compatible APIs, NVIDIA
   NIM, Codex, Claude, Gemini, future backends).
3. **Dependency-aware scheduling.** Tasks form a graph. A task starts only when
   its dependencies are complete. No arbitrary global cap; concurrency is
   limited by RAM/CPU and provider capacity.
4. **Security first.** All paths resolve canonically inside a workspace root.
   Path traversal, symlink escape and workspace escape are rejected, never
   "cleaned". Invalid model output is an error, not something to silently remap.
5. **Real verification.** A task is done only when the language-aware QA
   pipeline (compile/build/test/review) succeeds — never because the model said
   so.
6. **Structured state.** Runtime state (DBs, locks, PIDs, logs, results) lives
   in runtime directories and never pollutes the Git source tree. Markdown
   documentation is a human-readable layer over structured state.
7. **Observability.** Every important event is emitted on a structured event bus
   (run_id, task_id, agent_id, provider, model, timestamp, status, error).
8. **Checkpointed migration.** The old orchestrator is migrated component by
   component; nothing is deleted until its replacement is verified.

---

## High-level flow

```
GOAL
  │
  ▼
PLANNER ───────────────► REPOSITORY CONTEXT (imports, APIs, tests, build files)
  │
  ▼
TASK GRAPH (dependencies, priorities, resource classes, owned files, read files)
  │
  ▼
SCHEDULER ─────────────► RESOURCE POLICY (live CPU/RAM/swap/thermal admission ladder)
  │                        │
  │                        ▼
  │                 RESOURCE LEDGER (slot reservations BEFORE start; heavy exclusivity)
  │                        │
  │                        ▼
  │                 PROVIDER MANAGER (health, capabilities, rate limits, budget)
  │                        │
  ▼                        ▼
MODEL ROUTER ─────────► LOCAL MODEL POOL (ONE shared slot, queued, priorities)
  │                        │  or remote providers in parallel (privacy-aware)
  ▼                        ▼
AGENT MANAGER (logical roles, dozens, in-process) ── deterministic checks first
  │
  ▼
WORKSPACE MANAGER (secure file ownership, no traversal)
  │
  ▼
TOOL MANAGER (permissioned, capability-aware tool registry)
  │
  ▼
TEST / QA MANAGER (language-aware validation + project tests)
  │
  ▼
REVIEW AGENTS (code / test / security / architecture)
  │
  ▼
GIT MANAGER (checkpoint commits, conflict detection, no secrets)
  │
  ▼
EVENT BUS ─────────────► HUD (structured state, not process scraping)
```

The execution rule: **LOGICAL AGENT ≠ MODEL PROCESS ≠ OS PROCESS ≠ PROVIDER
REQUEST.** One loaded local model serves every logical agent through a queued
single slot (`local_llm_concurrency: 1` default); CLI/cloud providers never
consume local slots; heavy classes (`cpu_heavy`, `memory_heavy`, `local_llm`,
`build`) share one slot when `heavy_exclusive: true`; saturated local compute
overflows to healthy remote providers unless the task (or global policy) is
`local_only`. Full design: `RESOURCE_ARCHITECTURE.md`.

---

## Components

### Orchestrator (`elysia/` top-level package)

Pure-Python stdlib core that unifies the old `orchestrator/` and defines the
new architecture. Components:

| Component | Module | Responsibility |
|---|---|---|
| Config | `elysia/core/config.py` | One validated configuration system (providers, models, workspace, ports, limits, git, testing). No hard-coded machine paths. |
| Paths | `elysia/core/paths.py` | Canonical workspace root + `resolve()` that rejects `..`, absolute escape, symlink escape and anything outside the workspace. |
| Events | `elysia/core/events.py` | Structured event bus (run_id, task_id, agent_id, provider, model, timestamp, type, status, error, duration). |
| Workspace | `elysia/core/workspace.py` | File-ownership enforcement + read/reference access + concurrent-modification detection. |
| Providers | `elysia/core/providers.py` | Provider registry: OpenAI-compatible, local llama.cpp/Ollama, NIM, CLI (opencode/claude/codex), generic. Capability requirement passes (strict, then documented soft fallback), atomic slot reservation, estimated-spend budget gate, and a full health model: consecutive failures, circuit breaker (closed/open/half-open with doubling capped cooldown), quarantine that excludes a provider from selection, a bounded incident timeline, a last-20-outcomes success rate, and one-shot `provider.quarantined`/`half_open`/`recovered` events. `capacity()`/`availability_report()`/`explain()` expose all of it, never a bare verdict. |
| Tasks | `elysia/core/tasks.py` | Task schema: id, title, description, status, priority, dependencies, owned files, read files, worker, provider, model, attempts, heartbeats, lease expiry, result, test status. |
| Scheduler | `elysia/core/scheduler.py` | `dispatch_plan()` — dependency-aware scheduling with leases, heartbeats, retries, provider/agent selection; priority classes (`critical→idle`) with aging and interactive preemption of background work; the live resource admission ladder; `ResourceLedger` slot reservations; provider-slot reservation BEFORE a task starts. No hard `MAX_DIVISION = 6`. |
| QA | `elysia/core/qa.py` | Language-aware validation: py_compile, gofmt/go vet/go test, tsc/npm test, gradle, shell syntax/shellcheck, strict JSON. |
| Git | `elysia/core/git.py` | status awareness, dirty detection, conflict detection, checkpoint commits. Never commits secrets/runtime state. |
| Resources | `elysia/core/resources.py` | Resource-aware execution: live monitor (CPU/RAM/swap/thermal/per-process), `ResourcePolicy` admission ladder (configurable thresholds), `ResourceLedger` slot reservations (heavy/heavy-exclusive/io/network, atomic, exactly-once release), resource classes (`light..local_llm/remote_llm/build`) and priority classes (`critical..idle` with aging). Full design: `RESOURCE_ARCHITECTURE.md`. |
| Inference | `elysia/core/inference.py` | `LocalModelPool` — ONE shared local model slot (default concurrency 1) serving every logical agent with isolated messages/context: priority queue, aging, cancellation, per-request timeout, deferral (never silent failure), slot survival across provider exceptions. `ModelRouter` — the one place that decides local vs remote: scheduler-held reservations, `local_only` privacy (structural, never routed remote), saturation overflow to healthy remote providers. `WarmModelRegistry` — idle unload under sustained pressure with warm-time hysteresis, honest `unsupported` without an unload command. `AnalysisCache` — model-independent analysis cached by input hash. |
| Model server | `elysia/core/modelserver.py` | The ONE component allowed to start/stop the local model process: pid-tracked (no duplicate starts), parallelism from `local_llm_concurrency`, threads from real core count, RAM-floor refusal quoting real free MB, graceful verified stop, `--require-managed` unload. Legacy `airllm.py`/`monitor.py` spawn paths migrated onto it. |
| Tools (mechanism) | `elysia/core/tools.py` | Tool registry: `ToolSpec` (name/description/schema/permissions/timeout/risk/destructive/preview) and `ToolRegistry.invoke` — risk gate, permission gate, dry-run preview, audit events. |
| Tools (runtime surface) | `elysia/core/toolkit.py` | The canonical tool layer agents actually use: permission levels (`read_only`, `workspace_write`, `git_write`, `network`, `browser`, `desktop`, `system`), the per-role grant map (reviewers are read-only by construction, deny-by-default for unknown roles), and real tools over Workspace/QA/git/computer: `fs.read|list|search|write|remove`, `qa.validate|run_tests`, `git.status|diff|checkpoint`, `system.info`, `browser.open_url` (SSRF-guarded), `knowledge.search`, `desktop.*`, `clipboard.*`. `AgentPipeline` writes owned files through it, so a refusal is a loud QA failure rather than a silent success. |
| Health | `elysia/core/health.py` | Ten independent health dimensions (providers, scheduler, task_store, workspace, resources, security, tests, git, memory, installation) with `ok`/`warn`/`fail`/`unknown` verdicts and no aggregate score. |
| Workflow engine | `elysia/core/workflow.py` | Real node semantics over the durable task graph: `task`, `approval` (human gate; blocks downstream until resolved, denial cascades), `join` (fan-in; completes on all-success, fails on any failure), `fallback` (executes only when its primary failed), `retry`, `timeout`, `rollback` (verifies the checkpoint exists; never a destructive reset), `fail`. Gates are board rows (`kind='gate:*'`) that `TaskStore.claim` refuses, so no worker can execute them; `tick()` promotes and evaluates gates through the canonical state machine — there is no second state store. |
| Provider budget | `elysia/core/providers.py` (`set_budget`/`budget_status`/`explain`) | Estimated-spend accumulation per call, a warning threshold, and a hard ceiling: when exceeded, paid provider kinds are dropped from `_eligible()` and `reserve()` while zero-cost (local) providers keep serving; an all-paid fleet honestly refuses to reserve (the task queues). Spend figures are labelled estimates, not billing data. |
| DB hardening | `elysia/core/tasks.py` (`health_check`/`backup`/`restore`/`vacuum`, `_migrate`) | WAL + busy timeout + `user_version`-based migrations, integrity check with malformed-row detection, consistent online backup via SQLite's backup API, restore that verifies integrity first and refuses non-SQLite content, and vacuum/compaction. |
| Memory | `elysia/core/memory.py` | Layered persistent memory: one namespace per concern (session, conversation, task, workflow, project, repo, user_prefs, agents, providers, failure, solution, decision, architecture, research, tools, history) with per-record importance, confidence, provenance, TTL, recall counters and a content hash. Duplicate content is merged instead of duplicated; compaction drops expired records and compresses the oldest beyond the per-namespace cap into a summary record that keeps the keys it replaced; backup/restore round-trips and refuses corrupt input. `rec_about()`/`recall()` return an explainable score. |
| Context planner | `elysia/core/context.py` (`ContextPlanner`) | Decides what one agent call actually needs: layers (system, task, files, failures, tests, memory, review, provider, capabilities) compete for a token budget by per-role priority, a long layer is truncated to its recent tail, every included/dropped layer is reported with source and reason, and the plan is cached until an input changes. `ContextBuilder` remains the simple layered assembler. |
| Self-healing | `elysia/core/healing.py` | One failure taxonomy (29 classes) with an explicit policy per class: retryable, action (retry / retry_after / failover / replan / escalate / give_up), base backoff, model hint, named recovery routine and a bounded retry cap. `classify()` reports the evidence it used; the configured `retry_backoff_s` is the per-attempt base and the class scales it exponentially with deterministic jitter (capped). `Healer.handle()` runs the recovery, verifies where verification is possible (otherwise `None`, never a fake `True`), records failure memory and emits `task.healing`. Git conflicts and permission/auth failures escalate to a human instead of being auto-"fixed". |
| Task-graph intelligence | `elysia/core/graph.py` | Static analysis of a plan before anything runs: unknown/self dependencies, cycles, duplicate file ownership, overlapping modification without a dependency, existing-vs-new files, tasks no provider can execute, oversized/trivial tasks, plus per-task complexity/duration/token estimates (labelled heuristics). `replan()` applies safe mechanical repairs and remaps dependencies through an explicit old→new table, so splitting points dependents at every part and merging can never leave a stale index or a cycle. |
| Front door | `elysia/core/jarvis.py` | One natural-language entry point. Deterministic regex routing first (no model call to decide how to call a model): `environment`, `progress`, `briefing`, `knowledge`, `research`, `goal`, `chat`. Machine/repo and goal-progress questions never reach the model — they are answered from real state, because the small local model used to invent refusals ("I don't have access to your GitHub repositories", "I can't check the progress of a workflow"). |
| Environment inspection | `elysia/core/environment.py` | Grounds front-door answers in real state: this checkout's git remotes and branch, the operator's repositories via the authenticated `gh` CLI, and local git repos under the workspace. When `gh` is missing or unauthenticated it says exactly that (with the fix) instead of fabricating a list. |
| Briefing / goal progress | `elysia/core/briefing.py` | Fuses capability digest, board state, provider health and control plane into one honest report, and `goal_progress()` answers "is it done?" from durable board state: `DONE`, `still running — N/M sub-task(s) completed`, or `stopped — N failed`, with each sub-task's status and last error. |

### Old `orchestrator/` (being migrated)

Kept until each piece is replaced and verified:

- `server.py` (HUD + `/api/*`) → thin HTTP layer over the scheduler state.
- `taskboard.py` (SQLite) → replaced by `elysia/core/tasks.py` persistence.
- `worker_local.py` → replaced by a scheduler agent session that maps logical
  tasks onto provider sessions.
- `brain.py` → becomes a thin wrapper over `elysia/core/providers.py` (local
  provider).
- `adaptive.sh`, `monitor.py` → wrapper scripts that start the scheduler.

### Memory, context, healing and graph wiring

Nothing in the list above is a side library — each is on the live call path:

```
MasterController
  -> plan()            AgentPipeline.plan_task (project intel in the prompt)
                       -> graph.analyze() -> graph.replan()  (safe repairs, reported)
                       -> memory.remember_decision()
  -> TaskExecutor      AgentPipeline.solve_task
       -> ContextPlanner  (task + owned files + classified prior failure +
                           recalled memory + last test result + provider trace,
                           inside a token budget, cache-invalidated on change)
       -> provider         (ProviderManager: capability/health/concurrency/budget)
       -> tool layer       (fs.write through toolkit, denied writes fail QA)
       -> QA / tester / reviewer
       -> on failure       Healer.handle() -> classify, recover, verify, record
                           (bounded retries, class-scaled backoff, task.healing event)
       -> on success       memory.remember_solution() + remember_task_context()
```

### Simulation, routing and audit

- `MasterController.simulate(goal)` dry-runs a plan: it reports the files that
  would change, conflicting file ownership, circular dependencies, roles that
  cannot write and roles no provider can serve — and writes nothing (no files,
  no board rows, no scheduler start).
- `ProviderManager.explain(capabilities)` returns a read-only routing trace:
  the strict pass, the documented soft-capability fallback, each candidate's
  rejection reason, priority order, free slots and whether health was probed.
  `select()` and `explain()` share `_eligible()` so criteria cannot drift.
- Every tool invocation and file change is an event (`tool.invoke`,
  `tool.result`, `file.changed`, `tool.quarantined`), so the audit trail is
  reconstructable from the event journal rather than from logs or process names.

### Python host (`workspace/tools/`)

Tools gain a common interface: name, description, input schema, output schema,
permissions, timeout. The permissions system is the choke point for
desktop-control and system-level actions (never let raw model output become raw
shell execution).

### Go `agent-core/`

The Go daemon wraps the same concepts natively. `sandbox.go` already uses
canonical resolution (keep & harden). It speaks HTTP to the orchestrator so the
scheduler can treat it as another worker endpoint. `Elysia Desktop.zip` and the
Windows-specific `agent_config.json` live in Releases/runtime config, not the
source tree.

### Android `elysia-android/`

Preserved and integrated: the device agent can register as a remote logical
agent through the orchestrator API.

---

## Task schema (canonical)

```json
{
  "id": 1,
  "title": "...",
  "description": "...",
  "status": "open",
  "priority": 5,
  "dependencies": [],
  "owned_files": ["src/foo.py"],
  "read_files": ["README.md"],
  "worker": null,
  "provider": null,
  "model": null,
  "attempts": 0,
  "max_attempts": 3,
  "created_at": "...",
  "claimed_at": null,
  "heartbeat_at": null,
  "lease_expires_at": null,
  "completed_at": null,
  "last_error": null,
  "result": null,
  "test_status": null
}
```

Status values: `open → claimed → in_progress → (review) → done` or `failed`.

Lease semantics: a claimed task has `lease_expires_at`. A worker must renew
`heartbeat_at`; when the lease expires without a heartbeat the scheduler
releases the task (increments `attempts`, records `last_error`) and makes it
claimable again. A task fails after `max_attempts`.

---

## Acceptance criteria (from the rearchitecture plan)

A. Multiple logical agents can work concurrently.
B. Agents can use different providers/models.
C. A provider can fail without killing the whole run.
D. Tasks have dependencies.
E. Worker crashes recover automatically.
F. File ownership is enforced securely.
G. Real tests run automatically.
H. Failed tests trigger controlled repair.
I. Git changes are tracked safely.
J. Runtime state is separated from source.
K. Hard-coded machine paths are removed.
L. APIs validate input and return structured errors.
M. Secrets never enter Git/logs/output.
N. Resource-aware scheduling works on a low-RAM laptop.
O. HUD reflects real scheduler state.
P. Documentation matches implementation.
Q. The entire repository builds/tests successfully.

The system is not "done" until these are exercised by tests.