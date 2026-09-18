# Elysia Desktop Agent

Offline-first desktop AI agent: local LLM inference (`llama-server` + Go `agent-core`),
a Python orchestrator pool with HUD/taskboard, and a Kotlin Android app
(`elysia-android/`). No cloud required for the core loop — the model, agent,
and workers all run on `127.0.0.1`.

## Repository layout

| Path | What it is |
|---|---|
| `agent-core/` | Go daemon (default listen `:8085`). HTTP API + sandbox + thermal/power managers. Build with `go build`. Config: `agent-core/agent_config.json`. |
| `orchestrator/` | Python control layer (stdlib only). `server.py` HUD + JSON API (default `--port 8087`), `adaptive.sh` worker pool, `worker_local.py` agents, `taskboard.py` (canonical `elysia.core.tasks` store), `brain.py` / `ask.sh` LLM chat (multi-provider), `airllm.py` model launcher, `monitor.py`, `hud.html`. |
| `elysia/` | Rearchitected core package: `core/master.py` (**master control plane**: goal -> planner -> durable task graph -> scheduler -> executor -> logical agents -> workspace -> QA -> review -> completion, plus `status`/`agents`/`report`), `core/config.py`, `core/paths.py` (secure path resolution), `core/providers.py`, `core/tasks.py`, `core/scheduler.py`, `core/executor.py` (in-process task execution), `core/agents.py` (logical roles), `core/fileblocks.py` (model-output file parser), `core/qa.py`, `core/events.py`, `core/git.py`, `core/workspace.py`, `core/toolcatalog.py` (machine capability detection), `core/briefing.py` (Jarvis-style status fusion), `core/jarvis.py` (natural-language front door), `core/knowledge.py` (multi-domain tooling docs) + more. `elysia/config.json` is the single source of configuration. |
| Provider ecosystem | `core/provider_presets.py` — one catalog: local llama.cpp/Ollama, cloud OpenAI-compatible APIs (OpenRouter, Groq, Together, DeepSeek, Mistral, xAI, NVIDIA NIM, GitHub Models, Cerebras, Gemini, HuggingFace, Freebuff-style gateways) and CLI coding agents (Claude Code, Codex, Gemini CLI, OpenCode, OpenClaw). A preset activates only when its credential env var is set (API) or its binary is on PATH (CLI). `core/browser_login.py` — `elysia login <provider>` opens the provider's console in the desktop browser and stores keys in `config/providers.env` (0600, git-ignored). |
| `docs/` | `ARCHITECTURE_AUDIT.md` (Phase 1 audit), `ARCHITECTURE.md` (target architecture), `IMPLEMENTATION_STATE.md` (status of the rearchitecture), `knowledge/kali-tools/` (vendored defensive-first security-tooling docs, indexed by `elysia.core.knowledge`), `security/SECURITY_TOOLING.md` (tooling policy). |
| `tests/` | `python3 -m unittest discover -s tests` — 210 unit tests (paths/security, providers, scheduler, QA, redaction, worker write security, features bundle, server API, provider presets/login/knowledge/HF, runtime wiring: crash recovery, lease heartbeat, failover, resource queueing, end-to-end executor: goal→file→QA→completion with failover/retry/dependencies, the master control plane: full agent trace, failover, parallelism, dependency sequencing, restart recovery, cancellation, QA rollback, and the install/launch scripts: shim contract, dry-run safety, service spawn→stop lifecycle). |
| `runtime/` | Local inference runtime (**not committed**: binaries/models). `restore-model.sh` downloads `llama-server` + Qwen GGUF into `runtime/llama/` + `runtime/models/`. |
| `elysia-android/` | Android app (Gradle, AGP `8.13.2`, Kotlin `2.2.21`). Modules: `:app`, `:core`, `:device`, `:installer`, `:runtime`, `:models`, `:diagnostics`, `:permissions`. |
| `workspace/` | Generated projects, `tools/` scripts, `docs/` notes. `workspace/repos/` (cloned test projects), `*.db`, `*.log`, `cache/` are git-ignored. |
| `scripts/` | `elysia_boot.py` — **universal installer + launcher** (Linux/macOS/Windows, stdlib only): `install`, `start`, `stop`, `restart`, `status`, `doctor`. Also task-board generators (`generate_*.py`, `gen_unique_tasks.py`). |
| `install.sh` / `start.sh` | Linux + macOS shims: `./install.sh [--deps --build --with-model]`, `./start.sh [stop\|status\|doctor]`. |
| `install.ps1` / `start.ps1` / `*.cmd` | Windows shims (PowerShell 5.1+/7+, plus double-click `.cmd` wrappers). |
| `config/` | Local secrets (**never committed**, see `.gitignore`). Example: `config/composio.env`. |
| `elysia-run.sh` | Unified launcher: starts `llama-server` (`:11434`) + `agent-core` (`:8085`). `start\|stop\|status\|restart`. Paths derive from the repo root; override with `ELYSIA_MODEL`, `ELYSIA_RUNTIME`, `ELYSIA_WS`, `ELYSIA_AGENT_BIN`. |
| `elysia-home/` | Notes about the working-copy location (`.readme`). |
| `dist/` | Build output (git-ignored). |

