#!/usr/bin/env bash
# Restore local LLM for Elysia: downloads llama-server binary + a small GGUF.
# Usage: bash restore-model.sh [qwen1.5b|qwen3b]
# Needs ~2GB disk. Run once; then: python3 /data/elysia/orchestrator/airllm.py
set -euo pipefail
MODEL="${1:-qwen1.5b}"
RUNTIME=/data/elysia/runtime
mkdir -p "$RUNTIME/models" "$RUNTIME/llama"

# 1) llama-server binary (llama.cpp release, ggml-org - ggerganov is dead)
# Pinned build b10937 (verified 2026-09-13) - 'latest' has no stable binary assets.
LLAMA_BUILD="b10937"
if [ ! -x "$RUNTIME/llama/llama-server" ]; then
  echo "[*] fetching llama-server binary ($LLAMA_BUILD)..."
  URL="https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_BUILD}/llama-${LLAMA_BUILD}-bin-ubuntu-x64.tar.gz"
  TMPGZ="/tmp/llama-bin.tar.gz"
  curl -L --retry 3 --max-time 600 -o "$TMPGZ" "$URL" || {
    echo "[!] binary download failed. Get a release from:"; echo "    https://github.com/ggml-org/llama.cpp/releases"; exit 1; }
  tar -xzf "$TMPGZ" -C "$RUNTIME/llama" --wildcards '*/llama-server' --strip-components=1 2>/dev/null \
    || { mkdir -p /tmp/llx && tar -xzf "$TMPGZ" -C /tmp/llx && cp "$(find /tmp/llx -name llama-server | head -n 1)" "$RUNTIME/llama/llama-server"; }
  chmod +x "$RUNTIME/llama/llama-server"
  rm -f "$TMPGZ"
  "$RUNTIME/llama/llama-server" --version || echo "[!] binary runs?"
fi

# 2) model weights (Qwen instruct, Q4 quant - small + capable)
case "$MODEL" in
  qwen1.5b)
    URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf"
    OUT="$RUNTIME/models/qwen15b-q4.gguf" ;;
  qwen3b)
    URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
    OUT="$RUNTIME/models/qwen3b-q4.gguf" ;;
  *) echo "unknown model $MODEL"; exit 1 ;;
esac
if [ ! -f "$OUT" ]; then
  echo "[*] downloading $MODEL (~1-2GB)..."
  curl -L --max-time 1800 -o "$OUT" "$URL"
else
  echo "[=] model already present: $OUT"
fi

echo "[*] starting model on :11434..."
"$RUNTIME/llama/llama-server" --host 127.0.0.1 --port 11434 \
  --model "$OUT" --ctx-size 8192 --threads 4 &
sleep 5
curl -s --max-time 5 http://127.0.0.1:11434/v1/models && echo && echo "[+] LLM UP"
