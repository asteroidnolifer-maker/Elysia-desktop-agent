# Elysia

![Build](https://img.shields.io/badge/build-passing-brightgreen)

Desktop agent GUI, offline AI inference, and Android ROM tooling.

## Table of Contents

- [Architecture](#architecture)
- [Linux Quick-Start](#linux-quick-start)
  - [1. Install system dependencies](#1-install-system-dependencies)
  - [2. Install Node dependencies and build the desktop app](#2-install-node-dependencies-and-build-the-desktop-app)
  - [3. Build llama.cpp (local inference server)](#3-build-llamacpp-local-inference-server)
  - [4. Add a GGUF model](#4-add-a-gguf-model)
  - [5. Start llama-server](#5-start-llama-server)
  - [6. Build and start agent-core](#6-build-and-start-agent-core)
  - [7. Verify](#7-verify)
- [Windows (PowerShell)](#windows-powershell)
- [Available Ports](#available-ports)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)

## Architecture

- **Desktop app** (`src/`): Electron + React (Vite) UI for project generation, chat, and device management.
- **agent-core** (`agent-core/`): Lightweight Go daemon providing offline LLM inference via a local llama.cpp server and an HTTP JSON API (port 8085).
- **Runtime**: llama.cpp binaries + GGUF model files stored under `$ELYSIA_RUNTIME_DIR` (defaults to `~/.local/share/elysia/runtime`).

---

## Linux Quick-Start

### 1. Install system dependencies

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install -y build-essential cmake ninja-build git curl wget \
  nodejs npm golang-go

# Fedora
sudo dnf install -y gcc-c++ cmake ninja-build git curl wget nodejs npm golang

# Arch
sudo pacman -Syu --needed base-devel cmake ninja git curl wget nodejs npm go
```

Verify versions:
```bash
node --version   # 18+
go version       # 1.20+
cmake --version
```

### 2. Install Node dependencies and build the desktop app

```bash
cd /path/to/elysia/workspace
npm ci
npm run typecheck   # optional: verify TypeScript
npm run build       # builds renderer + electron
```

### 3. Build llama.cpp (local inference server)

```bash
RUNTIME="${ELYSIA_RUNTIME_DIR:-$HOME/.local/share/elysia/runtime}"
mkdir -p "$RUNTIME/llama" "$RUNTIME/models"

# Clone and build
tmp=$(mktemp -d)
git clone --depth 1 https://github.com/ggml-org/llama.cpp "$tmp/llama.cpp"
cmake -S "$tmp/llama.cpp" -B "$tmp/build" -G Ninja -DLLAMA_CURL=OFF
cmake --build "$tmp/build" --config Release -j$(nproc)

# Install server binary
cp "$tmp/build/bin/llama-server" "$RUNTIME/llama/"
rm -rf "$tmp"

echo "llama-server installed -> $RUNTIME/llama/llama-server"
```

### 4. Add a GGUF model

Place at least one GGUF model file in the runtime models directory:

```bash
cp /path/to/your-model.gguf "$RUNTIME/models/"
ls "$RUNTIME/models/"
```

Popular small models for testing: `tinyllama-1.1b-chat`, `qwen2.5-coder-1.5b`, `phi-2`.

### 5. Start llama-server

```bash
RUNTIME="${ELYSIA_RUNTIME_DIR:-$HOME/.local/share/elysia/runtime}"
MODEL="$RUNTIME/models/your-model.gguf"

"$RUNTIME/llama/llama-server" \
  --model "$MODEL" \
  --host 127.0.0.1 \
  --port 8080 \
  --ctx-size 4096
```

The server is ready when you see `llama server listening on 127.0.0.1:8080`.

### 6. Build and start agent-core

```bash
cd agent-core
go build -o agent-core ./
```

Configure agent-core to use the llama-server backend. Edit `agent_config.json`:

```json
{
    "llm": {
      "backend": "openai",
      "openai_base_url": "http://127.0.0.1:8080/v1",
      "openai_model": "your-model",
      "temperature": 0.3,
      "max_tokens": 1024
    },
  "workspace_dir": "./workspace"
}
```

Start the agent:

```bash
./agent-core
# Listening on :8085
```

### 7. Verify

```bash
# Check llama-server health
curl http://127.0.0.1:8080/health

# Check agent-core status
curl http://127.0.0.1:8085/status

# Monitor the whole Elysia stack (services + system snapshot)
curl http://127.0.0.1:8085/monitor
curl http://127.0.0.1:8085/monitor/services

# Quick inference test via agent-core
curl -s -X POST http://127.0.0.1:8085/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hello, who are you?"}'
```

---

## Windows (PowerShell)

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned -Force  # if script errors
npm ci
npm run dev          # start Vite dev server
npm start            # in a second terminal — launches Electron
```

The bundled `runtime/` directory contains Windows llama.cpp binaries and GGUF models. Set `ELYSIA_RUNTIME_DIR` to override.

---

## Available Ports

| Port  | Service                        |
|-------|--------------------------------|
| 8080  | llama-server (warm model)      |
| 8085  | agent-core HTTP API            |
| 8095  | embedding server               |
| 8787  | companion server (phone link)  |

---

## Configuration

agent-core reads `agent_config.json` from its working directory. Key fields:

| Field                        | Description                                      |
|------------------------------|--------------------------------------------------|
| `llm.backend`                | `openai`, `llama`, or `nim`                      |
| `llm.openai_base_url`        | OpenAI-compatible endpoint (e.g. llama-server)   |
| `llm.openai_model`           | Model name to pass to the backend                |
| `llm.temperature`            | Sampling temperature (0.0 - 1.0)                |
| `llm.max_tokens`             | Max tokens per response                          |
| `memory_limit_mb`            | Model memory eviction threshold (MB)             |
| `workspace_dir`              | Root directory for generated projects            |
| `bind_addr`                  | HTTP listen address (default `:8085`)            |
| `api_key`                    | If set, mutating endpoints require this key      |

LLM settings can also be updated at runtime via `POST /config/update`.

---

## Troubleshooting

- **PowerShell "npm.ps1 cannot be loaded"**: See `docs/INSTALLATION.md`.
- **Electron blank page**: Ensure Vite dev server is running (`npm run dev`) before `npm start`.
- **agent-core won't start on port 8085**: Another process is using it — check with `lsof -i :8085`.
- **llama-server OOM**: Use a smaller model or reduce `--ctx-size`.
- **Models not found**: Verify `ELYSIA_RUNTIME_DIR` points to the correct path, or that `$RUNTIME/models/` contains `.gguf` files.
