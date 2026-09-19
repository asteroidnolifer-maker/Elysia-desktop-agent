# Elysia Desktop Agent — Implementation State

Status of the phased audit + rearchitecture. Phase 1 (audit) is complete;
Phases 2–15 (foundation + migration) are complete and committed on the
`rearchitecture` branch; Phase 16 (docs + verification) closes the loop.
Phase 17 (hardening + feature expansion), Phase 18 (provider ecosystem:
presets, desktop login, prompt styles, security knowledge base, HuggingFace),
and Phase 19 (**resource-aware agent execution**: `LocalModelPool` shared local
slot, `ModelRouter`, `WarmModelRegistry`, `AnalysisCache`, model-server
lifecycle, admission ladder, slot ledger, priority/aging fairness, privacy-
structural routing, deterministic-first checks, efficiency accounting) are
complete on `main` — see `checks.md`, `howtotest.md` and
`RESOURCE_ARCHITECTURE.md`.

Companion docs:
- `docs/ARCHITECTURE_AUDIT.md` — the full Phase 1 audit (findings, contradictions,
  dead code, security issues).
- `docs/ARCHITECTURE.md` — the target architecture (authoritative after this
  rearchitecture).
- `RESOURCE_ARCHITECTURE.md` — the resource-aware execution layer (design,
  admission ladder, measured low-end behavior, honest limitations).

---

## What changed ("before → after")

| Area | Before | After (this branch) |
|---|---|---|
| Python config | hard-coded `/data/Elysia/...`, `/data/elysia-run/workspace` scattered across files + org-specific env | single `elysia/config.json` (+ env overrides), everything derives from the repo root |
| LLM provider | local `llama-server` hard-wired via `urllib` in `brain.py` | `elysia/core/providers.py` — OpenAI-compatible (local or remote), NVIDIA NIM, CLI providers; fallback local default |
| Task store | hand-rolled `taskboard.sqlite` schema with ad-hoc `locks` | `elysia/core/tasks.py` canonical store with atomic claims, leases, heartbeats, dependencies, attempts |
| Scheduling | `adaptive.sh` + `monitor.py` loose coordination | `elysia/core/scheduler.py` lease/heartbeat/dependency-aware dispatch; `taskboard.py` is now a thin CLI wrapper over it |
| File writes | `lstrip("/").replace("..", "_")` — traversal *sanitized silently*; single-file tasks *remapped* model output | `elysia/core/paths.py` canonical resolution; traversal/symlink-escape/absolute paths **rejected**; out-of-scope model blocks refused (no remapping) |
| QA | ad-hoc per-extension checks in `worker_local` | `elysia/core/qa.py` language-aware validation reused by brain/worker/server |
| Events | unstructured log lines | `elysia/core/events.py` EventBus; `/api/events` endpoint |
| Git helpers | none | `elysia/core/git.py` — conflict detection, safe checkpoint, **secret redaction** |
| Paths in scripts | `/data/Elysia`, `/data/elysia-run`, `/home/myusername` | all scripts derive from repo root; `ELYSIA_*` env overrides |
| Repo hygiene | `.zip`, `agent_audit.json`, `*_result.json`, `.adaptive/` tracked | runtime state removed from git + `.gitignore` rules added |

## Package layout (new)

```
elysia/
  config.json              # default config (workspace root, providers, scheduler)
  __init__.py
  core/
    config.py              # load/default/apply config; repo_root() + resolve_repo_path()
    paths.py               # SECURE path resolution (no traversal/symlink escape)
    events.py              # EventBus (run-scoped, in-memory)
    providers.py           # multi-provider abstraction (openai / nim / cli / local)
    tasks.py               # canonical TaskStore (SQLite: add/claim/heartbeat/complete)
    scheduler.py           # dispatch_plan(): priority/aging, resource ladder, provider-slot reservations
    qa.py                  # language-aware validate_file() / validate_python() / validate_json()
    git.py                 # has_conflicts(), redact(), safe_checkpoint()
    resources.py           # live monitor + admission ladder + ResourceLedger + provider scoring
    inference.py           # LocalModelPool (shared local slot), ModelRouter, WarmModelRegistry, AnalysisCache
    modelserver.py         # THE owner of the local llama-server process (pid-tracked)
    environment.py         # real repo/remote/gh/system inspection for the front door
    tools.py               # permissioned tool registry
    workspace.py           # Workspace — owned reads/writes, secure root boundary
    memory.py              # MemoryStore (key/value persisted in workspace)
```

