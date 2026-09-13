#!/usr/bin/env bash
# Elysia unified launcher (Linux) - starts llama-server + agent-core
# Usage: ./elysia-run.sh [start|stop|status|restart]

set -euo pipefail

MODEL_DIR="/data/Elysia/elysia/runtime/models"
LLAMA_BIN="/data/Elysia/elysia/runtime/llama/llama-server"
AGENT_DIR="/data/elysia-run/agent-core"
AGENT_BIN="$AGENT_DIR/elysia-agent"
WORKSPACE="/data/elysia-run/workspace"

PORT_LLAMA=11434
PORT_AGENT=8085

# Choose model: default qwen15b (941MB, fast), override with ELYSIA_MODEL
MODEL="${ELYSIA_MODEL:-$MODEL_DIR/qwen15b-q4.gguf}"
ALIAS="qwen2.5-coder:7b"

if [[ "${1:-}" == "stop" ]]; then
  pkill -f "elysia-agent" 2>/dev/null || true
  pkill -f "llama-server.*$PORT_LLAMA" 2>/dev/null || true
  echo "[elysia] stopped"
  exit 0
fi

if [[ "${1:-}" == "status" ]]; then
  (echo > /dev/tcp/127.0.0.1/$PORT_AGENT) 2>/dev/null && echo "agent:    UP (:$PORT_AGENT)" || echo "agent:    DOWN"
  (echo > /dev/tcp/127.0.0.1/$PORT_LLAMA) 2>/dev/null && echo "model:    UP (:$PORT_LLAMA)" || echo "model:    DOWN"
  exit 0
fi

if [[ ! -f "$LLAMA_BIN" ]]; then echo "[elysia] ERROR: llama-server not found at $LLAMA_BIN"; exit 1; fi
if [[ ! -f "$MODEL" ]]; then  echo "[elysia] ERROR: model not found: $MODEL (set ELYSIA_MODEL)"; exit 1; fi
if [[ ! -f "$AGENT_BIN" ]]; then echo "[elysia] ERROR: agent-core not built at $AGENT_BIN"; exit 1; fi

if ! (echo > /dev/tcp/127.0.0.1/$PORT_LLAMA) 2>/dev/null; then
  echo "[elysia] starting llama-server ($(basename "$MODEL"))..."
  setsid "$LLAMA_BIN" --host 127.0.0.1 --port $PORT_LLAMA \
    --model "$MODEL" --alias "$ALIAS" \
    --ctx-size 8192 --parallel 2 --threads 4 \
    </dev/null >/tmp/elysia-llama.log 2>&1 &
  for i in $(seq 1 30); do
    (echo > /dev/tcp/127.0.0.1/$PORT_LLAMA) 2>/dev/null && break
    sleep 1
  done
  (echo > /dev/tcp/127.0.0.1/$PORT_LLAMA) 2>/dev/null || { echo "[elysia] ERROR: llama-server failed to start (see /tmp/elysia-llama.log)"; exit 1; }
  echo "[elysia] llama-server up on :$PORT_LLAMA"
else
  echo "[elysia] llama-server already running"
fi

if ! (echo > /dev/tcp/127.0.0.1/$PORT_AGENT) 2>/dev/null; then
  echo "[elysia] starting agent-core..."
  mkdir -p "$WORKSPACE"
  (cd "$AGENT_DIR" && setsid env ELYSIA_HTTP_ADDR=":$PORT_AGENT" \
    ./elysia-agent </dev/null >/tmp/elysia-agent.log 2>&1 &)
  for i in $(seq 1 30); do
    (echo > /dev/tcp/127.0.0.1/$PORT_AGENT) 2>/dev/null && break
    sleep 1
  done
  (echo > /dev/tcp/127.0.0.1/$PORT_AGENT) 2>/dev/null || { echo "[elysia] ERROR: agent-core failed to start (see /tmp/elysia-agent.log)"; exit 1; }
  echo "[elysia] agent-core up on :$PORT_AGENT"
else
  echo "[elysia] agent-core already running"
fi

echo
echo "[elysia] READY"
echo "  chat endpoint : http://127.0.0.1:$PORT_AGENT/chat  (POST {\"session_id\",\"message\"})"
echo "  model API     : http://127.0.0.1:$PORT_LLAMA/v1"
echo
echo "  quick check:"
echo "    curl -s http://127.0.0.1:$PORT_AGENT/health"