## Prerequisites

- Linux (primary) or Windows (Android/desktop parts). Commands below are Linux `bash`.
- Git, `curl`, `tar`.
- Go `1.20+` (repo `go.mod`: `go 1.20`; tested here with `go1.27`).
- Python `3.x` — orchestrator is **stdlib only** (no `pip install` needed).
- For `runtime/restore-model.sh`: ~2 GB free disk.
- For building `llama.cpp` from source: `cmake`, `ninja`, C++ toolchain.
- For `elysia-android/`: JDK `17+`, Android SDK + platform tools, Gradle wrapper (`./gradlew`, no install needed). Set SDK path in `elysia-android/local.properties` (file is git-ignored):
  `sdk.dir=/path/to/Android/Sdk`
- For the Electron desktop UI referenced in `workspace/docs/`: Node `18+` + `npm`.

## 1. Clone

```bash
git clone git@github.com:asteroidnolifer-maker/Elysia-desktop-agent.git
cd Elysia-desktop-agent
git status
```

## 1b. Install + launch (one script, all three platforms)

`scripts/elysia_boot.py` is the single installer and launcher for Linux, macOS
and Windows (stdlib only, no build step). The `.sh`, `.ps1` and `.cmd` files at
the repo root are thin shims that only locate a Python 3 interpreter.

```bash
# Linux / macOS
./install.sh                  # prerequisites, dirs, config; prints what to do next
./install.sh --deps --build   # also install missing tools, then build agent-core
./install.sh --with-model     # also fetch llama-server + a GGUF model
./start.sh                    # start model API + agent-core + HUD
./start.sh status             # ports, pids, board, executor
./start.sh stop               # stop what start launched
```

```powershell
# Windows (PowerShell)
.\install.ps1 -Deps -Build
.\start.ps1
.\start.ps1 -Action status
.\start.ps1 -Action stop
# or double-click install.cmd / start.cmd
```

```bash
# any platform, directly
python3 scripts/elysia_boot.py install --dry-run   # show every action, change nothing
python3 scripts/elysia_boot.py start --no-agent    # HUD only
python3 scripts/elysia_boot.py doctor
```

What `install` does — and deliberately does not do:

- checks Python 3.8+, `git`, `curl` (and `go` for the optional `agent-core` build)
- creates `workspace/`, `runtime/models`, `runtime/llama`, `state/`, `logs/`, `config/`
- writes `elysia/config.json` only if it is missing (existing config is kept)
- normalizes `agent-core/agent_config.json` → absolute `workspace_dir` (the shipped
  relative value would otherwise resolve against the binary and land the sandbox
  in `agent-core/workspace`)
- installs missing prerequisites **only** with `--deps`, using winget/choco/scoop,
  Homebrew, or apt/dnf/pacman/zypper/apk, and asks before each one
- never deletes user data, never edits API keys or `config/providers.env`
- `--build` compiles `agent-core` with Go; without Go it reports SKIP with the
  exact command instead of pretending to succeed
- `--with-model` delegates to `runtime/restore-model.sh` when present; if that
  fetcher is absent (it is git-ignored) it prints the two things to download
  instead of inventing URLs
- finishes with a `py_compile` check and `elysia doctor`, and writes
  `state/install.json` (platform, paths, ports)