## Orchestrator after migration

- `orchestrator/brain.py` → thin wrapper over `elysia.core.providers.Provider` +
  `elysia.core.qa.validate_file`. Same CLI (`ask`, `health`); now provider-agnostic.
- `orchestrator/taskboard.py` → CLI + import wrapper over `elysia.core.tasks.TaskStore`.
  Legacy `locks` table and `files`-as-JSON-string payload shape preserved so
  `worker_local.py` / `server.py` / `adaptive.sh` / `monitor.py` work unchanged.
- `orchestrator/worker_local.py` → all writes via `Workspace.resolve()` (rejects
  traversal, absolute, symlink escape). Out-of-scope model blocks refused, not
  remapped. Repair loop same guarantee.
- `orchestrator/server.py` → provider health via `ProviderManager`,
  structured events, new endpoints (`/api/providers`, `/api/events`), owned-file
  list validated through `elysia.core.paths.validate_file_list` on `/api/task`.

## Scripts / launcher

- `elysia-run.sh start|stop|status|restart` — paths derived from repo root;
  override anything with `ELYSIA_MODEL`, `ELYSIA_RUNTIME`, `ELYSIA_WS`,
  `ELYSIA_MODEL_ALIAS`, `ELYSIA_AGENT_BIN`.
- `orchestrator/adaptive.sh up|down|status` — pool manager, portable `WS_DIR`.
- `orchestrator/ask.sh` — one-shot/interactive chat, portable stack lookup.
- `orchestrator/airllm.py` — now a thin wrapper over `elysia.core.modelserver`
  (its own `subprocess` use is gone, AST-enforced by test); model/llama paths
  still derive from the repo root.

## Go agent-core

Unchanged logic; paths are already env-configurable (`ELYSIA_HTTP_ADDR`,
OpenAI-compatible base URL). Build with `cd agent-core && go build`.

## Tests

`python3 -m unittest discover -s tests -v` — **402 tests**, stdlib only
(Python 3 + SQLite), no network/key/model required. Bundles:
- `tests/test_core.py` — providers (selection, health), QA (python/json/markdown),
  scheduler (dependency block, claim+lease expiry, retries→fail, event emission),
  TaskStore add/complete.
- `tests/test_paths.py` — traversal, absolute, symlink-escape rejection; symlink-inside
  allowed; owned write/read.
- `tests/test_worker_security.py` — end-to-end worker write security:
  traversal rejected, out-of-scope rejected **with no remap**, valid owned write succeeds.
- `tests/test_git_redact.py` — secret redaction for `sk-*`, `ghp_*`, `ak_*`,
  `Authorization: Bearer`, PEM blocks.
- `tests/test_features.py`, `tests/test_server_api.py`, `tests/test_integration.py`,
  `tests/test_providers_plus.py`, `tests/test_master_control.py`,
  `tests/test_boot_scripts.py`, `tests/test_tool_layer.py`,
  `tests/test_db_budget_workflow.py`, `tests/test_memory_context_healing.py`,
  `tests/test_task_graph.py`, `tests/test_jarvis_layer.py`,
  `tests/test_jarvis_router.py`, `tests/test_briefing_cli.py`,
  `tests/test_runtime_wiring.py`, `tests/test_e2e_executor.py` — the full
  feature/runtime envelope (see `checks.md` §1 for the map).
- `tests/test_front_door.py` — Jarvis routes machine/repo questions to real
  environment inspection and goal follow-ups to durable board state; HUD
  legacy counters map canonical statuses.
