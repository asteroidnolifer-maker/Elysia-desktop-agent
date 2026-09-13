#!/usr/bin/env bash
# Ask the local Elysia model directly. NO opencode, NO third-party AI.
# Usage: ./ask.sh "your prompt here"     (or: ./ask.sh < file, or interactive if no args)
set -euo pipefail
ORCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! bash "$ORCH_DIR/../../elysia/elysia-run.sh" status 2>/dev/null | grep -q "model:    UP"; then
  echo "[ask] local model is DOWN — starting stack..."
  bash "${ORCH_DIR%orchestrator}elysia-run.sh" start >/dev/null 2>&1 || \
    bash /home/myusername/elysia/elysia-run.sh start
fi

if [[ $# -gt 0 ]]; then
  exec python3 "$ORCH_DIR/brain.py" ask "$*"
else
  echo "[ask] interactive mode (ctrl-c to exit). Talking to local qwen2.5-coder."
  while true; do
    printf "you> "
    IFS= read -r line || break
    [[ -z "$line" ]] && continue
    python3 "$ORCH_DIR/brain.py" ask "$line" || true
    echo
  done
fi