`start` launches the model API (`:11434`), `agent-core` (`:8085`) and the
HUD/orchestrator (`:8087`, canonical scheduler + in-process executor), waits
for each port to answer, and writes pid files under `state/pids/` plus logs
under `logs/`. It reports **up only after the port really answers**; `stop`
verifies the process is gone before reporting success. Defaults are local-only
(`127.0.0.1`) — pass `--host 0.0.0.0` deliberately to expose the HUD.

Ports are overridable: `ELYSIA_MODEL_PORT`, `ELYSIA_AGENT_PORT`,
`ELYSIA_API_PORT`, or `--port`.

## 2. Get a local model (required)

Option A — scripted (downloads pinned `llama-server` build + Qwen GGUF, then starts it on `:11434`):

```bash
bash runtime/restore-model.sh qwen1.5b
# or: bash runtime/restore-model.sh qwen3b
```

What it does (`runtime/restore-model.sh`):
- Downloads `llama-server` (`b10937`) into `runtime/llama/`.
- Downloads `qwen2.5-1.5b-instruct-q4_k_m.gguf` (or 3B) into `runtime/models/`.
- Starts `llama-server --host 127.0.0.1 --port 11434 --model <gguf> --ctx-size 8192 --threads 4`.

Option B — manual: place any `.gguf` in `runtime/models/` and start the server yourself:

```bash
mkdir -p runtime/models runtime/llama
cp /path/to/your-model.gguf runtime/models/
./runtime/llama/llama-server --host 127.0.0.1 --port 11434 \
  --model runtime/models/your-model.gguf --ctx-size 8192 --threads 4
curl -s http://127.0.0.1:11434/v1/models
```

`orchestrator/airllm.py` knows these model paths (`MODELS` dict) and picks one by free RAM:

```bash
python3 orchestrator/airllm.py status
python3 orchestrator/airllm.py models
python3 orchestrator/airllm.py start qwen1.5b
```

## 3. Build and configure `agent-core`

```bash
cd agent-core
go build -o elysia-agent ./
./elysia-agent
# listens on :8085 by default
```

Configuration is `agent-core/agent_config.json` (read at startup via `InitConfig("agent_config.json")` in `main.go`).
Important: the shipped file contains a Windows `workspace_dir` — **edit it for your machine**.

| Key | Meaning |
|---|---|
| `llm.backend` | `"openai"` (points at local llama-server), `"llama"`, or `"nim"` |
| `llm.openai_base_url` | OpenAI-compatible endpoint, default `http://127.0.0.1:11434/v1` |
| `llm.openai_model` | Model alias sent to the backend (e.g. `qwen2.5-coder:7b`) |
| `llm.temperature` / `llm.max_tokens` | Sampling temperature / response token cap |
| `llm.openai_api_key` | `"none"` for local server; real key only for remote OpenAI |
| `llm.nim_base_url` / `llm.nim_model` | NVIDIA NIM endpoint/model (only if `backend: nim`) |
| `memory_limit_mb` | Model-memory eviction threshold (default `512`) |
| `workspace_dir` | Root dir for generated projects — **set to your checkout's `workspace/`** |
| `sandbox_allow_commands` | Allowlist for commands the agent may run |
| `sandbox_timeout_sec` | Per-command timeout (default `120`) |
| `rate_limit_per_min` | HTTP rate limit (default `60`) |
| `bind_addr` | HTTP listen address (default `:8085`; empty = `ELYSIA_HTTP_ADDR` or `:8085` per `runtime_paths.go`) |

Env overrides:

```bash
ELYSIA_HTTP_ADDR=":8085" ./elysia-agent
ELYSIA_MODEL=/path/to/model.gguf ./elysia-run.sh start
```

## 4. Start the stack

### Unified script

```bash
./elysia-run.sh start
./elysia-run.sh status
# agent:    UP (:8085)
# model:    UP (:11434)
./elysia-run.sh stop
```

> Note: `elysia-run.sh` derives every path from the repository root and respects
> `ELYSIA_MODEL`, `ELYSIA_RUNTIME`, `ELYSIA_WS`, `ELYSIA_AGENT_BIN` overrides.
> If `start` reports `llama-server not found` / `agent-core not built`, either edit those variables
> or start the two processes manually (next section).

### Manual start (no script edits needed)

