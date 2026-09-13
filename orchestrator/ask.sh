#!/usr/bin/env bash
# Ask the local Elysia model directly. NO opencode, NO third-party AI.
# Usage: ./ask.sh "your prompt here"     (or: ./ask.sh < file, or interactive if no args)
set -euo pipefail
ORCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$ORCH_DIR")"
RUN_SH="$REPO_ROOT/elysia-run.sh"

if ! bash "$RUN_SH" status 2>/dev/null | grep -q "model:    UP"; then
  echo "[ask] local model is DOWN — starting stack..."
  bash "$RUN_SH" start >/dev/null 2>&1 || true
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
