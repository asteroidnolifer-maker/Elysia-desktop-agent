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
TASK GRAPH (dependencies, priorities, owned files, read files)
  │
  ▼
SCHEDULER ─────────────► RESOURCE MANAGER (RAM/CPU budget)
  │                        │
  │                        ▼
  │                 PROVIDER MANAGER (health, capabilities, rate limits)
  │                        │
  ▼                        ▼
AGENT MANAGER ───────► one or more PROVIDER SESSIONS (may be shared)
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
| Providers | `elysia/core/providers.py` | Provider registry: OpenAI-compatible, local llama.cpp/Ollama, NIM, CLI (opencode/claude/codex), generic. Health + capabilities + rate limit tracking. |
| Tasks | `elysia/core/tasks.py` | Task schema: id, title, description, status, priority, dependencies, owned files, read files, worker, provider, model, attempts, heartbeats, lease expiry, result, test status. |
| Scheduler | `elysia/core/scheduler.py` | Dependency-aware scheduling with leases, heartbeats, retries, provider/agent selection. Resource-aware (RAM/CPU). No hard `MAX_DIVISION = 6`. |
| QA | `elysia/core/qa.py` | Language-aware validation: py_compile, gofmt/go vet/go test, tsc/npm test, gradle, shell syntax/shellcheck, strict JSON. |
| Git | `elysia/core/git.py` | status awareness, dirty detection, conflict detection, checkpoint commits. Never commits secrets/runtime state. |
| Resources | `elysia/core/resources.py` | RAM/CPU budget model: how many local workers can run, provider session usage. |
| Tools | `elysia/core/tools.py` | Tool registry with name/description/input schema/output schema/permissions/timeout. Permissioned invocation. |
| Memory | `elysia/core/memory.py` | Structured project/task/agent/provider/run state (context.md is a human layer over this). |

### Old `orchestrator/` (being migrated)

Kept until each piece is replaced and verified:

- `server.py` (HUD + `/api/*`) → thin HTTP layer over the scheduler state.
- `taskboard.py` (SQLite) → replaced by `elysia/core/tasks.py` persistence.
- `worker_local.py` → replaced by a scheduler agent session that maps logical
  tasks onto provider sessions.
- `brain.py` → becomes a thin wrapper over `elysia/core/providers.py` (local
  provider).
- `adaptive.sh`, `monitor.py` → wrapper scripts that start the scheduler.

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