```bash
# terminal 1 — model
./runtime/llama/llama-server --host 127.0.0.1 --port 11434 \
  --model runtime/models/qwen15b-q4.gguf --alias "qwen2.5-coder:7b" \
  --ctx-size 8192 --parallel 2 --threads 4

# terminal 2 — agent
cd agent-core
go build -o elysia-agent ./
ELYSIA_HTTP_ADDR=":8085" ./elysia-agent
```

## 5. Orchestrator (HUD, taskboard, workers)

All stdlib Python. Defaults bind `127.0.0.1` only.

```bash
# HUD + API on :8087 (logs to orchestrator/logs/server.log)
setsid nohup python3 orchestrator/server.py --port 8087 \
  </dev/null >>orchestrator/logs/server.log 2>&1 &
# open http://127.0.0.1:8087/

# task board
python3 orchestrator/taskboard.py init
python3 orchestrator/taskboard.py list
python3 orchestrator/taskboard.py list open

# adaptive local-worker pool (cap 2 pairs with llama-server --parallel 2)
bash orchestrator/adaptive.sh up 2
bash orchestrator/adaptive.sh status
bash orchestrator/adaptive.sh down

# one-shot chat with the local model (no third-party AI)
python3 orchestrator/brain.py ask "say hi in one line"
# same loop with a different operating style:
python3 orchestrator/brain.py ask --style claude-code "plan a refactor in 3 bullets"
bash orchestrator/ask.sh "list files in workspace"
```

### Provider ecosystem (optional — local model always works)

```bash
./bin/elysia providers --catalog          # every backend + what it needs
./bin/elysia login groq --no-browser      # opens the console URL in your browser
./bin/elysia login groq --paste <KEY>     # stores the key (config/providers.env, 0600)
./bin/elysia hf models                    # curated top open models (GGUF for runtime/)
./bin/elysia knowledge search "port scanner"   # vendored defensive security docs
./bin/elysia prompt                       # system-prompt styles (claude-code, hermes, ...)
```

Activation is credential-gated: a cloud preset joins the runtime provider
set only when its env key is set; a CLI-agent preset (claude/codex/gemini/
opencode/openclaw) only when its binary is on PATH (it reuses that tool's own
login — Elysia never stores those credentials). See `howtotest.md` and
`docs/security/SECURITY_TOOLING.md`.

Flow: `POST /api/ask {goal}` → local model splits the goal into file-owning subtasks
(max `MAX_DIVISION = 6`, rules from `orchestrator/INSTRUCTIONS.md`) → rows in
`orchestrator/taskboard.sqlite` → `worker_local.py` agents claim and complete them → HUD polls `/api/state`.

## 6. Android app

```bash
cd elysia-android
echo "sdk.dir=$HOME/Android/Sdk" > local.properties
./gradlew assembleDebug
./gradlew test
./gradlew :app:assembleDebug
```

APK output: `elysia-android/app/build/outputs/apk/debug/app-debug.apk` (build dirs are git-ignored).
Modules (`settings.gradle.kts`): `:app` (UI, onboarding, chat, OTP, diagnostics),
`:core` (events, memory, settings, link parsing), `:device` (device detection),
`:installer` (atomic install, verifier, downloads), `:runtime` (ONNX/inference engine,
tokenizer), `:models` (model manager + manifest), `:diagnostics`, `:permissions`.

## 7. Verify

```bash
# model
curl -s http://127.0.0.1:11434/v1/models

# agent-core
curl -s http://127.0.0.1:8085/health
curl -s http://127.0.0.1:8085/status
curl -s -X POST http://127.0.0.1:8085/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hello, who are you?"}'

# orchestrator HUD API
curl -s http://127.0.0.1:8087/api/state | head -c 500
```

## Ports

| Port | Service | Source |
|---|---|---|
| `11434` | `llama-server` (OpenAI-compatible `/v1`) | `elysia-run.sh`, `airllm.py`, `brain.py` |
| `8085` | `agent-core` HTTP API | `agent-core/config.go`, `runtime_paths.go` |
| `8087` | orchestrator HUD + API (`server.py --port`) | `orchestrator/server.py` |

(`workspace/docs/README.md` also mentions `8080/8095/8787` as example/legacy ports;
the current defaults in code are the three above.)

## API cheat sheet

agent-core (`agent-core/server.go` routes):

- `GET /health`, `GET /status`
- `GET /models`, `POST /models/register`, `GET /models/catalog`, `GET /models/recommend`
- `POST /chat` — `{"message": "..."}` (see `elysia-run.sh` READY text)
- `POST /task`, `GET /task/{id}`
- `GET /api/link/status`

