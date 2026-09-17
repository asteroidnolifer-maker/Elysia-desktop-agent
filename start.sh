#!/usr/bin/env sh
# Elysia launcher — Linux + macOS.
# Thin shim around the universal launcher (scripts/elysia_boot.py).
#
#   ./start.sh                 start model API + agent-core + HUD
#   ./start.sh --no-model      start only agent-core + HUD
#   ./start.sh --host 0.0.0.0  expose the HUD on your network
#   ./start.sh stop            stop everything this script started
#   ./start.sh status          ports, pids, board summary
#   ./start.sh doctor          repository health check
#
# Windows: use start.ps1 or start.cmd
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
  exit 1
fi

# Allow `./start.sh stop|status|restart|doctor|install` as well as the default.
VERB="start"
case "${1:-}" in
  start|stop|restart|status|doctor|install)
    VERB="$1"
    shift
    ;;
esac

exec "$PY" "$ROOT/scripts/elysia_boot.py" "$VERB" "$@"
