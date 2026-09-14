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
| `elysia/` | Rearchitected core package: `core/config.py`, `core/paths.py` (secure path resolution), `core/providers.py`, `core/tasks.py`, `core/scheduler.py`, `core/executor.py` (in-process task execution), `core/qa.py`, `core/events.py`, `core/git.py`, `core/workspace.py`, `core/toolcatalog.py` (machine capability detection), `core/briefing.py` (Jarvis-style status fusion), `core/knowledge.py` (multi-domain tooling docs) + more. `elysia/config.json` is the single source of configuration. |
| Provider ecosystem | `core/provider_presets.py` — one catalog: local llama.cpp/Ollama, cloud OpenAI-compatible APIs (OpenRouter, Groq, Together, DeepSeek, Mistral, xAI, NVIDIA NIM, GitHub Models, Cerebras, Gemini, HuggingFace, Freebuff-style gateways) and CLI coding agents (Claude Code, Codex, Gemini CLI, OpenCode, OpenClaw). A preset activates only when its credential env var is set (API) or its binary is on PATH (CLI). `core/browser_login.py` — `elysia login <provider>` opens the provider's console in the desktop browser and stores keys in `config/providers.env` (0600, git-ignored). |
| `docs/` | `ARCHITECTURE_AUDIT.md` (Phase 1 audit), `ARCHITECTURE.md` (target architecture), `IMPLEMENTATION_STATE.md` (status of the rearchitecture), `knowledge/kali-tools/` (vendored defensive-first security-tooling docs, indexed by `elysia.core.knowledge`), `security/SECURITY_TOOLING.md` (tooling policy). |
| `tests/` | `python3 -m unittest discover -s tests` — 147 unit tests (paths/security, providers, scheduler, QA, redaction, worker write security, features bundle, server API, provider presets/login/knowledge/HF, runtime wiring: crash recovery, lease heartbeat, failover, resource queueing, end-to-end executor: goal→file→QA→completion with failover/retry/dependencies). |
| `runtime/` | Local inference runtime (**not committed**: binaries/models). `restore-model.sh` downloads `llama-server` + Qwen GGUF into `runtime/llama/` + `runtime/models/`. |
| `elysia-android/` | Android app (Gradle, AGP `8.13.2`, Kotlin `2.2.21`). Modules: `:app`, `:core`, `:device`, `:installer`, `:runtime`, `:models`, `:diagnostics`, `:permissions`. |
| `workspace/` | Generated projects, `tools/` scripts, `docs/` notes. `workspace/repos/` (cloned test projects), `*.db`, `*.log`, `cache/` are git-ignored. |
| `scripts/` | Task-board generators (`generate_*.py`, `gen_unique_tasks.py`). Run manually as needed. |
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
