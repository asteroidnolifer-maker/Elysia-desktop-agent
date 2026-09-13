#!/usr/bin/env bash
# Elysia adaptive coordinator — LOCAL workers only (NO opencode).
#
# Self-balancing pool of lightweight python workers (worker_local.py) against
# the shared SQLite task board. Each worker is one small python process that
# talks to the local llama-server; hardware stays safe: cap 2 workers,
# RAM guard pauses spawning under 2GB free.
#
# Usage:
#   ./adaptive.sh up [cap]    start the (single, flock-guarded) pool
#   ./adaptive.sh down        stop the pool + workers
#   ./adaptive.sh status      show pool + board state
set -euo pipefail

ORCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$ORCH_DIR")"
WS_DIR="${ELYSIA_WS:-$REPO_ROOT/workspace}"
RUN_DIR="$ORCH_DIR/.adaptive"
mkdir -p "$RUN_DIR"
PID_FILE="$RUN_DIR/pids"
LOG="$RUN_DIR/adaptive.log"
LOCK="$RUN_DIR/pool.lock"
touch "$LOG"
say() { printf '[adaptive] %s\n' "$*" | tee -a "$LOG"; }

probe() {
  local load mem_avail cores
  cores="$(nproc)"
  load="$(awk '{print $1}' /proc/loadavg)"
  mem_avail="$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)"
  local load_head
  load_head="$(python3 -c "print(max(0, round($cores*0.8 - $load,1)))")"
  printf '%s %s' "$load_head" "$mem_avail"
}

current() {
  local c
  c="$(pgrep -f "[w]orker_local.py" 2>/dev/null | wc -l)"
  [[ "$c" =~ ^[0-9]+$ ]] || c=0
  printf '%s\n' "$c"
}

spawn() {  # spawn <id>
  local id="$1"
  setsid python3 "$ORCH_DIR/worker_local.py" "ad-$id" "$WS_DIR" 3 \
    </dev/null >>"$LOG" 2>&1 &
  echo "$! $id" >> "$PID_FILE"
  say "spawned local worker ad-$id (pid $!)"
}

reap() {
  local line newlines=()
  while read -r pid id; do
    [[ -z "$pid" ]] && continue
    if kill -0 "$pid" 2>/dev/null; then
      newlines+=("$pid $id")
    else
      say "reaped finished worker ad-$id"
    fi
  done < "$PID_FILE"
  : > "$PID_FILE"
  for line in "${newlines[@]:-}"; do
    printf '%s\n' "$line" >> "$PID_FILE"
  done
}

case "${1:-status}" in
  up)
    CAP="${2:-2}"   # 2 workers pair with llama-server --parallel 2
    exec 9>"$LOCK"
    if ! flock -n 9; then
      echo "[adaptive] another pool is already running; quitting" | tee -a "$LOG"
      exit 0
    fi
    python3 "$ORCH_DIR/taskboard.py" init >/dev/null
    say "adaptive pool starting (cap=$CAP, ws=$WS_DIR, backend=local-llama)"
    local_clock=0
    while :; do
      local_clock=$((local_clock+1))
      open="$(python3 "$ORCH_DIR/taskboard.py" list open | wc -l)"
      claimed="$(python3 "$ORCH_DIR/taskboard.py" list claimed | wc -l)"
      # wind down only when nothing is open AND nothing is claimed/in-progress
      if [[ "$open" -eq 0 && "$claimed" -eq 0 ]]; then
        say "board empty; wind down"
        break
      fi
      read -r load_head mem_avail <<< "$(probe)"
      load_head="${load_head%.*}"; [[ -z "$load_head" ]] && load_head=0
      mem_avail="${mem_avail%.*}";  [[ -z "$mem_avail" ]] && mem_avail=0
      active="$(current)"
      want=$(( load_head + 1 )); [[ "$want" -gt "$CAP" ]] && want="$CAP"
      # RAM guard: ALWAYS leave >= RESERVE_MB (1.5GB) free for the system.
      # Each worker is estimated at WORKER_MB, so want is capped at the count
      # that keeps mem_avail - want*WORKER_MB >= RESERVE_MB.
      RESERVE_MB=1536
      WORKER_MB=600
      max_by_ram=$(( (mem_avail - RESERVE_MB) / WORKER_MB ))
      [[ "$max_by_ram" -lt 0 ]] && max_by_ram=0
      [[ "$want" -gt "$max_by_ram" ]] && want="$max_by_ram"
      # never shrink the pool mid-task (adaptive never kills workers)
      [[ "$want" -lt "$active" ]] && want="$active"
      say "cycle $local_clock: load_head=$load_head mem=${mem_avail}MB active=$active want=$want open=$open claimed=$claimed"
      if [[ "$want" -gt "$active" ]]; then
        for (( i=active; i<want; i++ )); do spawn "${local_clock}-$i"; done
      fi
      reap
      sleep 10
    done
    say "adaptive pool finished (board drained)"
    ;;
  down)
    if [[ -f "$PID_FILE" ]]; then
      while read -r pid id; do
        [[ -z "$pid" ]] && continue
        kill "$pid" 2>/dev/null || true
      done < "$PID_FILE"
      : > "$PID_FILE"
    fi
    pkill -f "worker_local.py" 2>/dev/null || true
    say "pool stopped"
    ;;
  status)
    echo "active local workers: $(current)"
    echo "board:"
    python3 "$ORCH_DIR/taskboard.py" list
    ;;
  *)
    echo "usage: $0 {up [cap] | down | status}"
    exit 1
    ;;
esac
