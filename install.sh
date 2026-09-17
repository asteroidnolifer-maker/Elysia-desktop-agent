#!/usr/bin/env sh
# Elysia installer — Linux + macOS.
# Thin shim: locates a Python 3 interpreter and runs the universal installer.
#
#   ./install.sh                 check prerequisites, create dirs/config
#   ./install.sh --deps          also install missing prerequisites
#   ./install.sh --build         build agent-core (needs Go)
#   ./install.sh --with-model    fetch llama-server + a GGUF model
#   ./install.sh --dry-run       show every action, change nothing
#
# Windows: use install.ps1 or install.cmd
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "[elysia] Python 3.8+ is required but no python3/python was found." >&2
  echo "         Linux : sudo apt-get install -y python3   (or dnf/pacman/zypper/apk)" >&2
  echo "         macOS : brew install python3" >&2
  exit 1
fi

exec "$PY" "$ROOT/scripts/elysia_boot.py" install "$@"