- `tests/test_resource_execution.py` — the Phase 19 resource layer: 20 logical
  agents through ONE local model slot (peak concurrency = 1), slot survival
  across exceptions/cancel/timeout, priority/aging fairness, interactive
  preemption, CPU/RAM admission ladder, heavy-slot exclusivity, warm-model
  hysteresis, `local_only` privacy routing, provider-slot reservations,
  deterministic-first checks, model-server lifecycle, and bypass audits
  (`airllm.py` AST-checked to contain no `subprocess`; `start_pool` spawns
  nothing; `worker_local.py` reaches models only through the brain wrapper).

## Phase 19 — resource-aware execution (current state)

The four confused units are now formally distinct: logical agents are pipeline
stages in the executor's threads; the ONE model process is owned by
`elysia.core.modelserver.ModelServer` (pid-tracked, duplicate start is a
no-op, RAM-floor refusal quotes real free MB); local inference is ONE queued
slot (`LocalModelPool`, priorities + aging + cancellation + timeout + context
isolation, deferred-not-failed refusals); provider requests are bounded per
provider. The scheduler (`dispatch_plan`) decides WHO may start NOW and WHY
NOT — priority class + aging + interactive preemption, the live CPU/RAM/swap/
thermal admission ladder, `ResourceLedger` slot reservations (heavy classes
share one slot when `heavy_exclusive`), and provider-slot reservation BEFORE a
task starts. Privacy is structural: `local_only` tasks are never routed to a
remote provider, even when the local slot is busy and remote is healthy.
Saturated local compute overflows to healthy remote providers for non-private
tasks. Warm models unload only under sustained pressure with hysteresis and
an explicit unload command (`unsupported` otherwise — never a pretend
unload). Model-call minimization: deterministic checks answer verification
tasks with zero model calls; `AnalysisCache` caches model-independent
analysis by input hash; per-task model-call caps are configurable. Full
design, thresholds and measured numbers: `RESOURCE_ARCHITECTURE.md`.

Known limitations (honest, documented): provider health history is in-process
(does not survive restarts); per-process CPU needs a sampling window (first
snapshot reports `per_process: []`); temperature requires a readable thermal
zone; batching stays off unless a backend declares support; the legacy
`worker_local.py`/`adaptive.sh` path remains for old boards (not part of the
canonical execution path).

## Remaining / not addressed

- `elysia-android/`, `dist/`, `workspace/tools` runtime, Electron desktop UI, and
  the Go sandbox internals are out of scope for this branch (unchanged).
- Keyboard-interactive auth, cloud/webhooks, and provider API keys are left to the
  operator via `config/` + env (never committed).
- The canonical scheduler now runs as a server-owned maintenance thread
  (`orchestrator/server.py:start_scheduler_thread`): it repairs crashed workers
  (lease expiry → ready/failed by the task's OWN `max_attempts`), releases
  stale-worker claims, enforces timeouts, and propagates dependency failures.
  Workers renew their lease during long model calls (`worker_local._heartbeat_loop`
  + `taskboard.py heartbeat`). Crash-recovery / failover / resource-queueing /
  symlink-escape tests: `tests/test_runtime_wiring.py`. Doctor now reports
  expired leases and stuck tasks (`taskboard` check).
- LIVE in-process execution is wired: `elysia/core/executor.py:TaskExecutor`
  claims budgeted tasks through the scheduler (atomic provider reservation) and
  runs `AgentPipeline.solve_task` in-process — logical agents as pipeline stages,
  provider failover mid-task, real Workspace writes with the owned-file security
  gate, language-aware QA, retry-with-backoff by the task's own `max_attempts`,
  lease heartbeat during model calls. Server integration: health-gated start,
  periodic re-probe when a provider comes online, `POST /api/executor
  {action:start|stop|status}` and executor state on `GET /api/scheduler`.
  End-to-end tests (goal → dispatch → failover → file on disk → QA →
  completion, plus retry/exhaustion/dependency-ordering/parallelism/restart):
  `tests/test_e2e_executor.py`. The `adaptive.sh` worker pool remains as a
  compatibility execution path; both compete for tasks via the same atomic
  claim, so no task is double-executed.