orchestrator (`orchestrator/server.py` docstring):

- `GET /` (HUD), `GET /api/state`, `GET /api/tasks?status=&n=`, `GET /api/agents`, `GET /api/agent-log?worker=<id>&n=`
- `POST /api/ask {goal, files?}`, `POST /api/pool {action: start|stop, cap?}`, `POST /api/task {title, description, files}`
- `POST /api/agent {task}` — master control plane: plans, persists the task graph, drives the logical agents and returns the trace; `GET /api/scheduler`, `POST /api/executor {action: status|start|stop}`

## Runtime tool layer, simulation, routing, health

Agents never touch the filesystem directly: owned-file writes go through the
canonical permissioned tool layer (`elysia/core/toolkit.py`), and a role that
lacks `workspace:write` fails loudly instead of silently changing files.

```bash
./bin/elysia tools --registry                  # tools + risk + required permissions
./bin/elysia tools --registry --role implementer   # allow/deny per role, with reasons
./bin/elysia master route --caps chat,coding   # why this provider/model was chosen
./bin/elysia master simulate "<goal>"          # dry run — writes nothing
./bin/elysia health                            # 10 independent health dimensions
```

Permission levels are escalating bundles (`read_only`, `workspace_write`,
`git_write`, `network`, `browser`, `desktop`, `system`) configured under
`tools.default_permissions` (the ceiling for every role) and
`tools.role_permissions` (per-role overrides). Reviewers
(`code_reviewer`, `security_reviewer`, `planner`, ...) are forced read-only.
Desktop/clipboard control needs both `tools.allow_high_risk: true` and the
`desktop:control` permission, and reports the backend unavailable on headless
hosts instead of pretending. Set `tools.enabled: false` to fall back to direct
path-validated workspace writes.

## Workflows, budgets and board maintenance

Workflows are real node graphs over the durable task board (no second state
store). Gates are board rows no worker can claim:

```bash
./bin/elysia workflow start --file nodes.json --name demo   # task/approval/join/
./bin/elysia workflow tick                                  # fallback/retry/timeout/rollback
./bin/elysia workflow state demo                            # node table + awaiting approval
./bin/elysia workflow approve --node 119                    # human gate (deny cascades)
./bin/elysia db health | backup state/backups | restore FILE | vacuum
```

Approval gates block downstream work until a human resolves them; a denial
cancels the branch instead of proceeding. Joins complete only when every
sibling completed. `providers.set_budget(max_usd, warn_usd)` enforces an
estimated-spend ceiling: paid providers are dropped (visible in
`master route`), local models keep serving, and an all-paid fleet queues work
instead of silently spending.

## Memory, context planning, self-healing, task graphs

Four subsystems sit behind every model call. All four are wired into the live
pipeline (not side libraries), and none of them fabricates success.

**Layered memory** (`elysia/core/memory.py`) — separate namespaces (task,
workflow, project, repo, user_prefs, agents, providers, failure, solution,
decision, architecture, research, tools, history) with per-record
`importance`, `confidence`, `provenance`, TTL, recall counters and a content
hash. Identical content is deduplicated instead of duplicated; compaction drops
expired records and *compresses* the oldest low-value ones into a summary record
(the keys it replaced are kept, never silently destroyed).

```bash
./bin/elysia memory stats
./bin/elysia memory timeline --ns solution
./bin/elysia memory recall "provider timeout"
./bin/elysia memory backup state/memory-backup.json
./bin/elysia memory invalidate --ns decision --key dec_1 --reason superseded
./bin/elysia memory compact
```

**Context planner** (`elysia/core/context.py`) — answers "what does this agent
actually need?" instead of dumping the repository into every prompt. Layers
(system, task, files, failures, tests, memory, review, provider, capabilities)
compete for a token budget by per-role priority; a long layer keeps its recent
*TAIL*; every included/dropped layer is reported with its source and reason,
and the plan is cached until its inputs change (any `add`/`invalidate`).

