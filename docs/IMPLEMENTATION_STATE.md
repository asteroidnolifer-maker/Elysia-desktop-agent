# Elysia Desktop Agent — Implementation State

Status of the phased audit + rearchitecture. Phase 1 (audit) is complete;
Phases 2–15 (foundation + migration) are complete and committed on the
`rearchitecture` branch; Phase 16 (docs + verification) closes the loop.
Phase 17 (hardening + feature expansion) and Phase 18 (provider ecosystem:
presets, desktop login, prompt styles, security knowledge base, HuggingFace)
are complete on `main` — see `checks.md` and `howtotest.md`.

Companion docs:
- `docs/ARCHITECTURE_AUDIT.md` — the full Phase 1 audit (findings, contradictions,
  dead code, security issues).
- `docs/ARCHITECTURE.md` — the target architecture (authoritative after this
  rearchitecture).

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
    scheduler.py           # dispatch_once(), lease expiry, dependency resolution
    qa.py                  # language-aware validate_file() / validate_python() / validate_json()
    git.py                 # has_conflicts(), redact(), safe_checkpoint()
    resources.py           # RAM/CPU budget model (data/elysia practice)
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
- `orchestrator/airllm.py` — model launcher, model/llama paths from repo root.

## Go agent-core

Unchanged logic; paths are already env-configurable (`ELYSIA_HTTP_ADDR`,
OpenAI-compatible base URL). Build with `cd agent-core && go build`.

## Tests

`python3 -m unittest discover -s tests -v` — 29 tests:
- `tests/test_core.py` — providers (selection, health), QA (python/json/markdown),
  scheduler (dependency block, claim+lease expiry, retries→fail, event emission),
  TaskStore add/complete.
- `tests/test_paths.py` — traversal, absolute, symlink-escape rejection; symlink-inside
  allowed; owned write/read.
- `tests/test_worker_security.py` — end-to-end worker write security:
  traversal rejected, out-of-scope rejected **with no remap**, valid owned write succeeds.
- `tests/test_git_redact.py` — secret redaction for `sk-*`, `ghp_*`, `ak_*`,
  `Authorization: Bearer`, PEM blocks.

No third-party dependencies (Python 3 stdlib + SQLite).

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
- Still deferred: live in-process task execution via `Scheduler.execute_claimed`
  (the `adaptive.sh` worker pool remains the model execution path until a model
  runtime is validated on the target machine).