**Self-healing** (`elysia/core/healing.py`) — one classifier decides what a
failure *is* (`provider_timeout`, `provider_rate_limit`, `sqlite_busy`,
`stale_lease`, `qa_failure`, `test_failure`, `malformed_model_output`, …), what
to do about it (retry / retry-after-backoff / failover / replan / escalate /
give up) from real evidence, and how long to wait: the configured
`retry_backoff_s` is the per-attempt base and the failure class scales it
exponentially with deterministic jitter. Retries are bounded per class, so no
code path can build an infinite retry loop. Recovery routines do real work
(release a stale lease, reclaim disk via memory compaction + DB vacuum,
re-probe providers) and report honestly when they cannot run. Dangerous
conditions are never auto-fixed: a git conflict escalates to a human because
resolving it could destroy someone else's work.

```bash
./bin/elysia healing policies                     # the whole taxonomy + policy table
./bin/elysia healing classify "HTTP 429 too many requests"
./bin/elysia healing report
```

**Provider health** (`elysia/core/providers.py`) — every provider keeps an
availability history: consecutive failures, circuit state, trips, cooldown,
success rate over the last 20 outcomes and a bounded incident timeline. Three
consecutive failures quarantine it (circuit open, 30s cooldown doubling per
trip, capped at 900s) and it stops being selected; `master route` then says
*why* ("circuit open after 1 trip(s)/3 failures, 30s cooldown left") instead of
a vague "degraded". When the cooldown elapses exactly ONE half-open probe is
allowed — success closes the circuit, failure re-quarantines for longer — and an
abandoned probe ticket expires so nothing is locked out forever. Transitions are
published once each as `provider.quarantined` / `provider.half_open` /
`provider.recovered`, so a run timeline shows why a provider vanished, and the
health dimension reports `N quarantined (circuit open)`.

```bash
./bin/elysia master status     # circuit / trips / success rate per provider
./bin/elysia master route --caps chat,coding
./bin/elysia health
```

**Task-graph intelligence** (`elysia/core/graph.py`) — a plan is checked as a
GRAPH before anything runs: unknown/self dependencies, cycles, two writers of
one file, a task that mentions another task's file without depending on it,
tasks nothing can execute, oversized tasks, trivial tasks, existing-vs-new
files. `replan()` then applies only the repairs that are safe and mechanical —
dropping invalid edges, breaking cycles, giving a file one owner, splitting
oversized tasks — and reports every change. Dependencies are remapped through an
explicit old→new table, so splitting a task wires its dependents to *every*
part and merging can never leave a stale index or a cycle. The planner path
repairs automatically; an explicit plan is never rewritten, and its available
repairs are shown instead:

```bash
./bin/elysia master simulate "refactor the utils module"   # plan + analyse + estimate
./bin/elysia master simulate "plan check" --file plan.json # analyse a plan offline
```

`simulate` reports the conflicts the RAW planner output had, the repairs the
master would apply, the repairs available for an explicit plan, and heuristic
duration/token estimates (labelled as heuristics, never as telemetry).

## Secrets — do not commit

`.gitignore` already blocks: `.env` / `*.env` / `*.key` / `*.pem` / `*token*` / `*secret*`,
`config/composio.env`, model weights (`*.gguf`, `runtime/models/`, `runtime/llama/`),
build outputs (`dist/`, `**/build/`, `*.exe`, `*.so`), DBs (`*.sqlite`, `*.db`, `TASKS.md`),
logs (`logs/`, `*.log`), `workspace/videos|cache|agents|repos/`, IDE files.
Keep your `config/composio.env`, API keys, and `.gguf` files local only.

## Troubleshooting

- `llama-server not found` / `agent-core not built` from `elysia-run.sh` → set `ELYSIA_LLAMA_BIN` / `ELYSIA_AGENT_BIN` / `ELYSIA_MODEL` to the real locations, or use the manual start above.
- `agent-core` binds `:8085` already in use → `lsof -i :8085`, or `ELYSIA_HTTP_ADDR=":8086" ./elysia-agent`.
- `Model not found` → `ls runtime/models/`, check `agent_config.json` URLs point at `:11434`, run `python3 orchestrator/airllm.py status`.
- `llama-server` OOM → smaller model (`qwen1.5b`), lower `--ctx-size`, fewer `--parallel`.
- Android `sdk.dir` missing → create `elysia-android/local.properties` (ignored by git).
- `ssh -T git@github.com` fails → deploy key must be on **`Elysia-desktop-agent`** repo settings (`.../Elysia-desktop-agent/settings/keys`) with write access, not on another repo.
